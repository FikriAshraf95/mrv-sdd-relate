"""The code walker: ignore rules, folder and file nodes, TESTS (SPEC-04 §4; plan M04a §2, §4).

``IgnoreRules`` decides which paths exist for the graph: the built-in skips, the ``.gitignore``
of every folder (a deeper file cannot un-ignore what a shallower one ignored) and a root
``.sddignore``. ``walk`` lists the tree; ``read_info`` reads one file once (hash, line count,
language, ``is_test``). ``sync_code`` diffs the walk, or a watcher batch, against the in-memory
:data:`CodeCache` and writes only the differences through :mod:`sdd.graph.code`. File contents
are never stored. This module never imports ``indexer`` (the indexer imports it).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pathspec

from sdd.config import Settings
from sdd.graph import code as graph_code
from sdd.graph.store import Store, Tx

if TYPE_CHECKING:
    from sdd.sync.indexer import Classifier

__all__ = [
    "BUILTIN_SKIPS",
    "CodeCache",
    "CodeReport",
    "CodeResult",
    "FileInfo",
    "IgnoreRules",
    "builtin_ignored",
    "file_hash",
    "iter_files",
    "prune_folders",
    "read_info",
    "scan_tests",
    "sync_code",
    "walk",
]

log = logging.getLogger("sdd.files")

BUILTIN_SKIPS = frozenset(
    {
        ".git",
        ".sdd",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        "bin",
        "obj",
        ".next",
        "coverage",
        "target",
    }
)
TEXT_LIMIT = 2 * 1024 * 1024  # `lines` and TESTS scans only look at files below this size
_SNIFF = 8 * 1024
_SPEC_AC = re.compile(r"spec(\d+)_ac(\d+)", re.IGNORECASE)
_LANGUAGES = {
    "py": "python",
    "pyi": "python",
    "ts": "typescript",
    "tsx": "typescript",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "md": "markdown",
    "json": "json",
    "toml": "toml",
    "yaml": "yaml",
    "yml": "yaml",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "sh": "shell",
    "bash": "shell",
    "ps1": "powershell",
    "cs": "csharp",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "kt": "kotlin",
    "sql": "sql",
    "txt": "text",
}
_LANGUAGE_NAMES = {"Dockerfile": "dockerfile", "Makefile": "make"}
_Stat = tuple[int, int]  # (st_mtime_ns, st_size)


def file_hash(data: bytes) -> str:
    """``File.content_hash``: sha256 hex of the raw bytes (write-back uses the same function)."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- ignore rules


def builtin_ignored(rel: str) -> bool:
    """Whether any segment of a project-relative POSIX path is in :data:`BUILTIN_SKIPS`."""
    return any(part in BUILTIN_SKIPS for part in rel.split("/"))


