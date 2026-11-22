"""Code-layer Cypher: Folder and File nodes, ``CONTAINS``, ``TESTS`` and the git layer
(SPEC-02 §3–4; SPEC-04 §4, §6; plan M04a §2, §5).

Plain data in, Cypher out, like :mod:`sdd.graph.upsert`: this module never imports ``parse/`` or
``sync/``. ``sync/files.py`` and ``sync/git.py`` do the filesystem and subprocess work and call
these functions inside ``store.write(job)``. Rows go through ``UNWIND`` in chunks, and labels and
relationship types are formatted into statements only after a whitelist check.

Ownership (SPEC-02 §4): relationships written here carry ``src = 'walker'`` (``CONTAINS``,
``TESTS``) or ``src = 'git:<sha>'``; nothing here touches ``tool`` or file-path owned ones.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from sdd.graph import schema
from sdd.graph.store import Store, Tx
from sdd.ids import label_of

__all__ = [
    "CHUNK",
    "FILE_PROPS",
    "CodeState",
    "CommitRow",
    "FileRow",
    "GitState",
    "add_commits",
    "add_contains",
    "add_git_rels",
    "delete_commits",
    "delete_files",
    "prune_empty_folders",
    "read_check_ids",
    "read_code_state",
    "read_features",
    "read_git_state",
    "read_implemented",
    "read_tests",
    "replace_implemented",
    "replace_tests",
    "set_last_git_sha",
    "upsert_files",
    "upsert_folders",
]

CHUNK = 500  # rows per UNWIND statement
# The File properties the walker owns (``content_hash`` only for non-SDD paths; see SPEC-04 §4).
FILE_PROPS = ("name", "language", "size", "lines", "is_test", "content_hash")


def _label(label: str) -> str:
    if label not in schema.LABELS:
        raise ValueError(f"unknown label {label!r}")
    return label


def _rel_type(type_: str) -> str:
    if type_ not in schema.REL_TYPES:
        raise ValueError(f"unknown relationship type {type_!r}")
    return type_


def _chunks[T](rows: Sequence[T]) -> Iterator[Sequence[T]]:
    for start in range(0, len(rows), CHUNK):
        yield rows[start : start + CHUNK]


def _run(store: Store | Tx) -> Any:
    return store.run if isinstance(store, Tx) else store.read


# ---------------------------------------------------------------- folders and files


@dataclass(frozen=True, slots=True)
class FileRow:
    path: str
    props: dict[str, Any]  # name, language, size, lines, is_test[, content_hash]; ``None`` removes


@dataclass(frozen=True, slots=True)
class CodeState:
    """What the graph holds of the code layer: File props by path, Folder paths, CONTAINS pairs."""

    files: dict[str, dict[str, Any]]
    folders: set[str]
    contains: set[tuple[str, str]]  # (parent Folder id, child id)


def read_code_state(store: Store | Tx) -> CodeState:
    """Every File's walker properties, every Folder path and every ``CONTAINS`` pair."""
    run = _run(store)
    cols = ", ".join(f"f.{p} AS {p}" for p in FILE_PROPS)
    files = {
        row["path"]: {p: row[p] for p in FILE_PROPS}
        for row in run(f"MATCH (f:{_label('File')}) RETURN f.path AS path, {cols}")
    }
    folders = {row["path"] for row in run(f"MATCH (d:{_label('Folder')}) RETURN d.path AS path")}
    pairs = {
        (row["a"], row["b"])
        for row in run(
            f"MATCH (a:{_label('Folder')})-[:{_rel_type('CONTAINS')}]->(b) "
            "RETURN a.id AS a, b.id AS b"
        )
    }
    return CodeState(files, folders, pairs)


def upsert_folders(tx: Tx, paths: Iterable[str], now: str) -> None:
    rows = [
        {
            "id": f"dir:{p}",
            "props": {"path": p, "name": p.rsplit("/", 1)[-1], "last_synced": now},
        }
        for p in paths
    ]
    for chunk in _chunks(rows):
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{_label('Folder')} {{id: row.id}}) SET n += row.props",
            {"rows": list(chunk)},
        )


def upsert_files(tx: Tx, rows: Iterable[FileRow], now: str) -> None:
    """``SET f += props``: a ``None`` property is removed. Never sends ``content_hash`` for an SDD
    document (the caller leaves it out): the indexer's phase 2 owns that hash (SPEC-04 §4)."""
    data = [
        {"id": f"file:{r.path}", "props": {**r.props, "path": r.path, "last_synced": now}}
        for r in rows
    ]
    for chunk in _chunks(data):
        tx.run(
            f"UNWIND $rows AS row MERGE (f:{_label('File')} {{id: row.id}}) SET f += row.props",
            {"rows": list(chunk)},
        )


