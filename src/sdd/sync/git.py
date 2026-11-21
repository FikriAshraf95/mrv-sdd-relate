"""Git sync: the reader, the incremental sync and the HEAD poller (SPEC-04 §6; plan M04a §5).

The reader shells out to the ``git`` CLI (no new dependency) and never writes to the repository:
every call is ``git -c core.quotepath=off --no-optional-locks -C <root> …`` with a 30 s timeout
and no terminal prompt. No git binary, not a repository, no commits yet, or a project that is a
sub-folder of a larger repository: git sync is skipped (``None``), never an error.

``sync_git`` links commits to the graph: a Commit node, ``PARENT``, ``CHANGED``, ``COMPLETES``,
``PART_OF`` and ``TOUCHES``, all with ``src = 'git:<sha>'``. A commit never changes a task's
status and creates no Events. ``Meta.last_git_sha`` follows the last job.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sdd import ids
from sdd.config import Settings, iso_utc
from sdd.graph import code as graph_code
from sdd.graph.store import Store, Tx

__all__ = [
    "CommitIn",
    "GitReport",
    "HeadPoller",
    "head",
    "is_ancestor",
    "log_commits",
    "sync_git",
    "task_ids",
]

log = logging.getLogger("sdd.git")

TIMEOUT = 30.0
JOB_SIZE = 200  # commits per write job
_FORMAT = "%x1e%H%x1f%P%x1f%an%x1f%aI%x1f%s"
_TASK = re.compile(r"\[(M\d+[a-z]?\.\d+)\]")
_PAREN_MILESTONE = re.compile(r"\((M\d+[a-z]?)\)")
_BARE_MILESTONE = re.compile(r"\bM\d+[a-z]?\b")
_logged_skip = False


@dataclass(frozen=True, slots=True)
class CommitIn:
    sha: str
    parents: list[str]
    author: str  # the name only: the graph can be public (M06b), so no email
    at: str  # UTC, ``...Z``
    message: str  # the subject line
    changes: list[tuple[str, str]]  # (A | M | D | R, path); a rename is the new path
    paths: list[str]  # every path in the diff, deleted ones and rename sources included


@dataclass(slots=True)
class GitReport:
    added: int = 0
    removed: int = 0
    head: str | None = None
    changed_ids: list[str] = field(default_factory=list)  # commit:<sha> added or removed

    @property
    def wrote(self) -> bool:
        return bool(self.added or self.removed)

    def as_dict(self) -> dict[str, object]:
        return {"added": self.added, "removed": self.removed, "head": self.head}


# ---------------------------------------------------------------- the reader


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True,
        check=check,
        timeout=TIMEOUT,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _text(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stdout.decode("utf-8", errors="replace")


def head(root: Path) -> str | None:
    """``git rev-parse HEAD``; ``None`` without git, a repository or a first commit."""
    try:
        return _text(_git(root, "rev-parse", "HEAD")).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    """``git merge-base --is-ancestor``; an unknown commit (collected after a rewrite) is False."""
    try:
        return (
            _git(root, "merge-base", "--is-ancestor", ancestor, descendant, check=False).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _at_repo_root(root: Path) -> bool:
    """The project is the repository's top level (commit paths are relative to it)."""
    try:
        return _text(_git(root, "rev-parse", "--show-prefix")).strip() == ""
    except (OSError, subprocess.SubprocessError):
        return False


def reachable(root: Path, rev: str, max_count: int) -> list[str]:
    """``git rev-list -n <max> <rev>``."""
    return _text(_git(root, "rev-list", "-n", str(max_count), rev)).split()


def log_commits(root: Path, rev: str, max_count: int) -> list[CommitIn]:
    """Commits of ``rev``, oldest first, at most the newest ``max_count``, with name-status."""
    out = _text(
        _git(
            root,
            "log",
            "--reverse",
            "-n",
            str(max_count),
            "--name-status",
            f"--format={_FORMAT}",
            rev,
        )
    )
    commits: list[CommitIn] = []
    for record in out.split("\x1e"):
        if not record.strip():
            continue
        header, _, body = record.partition("\n")
        sha, parents, author, stamp, subject = header.split("\x1f", 4)
        changes: list[tuple[str, str]] = []
        paths: list[str] = []
        for line in body.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            letter, names = fields[0][:1], fields[1:]
            if letter == "R" and len(names) == 2:
                changes.append(("R", names[1]))
                paths += names
            elif letter == "C" and len(names) == 2:
                changes.append(("A", names[1]))
                paths.append(names[1])
            elif letter in "AMDT" and names:
                changes.append(("M" if letter == "T" else letter, names[0]))
                paths.append(names[0])
        commits.append(
            CommitIn(
                sha=sha,
                parents=parents.split(),
                author=author,
                at=iso_utc(datetime.fromisoformat(stamp)),
                message=subject,
                changes=changes,
                paths=list(dict.fromkeys(paths)),
            )
        )
    return commits