class IgnoreRules:
    """``.gitignore`` per folder, ``.sddignore`` at the root and the built-in skips.

    Thread-safe (the watcher polls from its own thread while a sync runs). Spec files are read
    lazily and cached per folder until :meth:`invalidate`. Negation works within one file; a
    deeper file cannot un-ignore what a shallower file ignored (SPEC-04 §4).
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._lock = threading.Lock()
        self._specs: dict[str, pathspec.GitIgnoreSpec | None] = {}

    def invalidate(self) -> None:
        """Drop the cached specs; the next query re-reads the ignore files."""
        with self._lock:
            self._specs.clear()

    def ignored(self, rel: str, *, is_dir: bool = False) -> bool:
        """Whether ``rel`` (project-relative, POSIX) is ignored; ``is_dir`` for a folder."""
        if builtin_ignored(rel):
            return True
        parts = rel.split("/")
        with self._lock:
            for depth in range(len(parts)):
                spec = self._spec_for("/".join(parts[:depth]))
                if spec is None:
                    continue
                sub = "/".join(parts[depth:])
                if spec.match_file(sub + "/" if is_dir else sub):
                    return True
        return False

    def _spec_for(self, folder: str) -> pathspec.GitIgnoreSpec | None:
        # the caller holds the lock
        if folder in self._specs:
            return self._specs[folder]
        names = (".gitignore", ".sddignore") if folder == "" else (".gitignore",)
        lines: list[str] = []
        for name in names:
            try:
                text = (self._root / folder / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines += text.splitlines()
        spec = pathspec.GitIgnoreSpec.from_lines(lines) if lines else None
        self._specs[folder] = spec
        return spec


# ---------------------------------------------------------------- walking


def _join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def iter_files(
    root: Path, rules: IgnoreRules, stop: threading.Event | None = None
) -> Iterator[str]:
    """Project-relative POSIX paths of every non-ignored file, folders pruned as they are met.

    ``stop`` ends the walk early (the watcher's shutdown check). Symlinked folders are not followed.
    """
    base = str(root)
    for folder, dirs, names in os.walk(root, followlinks=False):
        if stop is not None and stop.is_set():
            return
        rel_dir = folder[len(base) :].strip("/\\").replace("\\", "/")
        dirs[:] = sorted(d for d in dirs if not rules.ignored(_join(rel_dir, d), is_dir=True))
        for name in sorted(names):
            rel = _join(rel_dir, name)
            if not rules.ignored(rel):
                yield rel


def walk(root: Path, rules: IgnoreRules, stop: threading.Event | None = None) -> dict[str, _Stat]:
    """``{rel: (mtime_ns, size)}`` for every non-ignored regular file."""
    out: dict[str, _Stat] = {}
    for rel in iter_files(root, rules, stop):
        try:
            st = os.stat(root / rel)
        except OSError:
            continue  # vanished mid-walk
        if stat.S_ISREG(st.st_mode):
            out[rel] = (st.st_mtime_ns, st.st_size)
    return out


# ---------------------------------------------------------------- reading one file


@dataclass(frozen=True, slots=True)
class FileInfo:
    path: str
    name: str
    language: str | None
    size: int
    lines: int | None
    content_hash: str
    is_test: bool


# path -> what the graph holds of it (the runtime keeps one; a full sync rebuilds it)
CodeCache = dict[str, FileInfo]


def _language(name: str) -> str | None:
    if name in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[name]
    _, dot, ext = name.rpartition(".")
    return _LANGUAGES.get(ext.lower()) if dot else None


def _count_lines(data: bytes) -> int | None:
    if len(data) >= TEXT_LIMIT or b"\x00" in data[:_SNIFF]:
        return None
    count = data.count(b"\n")
    return count + 1 if data and not data.endswith(b"\n") else count


def read_info(root: Path, rel: str, classifier: Classifier) -> FileInfo | None:
    """Read ``rel`` once; ``None`` if it vanished or is not a readable file."""
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return None
    name = rel.rsplit("/", 1)[-1]
    return FileInfo(
        path=rel,
        name=name,
        language=_language(name),
        size=len(data),
        lines=_count_lines(data),
        content_hash=file_hash(data),
        is_test=classifier.is_test(rel),
    )


def _props(info: FileInfo, sdd: bool) -> dict[str, Any]:
    """The File properties the walker writes; ``None`` means "absent". No hash on SDD documents."""
    props: dict[str, Any] = {
        "name": info.name,
        "language": info.language,
        "size": info.size,
        "lines": info.lines,
        "is_test": info.is_test,
    }
    if not sdd:
        props["content_hash"] = info.content_hash
    return props


def _same(want: dict[str, Any], have: dict[str, Any]) -> bool:
    # a SDD document's stored content_hash is the indexer's: it is not in ``want``, so not compared
    return all(have.get(k) == v for k, v in want.items())


def _dirs(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def _parent_id(path: str) -> str | None:
    head, sep, _ = path.rpartition("/")
    return f"dir:{head}" if sep else None  # top-level entries have no parent (no root Folder)


# ---------------------------------------------------------------- the code step


@dataclass(slots=True)
class CodeReport:
    added: int = 0
    updated: int = 0
    removed: int = 0
    folders: int = 0  # Folder nodes created or pruned
    tests_links: int = 0  # TESTS relationships written by the TESTS scan
    capped: int = 0  # files left out by the soft cap


@dataclass(slots=True)
class CodeResult:
    report: CodeReport = field(default_factory=CodeReport)
    written: set[str] = field(default_factory=set)  # paths added or updated
    removed: set[str] = field(default_factory=set)
    changed_ids: set[str] = field(default_factory=set)

    @property
    def wrote(self) -> bool:
        return bool(self.written or self.removed or self.report.folders)

    def merge(self, other: CodeResult) -> None:
        """Fold a second code step (the git step's) into this one."""
        self.written |= other.written
        self.removed |= other.removed
        self.changed_ids |= other.changed_ids
        for name in ("added", "updated", "removed", "folders", "capped"):
            setattr(self.report, name, getattr(self.report, name) + getattr(other.report, name))


def sync_code(
    store: Store,
    settings: Settings,
    *,
    cache: CodeCache,
    rules: IgnoreRules,
    classifier: Classifier,
    full: bool,
    paths: Iterable[str] = (),
) -> CodeResult:
    """Phase 1 of the code layer: File and Folder nodes for what changed (SPEC-04 §2 step 4).

    A full sync walks everything and diffs it against the stored code layer; a batch re-reads only
    ``paths`` and diffs them against ``cache``. Unchanged files are not written. SDD documents get
    File nodes too, but never a walker ``content_hash`` (the indexer owns it); only non-SDD File
    nodes are deleted here. The cache is replaced only after the writes succeed.
    """
    if full:
        return _sync_full(store, settings, cache, rules, classifier)
    return _sync_batch(store, settings, cache, rules, classifier, paths=paths)


def _sdd(classifier: Classifier, rel: str) -> bool:
    return classifier.classify(rel) is not None


def _sync_full(
    store: Store, settings: Settings, cache: CodeCache, rules: IgnoreRules, classifier: Classifier
) -> CodeResult:
    root = settings.project_root
    paths = sorted(walk(root, rules))
    result = CodeResult()
    if len(paths) > settings.max_files:
        result.report.capped = len(paths) - settings.max_files
        log.warning(
            "%d files found; keeping the first %d by path (SDD_MAX_FILES)",
            len(paths),
            settings.max_files,
        )
        paths = paths[: settings.max_files]
    infos: dict[str, FileInfo] = {}
    for rel in paths:
        info = read_info(root, rel, classifier)
        if info is not None:
            infos[rel] = info

    stored = graph_code.read_code_state(store)
    sdd = {rel: _sdd(classifier, rel) for rel in {*infos, *stored.files}}
    upserts: list[FileInfo] = []
    for rel, info in infos.items():
        have = stored.files.get(rel)
        if have is None:
            result.report.added += 1
        elif _same(_props(info, sdd[rel]), have):
            continue
        else:
            result.report.updated += 1
        upserts.append(info)
    removes = sorted(p for p in stored.files if p not in infos and not sdd[p])

    folders = {d for rel in infos for d in _dirs(rel)}
    new_folders = sorted(folders - stored.folders, key=lambda p: (p.count("/"), p))
    wanted = [(parent, f"dir:{d}") for d in sorted(folders) if (parent := _parent_id(d))]
    wanted += [(parent, f"file:{rel}") for rel in infos if (parent := _parent_id(rel))]
    pairs = [pair for pair in wanted if pair not in stored.contains]

    _write(
        store,
        settings,
        removes=removes,
        upserts=upserts,
        sdd=sdd,
        new_folders=new_folders,
        pairs=pairs,
    )
    cache.clear()
    cache.update(infos)
    result.written = {i.path for i in upserts}
    result.removed = set(removes)
    result.report.removed = len(removes)
    result.report.folders = len(new_folders)
    result.changed_ids = {f"file:{p}" for p in result.written | result.removed} | {
        f"dir:{d}" for d in new_folders
    }
    return result


def _sync_batch(
    store: Store,
    settings: Settings,
    cache: CodeCache,
    rules: IgnoreRules,
    classifier: Classifier,
    *,
    paths: Iterable[str],
) -> CodeResult:
    root = settings.project_root
    result = CodeResult()
    new_cache = dict(cache)
    infos: dict[str, FileInfo] = {}
    removes: list[str] = []
    sdd: dict[str, bool] = {}
    for rel in sorted(set(paths)):
        sdd[rel] = _sdd(classifier, rel)
        info = None
        if not rules.ignored(rel) and _is_regular(root / rel):
            info = read_info(root, rel, classifier)
        if info is not None:
            infos[rel] = info
            new_cache[rel] = info
        elif rel in new_cache:
            del new_cache[rel]
            if not sdd[rel]:
                removes.append(rel)

    if len(new_cache) > settings.max_files:  # the cap applies to the union (SPEC-04 §4)
        keep = set(sorted(new_cache)[: settings.max_files])
        evicted = sorted(set(new_cache) - keep)
        result.report.capped = len(evicted)
        log.warning(
            "more than %d files; the last %d by path are left out", settings.max_files, len(evicted)
        )
        for rel in evicted:
            del new_cache[rel]
            infos.pop(rel, None)
            sdd.setdefault(rel, _sdd(classifier, rel))
            if rel in cache and not sdd[rel] and rel not in removes:
                removes.append(rel)

    upserts: list[FileInfo] = []
    for rel, info in infos.items():
        old = cache.get(rel)
        if old is None:
            result.report.added += 1
        elif _props(old, sdd[rel]) == _props(info, sdd[rel]):
            continue
        else:
            result.report.updated += 1
        upserts.append(info)

    new_files = [i.path for i in upserts if i.path not in cache]
    known = {d for p in cache for d in _dirs(p)} if new_files else set()
    new_folders = sorted(
        {d for p in new_files for d in _dirs(p)} - known, key=lambda p: (p.count("/"), p)
    )
    pairs = [(parent, f"dir:{d}") for d in new_folders if (parent := _parent_id(d))]
    pairs += [(parent, f"file:{p}") for p in new_files if (parent := _parent_id(p))]

    _write(
        store,
        settings,
        removes=sorted(removes),
        upserts=upserts,
        sdd=sdd,
        new_folders=new_folders,
        pairs=pairs,
    )
    cache.clear()
    cache.update(new_cache)
    result.written = {i.path for i in upserts}
    result.removed = set(removes)
    result.report.removed = len(removes)
    result.report.folders = len(new_folders)
    result.changed_ids = {f"file:{p}" for p in result.written | result.removed} | {
        f"dir:{d}" for d in new_folders
    }
    return result


def _is_regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        return False


def _write(
    store: Store,
    settings: Settings,
    *,
    removes: list[str],
    upserts: list[FileInfo],
    sdd: dict[str, bool],
    new_folders: list[str],
    pairs: list[tuple[str, str]],
) -> None:
    """Deletes in one job, then the upserts and links in another (no delete after a create)."""
    now = settings.now_iso()
    if removes:
        store.write(lambda tx: graph_code.delete_files(tx, removes))
    if upserts or new_folders or pairs:
        rows = [graph_code.FileRow(i.path, _props(i, sdd[i.path])) for i in upserts]

        def job(tx: Tx) -> None:
            graph_code.upsert_folders(tx, new_folders, now)
            graph_code.upsert_files(tx, rows, now)
            graph_code.add_contains(tx, pairs)

        store.write(job)


def prune_folders(store: Store, result: CodeResult) -> None:
    """Delete Folders left with no children (after the indexer removed SDD documents too)."""
    pruned = store.write(graph_code.prune_empty_folders)
    result.report.folders += len(pruned)
    result.changed_ids.update(f"dir:{p}" for p in pruned)


# ---------------------------------------------------------------- TESTS


def scan_tests(
    store: Store,
    settings: Settings,
    cache: CodeCache,
    result: CodeResult,
    *,
    all_tests: bool,
) -> None:
    """Link test files to the AcceptanceChecks their names mention (SPEC-04 §4).

    Scans the test files written in this sync, or every test file when ``all_tests`` (a full sync,
    or a sync that created or deleted an AcceptanceCheck, so a check added later still gets its
    tests). ``spec(\\d+)_ac(\\d+)`` reads both numbers as integers; a link is made only to a check
    that exists. A file's ``TESTS`` are rewritten only when the wanted set differs from the stored.
    """
    candidates = [
        p
        for p, info in sorted(cache.items())
        if info.is_test and (all_tests or p in result.written) and info.size < TEXT_LIMIT
    ]
    if not candidates:
        return
    checks = graph_code.read_check_ids(store)
    stored = graph_code.read_tests(store)
    wanted: dict[str, set[str]] = {}
    for rel in candidates:
        try:
            text = (settings.project_root / rel).read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        ids = {
            f"SPEC-{int(a):02d}#ac{int(b)}"
            for a, b in _SPEC_AC.findall(text)
            if f"SPEC-{int(a):02d}#ac{int(b)}" in checks
        }
        wanted[f"file:{rel}"] = ids
    todo = {fid: ids for fid, ids in wanted.items() if stored.get(fid, set()) != ids}
    if not todo:
        return

    def job(tx: Tx) -> None:
        for fid, ids in todo.items():
            graph_code.replace_tests(tx, fid, ids)

    store.write(job)
    result.report.tests_links += sum(len(ids) for ids in todo.values())
    result.changed_ids.update(todo)