def delete_files(tx: Tx, paths: Iterable[str]) -> None:
    ids = [f"file:{p}" for p in paths]
    for chunk in _chunks(ids):
        tx.run(
            f"MATCH (f:{_label('File')}) WHERE f.id IN $ids DETACH DELETE f", {"ids": list(chunk)}
        )


def add_contains(tx: Tx, pairs: Iterable[tuple[str, str]]) -> None:
    """``CONTAINS {src: 'walker'}`` from a parent Folder to a child Folder or File."""
    by_child: dict[str, list[dict[str, str]]] = defaultdict(list)
    for parent, child in pairs:
        by_child[label_of(child)].append({"p": parent, "c": child})
    for child_label, rows in by_child.items():
        for chunk in _chunks(rows):
            tx.run(
                f"UNWIND $rows AS row MATCH (a:{_label('Folder')} {{id: row.p}}) "
                f"MATCH (b:{_label(child_label)} {{id: row.c}}) "
                f"CREATE (a)-[:{_rel_type('CONTAINS')} {{src: 'walker'}}]->(b)",
                {"rows": list(chunk)},
            )


def prune_empty_folders(tx: Tx) -> list[str]:
    """Delete Folders with no children, repeatedly up the tree; returns the removed paths."""
    removed: list[str] = []
    while True:
        rows = tx.run(
            f"MATCH (d:{_label('Folder')}) WHERE NOT (d)-[:{_rel_type('CONTAINS')}]->() "
            "RETURN d.path AS path"
        )
        if not rows:
            return removed
        paths = [r["path"] for r in rows]
        for chunk in _chunks(paths):
            tx.run(
                f"MATCH (d:{_label('Folder')}) WHERE d.path IN $paths DETACH DELETE d",
                {"paths": list(chunk)},
            )
        removed += paths


def replace_tests(tx: Tx, file_id: str, check_ids: Iterable[str]) -> None:
    """Replace a test file's ``TESTS {src: 'walker'}`` with links to ``check_ids``."""
    tx.run(
        f"MATCH (:{_label('File')} {{id: $id}})-[r:{_rel_type('TESTS')}]->() DELETE r",
        {"id": file_id},
    )
    ids = sorted(set(check_ids))
    if ids:
        tx.run(
            f"MATCH (f:{_label('File')} {{id: $id}}) UNWIND $ids AS cid "
            f"MATCH (c:{_label('AcceptanceCheck')} {{id: cid}}) "
            f"CREATE (f)-[:{_rel_type('TESTS')} {{src: 'walker'}}]->(c)",
            {"id": file_id, "ids": ids},
        )


def read_tests(store: Store | Tx) -> dict[str, set[str]]:
    """``{file id: {AcceptanceCheck id}}`` for every stored ``TESTS`` link."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in _run(store)(
        f"MATCH (f:{_label('File')})-[:{_rel_type('TESTS')}]->(c:{_label('AcceptanceCheck')}) "
        "RETURN f.id AS f, c.id AS c"
    ):
        out[row["f"]].add(row["c"])
    return out


def read_check_ids(store: Store | Tx) -> set[str]:
    """Every AcceptanceCheck ID."""
    rows = _run(store)(f"MATCH (c:{_label('AcceptanceCheck')}) RETURN c.id AS id")
    return {r["id"] for r in rows}


# ---------------------------------------------------------------- features


def read_features(store: Store | Tx) -> dict[str, list[str]]:
    """``{feature id: globs}`` for every Feature node."""
    rows = _run(store)(f"MATCH (f:{_label('Feature')}) RETURN f.id AS id, f.globs AS globs")
    return {r["id"]: list(r["globs"] or []) for r in rows}


def read_implemented(store: Store | Tx) -> dict[str, set[str]]:
    """``{feature id: {File id}}`` for every stored ``IMPLEMENTED_IN``."""
    out: dict[str, set[str]] = defaultdict(set)
    for row in _run(store)(
        f"MATCH (f:{_label('Feature')})-[:{_rel_type('IMPLEMENTED_IN')}]->(x:{_label('File')}) "
        "RETURN f.id AS f, x.id AS x"
    ):
        out[row["f"]].add(row["x"])
    return out


def replace_implemented(tx: Tx, feature_id: str, file_ids: Iterable[str]) -> None:
    """Replace a Feature's ``IMPLEMENTED_IN {src: 'walker'}`` with links to ``file_ids``."""
    tx.run(
        f"MATCH (:{_label('Feature')} {{id: $id}})-[r:{_rel_type('IMPLEMENTED_IN')}]->() DELETE r",
        {"id": feature_id},
    )
    ids = sorted(set(file_ids))
    for chunk in _chunks(ids):
        tx.run(
            f"MATCH (f:{_label('Feature')} {{id: $id}}) UNWIND $ids AS fid "
            f"MATCH (x:{_label('File')} {{id: fid}}) "
            f"CREATE (f)-[:{_rel_type('IMPLEMENTED_IN')} {{src: 'walker'}}]->(x)",
            {"id": feature_id, "ids": list(chunk)},
        )


