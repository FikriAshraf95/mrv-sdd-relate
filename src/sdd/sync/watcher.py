"""The watcher (SPEC-04 §1; plan M02 §1): poll or native, debounced into batches.

``poll`` is required in Docker on Windows (inotify sees none of the host's edits through a bind
mount). It keeps one snapshot ``{path: (mtime_ns, size)}`` and runs two schedules, one thread each:

* the **SDD poll** (``poll_interval``) stats every known SDD file and lists the *glob base
  directories* of the SDD document globs, which finds new SDD files without walking the tree;
* the **code poll** (``poll_code_interval``) walks the whole root and stats every file.

``native`` uses one recursive ``watchdog`` observer. Both feed one debouncer: paths collect until
``debounce`` seconds pass without a new one, then one :class:`Batch` goes to ``on_batch`` on a
dedicated thread, so batches never overlap. Non-SDD paths are delivered too (the code walker uses
them). Both polls and the native handler share the walker's :class:`~sdd.sync.files.IgnoreRules`;
the code poll re-reads the ignore files on every poll (SPEC-04 §1).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from sdd.config import Settings
from sdd.errors import SddError
from sdd.sync import files, indexer

__all__ = ["Batch", "Watcher", "glob_bases"]

log = logging.getLogger("sdd.watcher")

# Document kinds that live in ``settings.paths`` and are polled by the SDD poll.
SDD_PATH_KEYS = ("specs", "milestones", "plans", "deviations", "deviation_index", "docs")
_GLOB_CHARS = frozenset("*?[")
_Stat = tuple[int, int]  # (st_mtime_ns, st_size)
CODE_BACKOFF = 10.0  # the code poll waits >= 10x its last duration (SPEC-04 §1, M02.8)


@dataclass(frozen=True, slots=True)
class Batch:
    paths: frozenset[str]  # project-relative POSIX paths created, modified or deleted
    sdd_files: Mapping[str, str]  # current {path: kind} of SDD documents, after this batch


def glob_bases(settings: Settings) -> dict[str, bool]:
    """``{base directory: recursive}`` for the SDD document globs (SPEC-04 §1 polling rule).

    The base is the literal folder prefix of a glob (``""`` = the project root). A base followed
    by ``**`` is walked recursively, others are listed one level. The project root is never
    walked here, even for ``**/CLAUDE.md``: nested matches are found by the code poll.
    """
    bases: dict[str, bool] = {}
    for key in SDD_PATH_KEYS:
        for glob in settings.paths.get(key, ()):
            parts = glob.split("/")
            folders = parts[:-1]
            literal: list[str] = []
            for part in folders:
                if _GLOB_CHARS & set(part):
                    break
                literal.append(part)
            base = "/".join(literal)
            recursive = len(literal) < len(folders) and folders[len(literal)] == "**" and bool(base)
            bases[base] = bases.get(base, False) or recursive
    return bases


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


class _Debouncer:
    """Collects paths; hands one batch to ``deliver`` once ``delay`` passes with nothing new."""

    def __init__(self, delay: float, deliver: Callable[[frozenset[str]], None]) -> None:
        self._delay = delay
        self._deliver = deliver
        self._cond = threading.Condition()
        self._pending: set[str] = set()
        self._last = 0.0
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name="sdd-batches", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def add(self, paths: set[str] | frozenset[str]) -> None:
        if not paths:
            return
        with self._cond:
            self._pending |= paths
            self._last = time.monotonic()
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._pending.clear()
            self._cond.notify()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._stopped:
                    if not self._pending:
                        self._cond.wait()
                        continue
                    remaining = self._last + self._delay - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cond.wait(remaining)
                if self._stopped:
                    return
                batch = frozenset(self._pending)
                self._pending.clear()
            try:
                self._deliver(batch)
            except Exception as exc:  # the watcher keeps running; never log file text
                code = exc.code if isinstance(exc, SddError) else type(exc).__name__
                log.error("batch of %d paths failed: %s", len(batch), code)


class _NativeHandler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher) -> None:
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in (
            "created",
            "modified",
            "deleted",
            "moved",
        ):
            return
        gone = event.event_type in ("deleted", "moved")
        touched = {(os.fsdecode(event.src_path), gone)}
        if event.event_type == "moved" and event.dest_path:
            touched.add((os.fsdecode(event.dest_path), False))
        for raw, removed in touched:
            self._watcher._native_event(raw, removed=removed)


class Watcher:
    """Watch the project root and deliver debounced :class:`Batch` objects to ``on_batch``."""

    def __init__(
        self,
        settings: Settings,
        on_batch: Callable[[Batch], None],
        *,
        debounce: float = 0.3,
        rules: files.IgnoreRules | None = None,
    ) -> None:
        self.settings = settings
        self.mode = settings.watch
        if self.mode == "auto":
            self.mode = "poll" if settings.in_container else "native"
        self._on_batch = on_batch
        self._root = settings.project_root
        self._classifier = indexer.Classifier(settings)
        self._rules = rules or files.IgnoreRules(self._root)
        self._bases = glob_bases(settings)
        self._lock = threading.Lock()  # guards _sdd and _snap
        self._sdd: dict[str, str] = {}
        self._snap: dict[str, _Stat] = {}
        self._debounce = _Debouncer(debounce, self._deliver)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._observer: Observer | None = None  # type: ignore[valid-type]

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Take the initial snapshot (no batch for it), then start the threads."""
        self._debounce.start()
        if self.mode == "native":
            self._sdd = indexer.discover(self.settings, rules=self._rules)
            observer = Observer()
            observer.schedule(_NativeHandler(self), str(self._root), recursive=True)
            observer.start()
            self._observer = observer
            return
        self._rescan_all()
        for code, name in ((False, "sdd-poll"), (True, "sdd-poll-code")):
            thread = threading.Thread(
                target=self._poll_loop, kwargs={"code": code}, name=name, daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Stop the threads and join them. Pending paths are dropped, not flushed."""
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
        for thread in self._threads:
            thread.join()
        self._threads = []
        self._debounce.stop()

    def sdd_files(self) -> dict[str, str]:
        """The current ``{path: kind}`` of SDD documents."""
        with self._lock:
            return dict(sorted(self._sdd.items()))

    # ------------------------------------------------------------ poll mode

    def poll_once(self, *, code: bool) -> set[str]:
        """One poll; returns the changed paths (also what the poll thread feeds the debouncer).

        ``code=True`` walks the whole tree; ``code=False`` polls only the SDD documents.
        """
        return self._poll_code() if code else self._poll_sdd()

    def _rescan_all(self) -> None:
        self._poll_code()

    def _stat(self, rel: str) -> _Stat | None:
        try:
            st = os.stat(self._root / rel)
        except OSError:
            return None  # vanished mid-poll counts as deleted
        return (st.st_mtime_ns, st.st_size)

    def _poll_sdd(self) -> set[str]:
        changed: set[str] = set()
        with self._lock:
            for rel in list(self._sdd):
                stat = self._stat(rel)
                if stat is None:
                    del self._sdd[rel]
                    self._snap.pop(rel, None)
                    changed.add(rel)
                elif self._snap.get(rel) != stat:
                    self._snap[rel] = stat
                    changed.add(rel)
            for rel in self._scan_bases():
                if rel in self._sdd:
                    continue
                kind = self._classifier.classify(rel)
                stat = self._stat(rel) if kind else None
                if kind and stat is not None:
                    self._sdd[rel] = kind
                    self._snap[rel] = stat
                    changed.add(rel)
        return changed

    def _scan_bases(self) -> list[str]:
        """``.md`` files under the glob base folders (recursive only where the glob says so)."""
        found: list[str] = []
        for base, recursive in self._bases.items():
            top = self._root / base if base else self._root
            if recursive:
                for folder, dirs, names in os.walk(top):
                    rel_dir = self._rel(folder)
                    dirs[:] = [
                        d for d in dirs if not self._rules.ignored(_join(rel_dir, d), is_dir=True)
                    ]
                    found += self._rel_md(folder, names)
            else:
                try:
                    names = [e.name for e in os.scandir(top) if e.is_file()]
                except OSError:
                    continue
                found += self._rel_md(str(top), names)
        return found

    def _rel(self, folder: str) -> str:
        rel = Path(folder).relative_to(self._root).as_posix()
        return "" if rel == "." else rel

    def _rel_md(self, folder: str, names: list[str]) -> list[str]:
        rel_dir = self._rel(folder)
        rels = (_join(rel_dir, n) for n in names if n.endswith(".md"))
        return [rel for rel in rels if not self._rules.ignored(rel)]

    def _poll_code(self) -> set[str]:
        self._rules.invalidate()  # a .gitignore edit is picked up by the next code poll
        new = files.walk(self._root, self._rules, self._stop)
        if self._stop.is_set():
            return set()  # shutting down: a long walk must not hold the daemon up
        with self._lock:
            old = self._snap
            changed = {p for p, s in new.items() if old.get(p) != s} | (old.keys() - new.keys())
            self._snap = new
            for rel in old.keys() - new.keys():
                self._sdd.pop(rel, None)
            for rel in new.keys() - old.keys():
                kind = self._classifier.classify(rel)
                if kind:
                    self._sdd[rel] = kind
        return changed

    def _poll_loop(self, *, code: bool) -> None:
        """One schedule per thread, so a slow code poll (30 s for 20 000 files through a Windows
        bind mount, M02.8) never delays the SDD poll. The code poll backs off: it waits at least
        ``CODE_BACKOFF`` times its last duration, so a big tree costs at most ~10% of a core."""
        interval = self.settings.poll_code_interval if code else self.settings.poll_interval
        wait = interval
        while not self._stop.wait(wait):
            started = time.monotonic()
            try:
                self._debounce.add(self.poll_once(code=code))
            except Exception as exc:
                log.error("poll failed: %s", type(exc).__name__)
            if code:
                wait = max(interval, CODE_BACKOFF * (time.monotonic() - started))

    # ------------------------------------------------------------ native mode

    def _native_event(self, raw: str, *, removed: bool) -> None:
        try:
            rel = Path(raw).relative_to(self._root).as_posix()
        except ValueError:
            return
        if not rel or rel == "." or self._rules.ignored(rel):
            return
        with self._lock:
            if removed:
                self._sdd.pop(rel, None)
            else:
                kind = self._classifier.classify(rel)
                if kind:
                    self._sdd[rel] = kind
        self._debounce.add({rel})

    # ------------------------------------------------------------ delivery

    def _deliver(self, paths: frozenset[str]) -> None:
        self._on_batch(Batch(paths, self.sdd_files()))