def task_ids(message: str) -> tuple[list[str], list[str]]:
    """``(task IDs, milestone IDs)`` named by a commit subject.

    Every ``[M02.3]`` is a task. Only when there is none, ``(M20f)`` (or a bare ``M20f``) names a
    milestone the commit is part of.
    """
    tasks = list(dict.fromkeys(ids.normalise(t) for t in _TASK.findall(message)))
    if tasks:
        return tasks, []
    found = _PAREN_MILESTONE.findall(message) or _BARE_MILESTONE.findall(message)
    return [], list(dict.fromkeys(ids.normalise(m) for m in found))


# ---------------------------------------------------------------- the sync


def sync_git(
    store: Store,
    settings: Settings,
    *,
    code_step: Callable[[Sequence[str]], None],
) -> GitReport | None:
    """Bring the Commit layer up to HEAD. ``None`` if the project has no usable git history.

    ``code_step`` is given the new commits' paths first, so that ``CHANGED`` and ``TOUCHES`` find
    the File nodes of files created in the same commit (the code poll alone would wait).
    """
    global _logged_skip  # noqa: PLW0603
    root = settings.project_root
    sha = head(root)
    if sha is None or not _at_repo_root(root):
        if not _logged_skip:
            _logged_skip = True
            log.info("git sync skipped: no repository with a commit at the project root")
        return None
    state = graph_code.read_git_state(store)
    report = GitReport(head=sha)
    if sha == state.last_git_sha:
        return report

    limit = settings.git_max_commits
    known = set(state.shas)
    if state.last_git_sha is None:
        commits = log_commits(root, "HEAD", limit)
    elif is_ancestor(root, state.last_git_sha, sha):
        commits = log_commits(root, f"{state.last_git_sha}..HEAD", limit)
    else:  # history rewritten: rebase, reset, branch switch
        stale = sorted(known - set(reachable(root, sha, limit)))
        if stale:  # its own job: a transaction must not delete what it created
            store.write(lambda tx: graph_code.delete_commits(tx, stale))
            known -= set(stale)
            report.removed = len(stale)
            report.changed_ids += [f"commit:{s}" for s in stale]
        commits = log_commits(root, "HEAD", limit)
    commits = [c for c in commits if c.sha not in known]

    if commits:
        code_step(sorted({p for c in commits for p in c.paths}))
    now = settings.now_iso()
    for start in range(0, len(commits), JOB_SIZE):
        chunk = commits[start : start + JOB_SIZE]
        last_chunk = start + JOB_SIZE >= len(commits)
        rows = [_row(c) for c in chunk]

        def job(tx: Tx, rows: list[graph_code.CommitRow] = rows, last: bool = last_chunk) -> None:
            graph_code.add_commits(tx, rows, now)
            graph_code.add_git_rels(tx, rows)
            if last:
                graph_code.set_last_git_sha(tx, sha)

        store.write(job)
    if not commits:
        store.write(lambda tx: graph_code.set_last_git_sha(tx, sha))
    report.added = len(commits)
    report.changed_ids += [f"commit:{c.sha}" for c in commits]
    return report


def _row(c: CommitIn) -> graph_code.CommitRow:
    tasks, milestones = task_ids(c.message)
    return graph_code.CommitRow(
        sha=c.sha,
        message=c.message,
        author=c.author,
        at=c.at,
        paths=c.paths,
        parents=c.parents,
        changes=c.changes,
        tasks=tasks,
        milestones=milestones,
    )


# ---------------------------------------------------------------- HEAD polling


class HeadPoller:
    """Poll ``git rev-parse HEAD`` and call ``on_change(sha)`` when it moves (SPEC-04 §6: 3 s).

    A daemon thread, like the watcher's. Polling works through bind mounts where file events do
    not. An error is logged by type and the loop keeps running.
    """

    def __init__(self, root: Path, on_change: Callable[[str], None], interval: float = 3.0) -> None:
        self._root = root
        self._on_change = on_change
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sdd-head", daemon=True)
        self._last: str | None = None

    def start(self) -> None:
        """Remember the current HEAD (the startup sync covered it), then poll."""
        self._last = head(self._root)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                sha = head(self._root)
                if sha is not None and sha != self._last:
                    self._last = sha
                    self._on_change(sha)
            except Exception as exc:  # keep polling; never log repository text
                log.error("head poll failed: %s", type(exc).__name__)