# ---------------------------------------------------------------- git


@dataclass(frozen=True, slots=True)
class CommitRow:
    sha: str
    message: str
    author: str
    at: str
    paths: list[str]
    parents: list[str] = field(default_factory=list)
    changes: list[tuple[str, str]] = field(default_factory=list)  # (change letter, path)
    tasks: list[str] = field(default_factory=list)  # task IDs this commit completes
    milestones: list[str] = field(default_factory=list)  # PART_OF targets (no task ID given)


@dataclass(frozen=True, slots=True)
class GitState:
    last_git_sha: str | None
    shas: set[str]  # every Commit node's sha


def read_git_state(store: Store | Tx) -> GitState:
    run = _run(store)
    meta = run("MATCH (m:Meta {id: 'meta'}) RETURN m.last_git_sha AS sha")
    shas = {r["sha"] for r in run(f"MATCH (c:{_label('Commit')}) RETURN c.sha AS sha")}
    return GitState(meta[0]["sha"] if meta else None, shas)


def set_last_git_sha(tx: Tx, sha: str) -> None:
    tx.run("MERGE (m:Meta {id: 'meta'}) SET m.last_git_sha = $sha", {"sha": sha})


def delete_commits(tx: Tx, shas: Iterable[str]) -> None:
    """Delete Commit nodes and every relationship whose ``src`` is ``git:<sha>``.

    ``TOUCHES`` is Task to File, so detaching the Commit does not remove it. A separate job from
    the one that adds commits (the engine panics when one transaction deletes a relationship it
    created). ``src = 'tool'`` relationships are never touched.
    """
    sha_list = sorted(set(shas))
    for chunk in _chunks(sha_list):
        srcs = [f"git:{s}" for s in chunk]
        tx.run("MATCH ()-[r]->() WHERE r.src IN $srcs DELETE r", {"srcs": srcs})
        tx.run(
            f"MATCH (c:{_label('Commit')}) WHERE c.sha IN $shas DETACH DELETE c",
            {"shas": list(chunk)},
        )


def add_commits(tx: Tx, commits: Sequence[CommitRow], now: str) -> None:
    """Commit nodes only (relationships follow in :func:`add_git_rels`)."""
    rows = [
        {
            "id": f"commit:{c.sha}",
            "props": {
                "sha": c.sha,
                "short": c.sha[:7],
                "message": c.message,
                "author": c.author,
                "at": c.at,
                "paths": list(c.paths),
                "last_synced": now,
                "id": f"commit:{c.sha}",
            },
        }
        for c in commits
    ]
    for chunk in _chunks(rows):
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{_label('Commit')} {{id: row.id}}) SET n = row.props",
            {"rows": list(chunk)},
        )


def add_git_rels(tx: Tx, commits: Sequence[CommitRow]) -> None:
    """``PARENT``, ``CHANGED``, ``COMPLETES``, ``PART_OF`` and ``TOUCHES``, all ``src = git:<sha>``.

    Links are made only to parents, files, tasks and milestones that exist now; a missing target
    gets no link and no ``unresolved`` entry (SPEC-04 §6).
    """
    parent: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    completes: list[dict[str, Any]] = []
    part_of: list[dict[str, Any]] = []
    touches: list[dict[str, Any]] = []
    for c in commits:
        src = f"git:{c.sha}"
        cid = f"commit:{c.sha}"
        parent += [{"a": cid, "b": f"commit:{p}", "p": {"src": src}} for p in c.parents]
        changed += [
            {"a": cid, "b": f"file:{path}", "p": {"src": src, "change": letter}}
            for letter, path in c.changes
        ]
        completes += [{"a": cid, "b": t, "p": {"src": src}} for t in c.tasks]
        part_of += [{"a": cid, "b": m, "p": {"src": src}} for m in c.milestones]
        files = sorted({path for _, path in c.changes})
        touches += [
            {"a": t, "b": f"file:{path}", "p": {"src": src}} for t in c.tasks for path in files
        ]
    _create(tx, "PARENT", "Commit", "Commit", parent)
    _create(tx, "CHANGED", "Commit", "File", changed)
    _create(tx, "COMPLETES", "Commit", "Task", completes)
    _create(tx, "PART_OF", "Commit", "Milestone", part_of)
    _create(tx, "TOUCHES", "Task", "File", touches)


def _create(tx: Tx, type_: str, from_label: str, to_label: str, rows: list[dict[str, Any]]) -> None:
    for chunk in _chunks(rows):
        tx.run(
            f"UNWIND $rows AS row MATCH (a:{_label(from_label)} {{id: row.a}}) "
            f"MATCH (b:{_label(to_label)} {{id: row.b}}) "
            f"CREATE (a)-[r:{_rel_type(type_)}]->(b) SET r = row.p",
            {"rows": list(chunk)},
        )
