"""Full scan of the SDD Markdown and the two-phase sync into the graph (SPEC-04 §2–3; plan M01b §3).

``analyse`` is pure with respect to the store: it discovers, reads, hashes and parses every SDD
file, drops duplicate IDs, cross-checks the deviation index and resolves every link against one
catalog. ``sdd doctor`` runs only this. ``full_sync`` adds the store: it decides what changed,
runs phase 1 (nodes) and phase 2 (relationships), handles removals and writes Meta.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pathspec

from sdd.config import Settings
from sdd.graph import schema, upsert
from sdd.graph.store import Row, Store, Tx
from sdd.graph.upsert import FileIn, NodeChanges, NodeIn, RelIn
from sdd.parse import (
    Catalog,
    ParseResult,
    ParseWarning,
    cross_check_index,
    parse_deviation,
    parse_deviation_index,
    parse_doc,
    parse_milestone,
    parse_plan,
    parse_spec,
    resolve,
)
from sdd.parse.md import id_slug
from sdd.parse.model import warn

__all__ = [
    "Analysis",
    "Resolved",
    "SourceFile",
    "SyncReport",
    "analyse",
    "catalog_fingerprint",
    "discover",
    "file_hash",
    "full_sync",
    "reset",
]

# Phase 1 order (SPEC-04 §2 step 4).
KIND_ORDER = ("spec", "milestone", "plan", "deviation", "deviation_index", "doc")
_PRUNED_DIRS = frozenset({"node_modules", "__pycache__"})
_PLAN_NAME = re.compile(r"^M\d+[a-z]?-plan\.md$")
_MILESTONE_NAME = re.compile(r"^M\d+[a-z]?-.+\.md$")
_PRIMARY_LABELS = ("Spec", "Milestone", "Deviation", "Doc")
_PARSERS = {
    "spec": parse_spec,
    "milestone": parse_milestone,
    "plan": parse_plan,
    "deviation": parse_deviation,
    "deviation_index": parse_deviation_index,
    "doc": parse_doc,
}


def file_hash(data: bytes) -> str:
    """``File.content_hash``: sha256 hex of the raw bytes (write-back uses the same function)."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- discovery


def _spec(globs: Iterable[str]) -> pathspec.PathSpec[Any]:
    # gitignore patterns match a slash-less pattern at any depth; config globs are project-relative
    return pathspec.PathSpec.from_lines("gitignore", [g if "/" in g else f"/{g}" for g in globs])


def discover(settings: Settings) -> dict[str, str]:
    """``{project-relative POSIX path: kind}`` for every SDD Markdown file, sorted by path."""
    specs = {key: _spec(globs) for key, globs in settings.paths.items()}
    root = settings.project_root
    found: dict[str, str] = {}
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _PRUNED_DIRS)
        for name in names:
            if not name.endswith(".md"):
                continue
            rel = (Path(folder) / name).relative_to(root).as_posix()
            kind = _classify(rel, name, specs)
            if kind:
                found[rel] = kind
    return dict(sorted(found.items()))


def _classify(rel: str, name: str, specs: Mapping[str, pathspec.PathSpec[Any]]) -> str | None:
    def hit(key: str) -> bool:
        return specs[key].match_file(rel)

    if hit("specs"):
        return "spec"
    if hit("plans") and _PLAN_NAME.match(name):
        return "plan"
    if hit("milestones") and _MILESTONE_NAME.match(name) and not _PLAN_NAME.match(name):
        return "milestone"
    if hit("deviations"):
        return "deviation"
    if hit("deviation_index"):
        return "deviation_index"
    if hit("docs"):
        return "doc"
    return None


# ---------------------------------------------------------------- analysis


@dataclass(slots=True)
class SourceFile:
    path: str
    kind: str
    content_hash: str
    result: ParseResult


@dataclass(slots=True)
class Resolved:
    rels: list[RelIn] = field(default_factory=list)
    unresolved: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class Analysis:
    files: list[SourceFile]  # path order; duplicate IDs already dropped
    resolved: dict[str, Resolved]
    warnings: list[ParseWarning]
    keep_ids: set[str]
    catalog_rows: list[Row]

    @property
    def unresolved(self) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for res in self.resolved.values():
            for node_id, strings in res.unresolved.items():
                out.setdefault(node_id, set()).update(strings)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def by_kind(self) -> list[SourceFile]:
        return sorted(self.files, key=lambda f: (KIND_ORDER.index(f.kind), f.path))


def analyse(settings: Settings) -> Analysis:
    """Discover, read, parse and resolve every SDD file. Reads Markdown only; no store."""
    files: list[SourceFile] = []
    for path, kind in discover(settings).items():
        data = (settings.project_root / path).read_bytes()
        text = data.decode("utf-8", errors="replace")
        files.append(SourceFile(path, kind, file_hash(data), _PARSERS[kind](path, text)))

    warnings = [w for f in files for w in f.result.warnings]
    warnings += _drop_duplicates(files)
    warnings += _check_index(files)

    catalog = Catalog.from_results(f.result for f in files)
    tracked = {f.path for f in files}
    for path in sorted(tracked):
        catalog.ids.add(f"file:{path}")
        catalog.paths.setdefault(path, f"file:{path}")

    resolved: dict[str, Resolved] = {}
    for f in files:
        resolved[f.path], extra = _resolve_file(f, catalog, tracked)
        warnings += extra

    keep_ids = {n.id for f in files for n in f.result.nodes}
    warnings.sort(key=lambda w: (w.path, w.line, w.code))
    return Analysis(files, resolved, warnings, keep_ids, _catalog_rows(files))


def _drop_duplicates(files: list[SourceFile]) -> list[ParseWarning]:
    """First file by path keeps an ID; later producers lose the node and its outgoing rels."""
    seen: set[str] = set()
    warnings: list[ParseWarning] = []
    for f in files:
        dropped: set[str] = set()
        kept = []
        for node in f.result.nodes:
            if node.id in seen:
                dropped.add(node.id)
                line = int(node.props.get("source_line") or 1)
                warnings.append(
                    warn(f.path, line, "duplicate_id", f"{node.id} is already defined; skipped")
                )
            else:
                seen.add(node.id)
                kept.append(node)
        if dropped:
            f.result.nodes = kept
            f.result.rels = [r for r in f.result.rels if r.from_id not in dropped]
    return warnings


def _check_index(files: list[SourceFile]) -> list[ParseWarning]:
    index = next((f for f in files if f.kind == "deviation_index"), None)
    if index is None:
        return []
    paths = {n.id: f.path for f in files if f.kind == "deviation" for n in f.result.nodes}
    return cross_check_index(index.result.index_rows, paths, index.path)


def _resolve_file(
    f: SourceFile, catalog: Catalog, tracked: set[str]
) -> tuple[Resolved, list[ParseWarning]]:
    out = Resolved()
    warnings: list[ParseWarning] = []
    produced = {n.id for n in f.result.nodes}
    primary = next(
        (n.id for label in _PRIMARY_LABELS for n in f.result.nodes if n.label == label), None
    )
    seen: set[tuple[Any, ...]] = set()

    def record(owner: str | None, strings: list[str]) -> None:
        if owner is not None:
            out.unresolved.setdefault(owner, []).extend(strings)

    for rel in f.result.rels:
        targets: list[str] = []
        missing: list[str] = []
        if rel.to.kind == "mention":
            if rel.to.target in tracked:
                targets = [f"file:{rel.to.target}"]
            elif rel.props.get("strict"):
                missing = [rel.to.target]
            else:
                continue
        else:
            res = resolve(rel.to, catalog, path=f.path)
            targets, missing = res.targets, res.unresolved
            warnings += res.warnings
        source_known = rel.from_id in catalog.ids
        if not source_known:
            missing = [*missing, rel.from_id]
        if missing:
            owner = rel.from_id if rel.from_id in produced else None
            if owner is None:
                owner = next((t for t in targets if t in produced), primary)
            record(owner, missing)
        if not source_known:
            continue
        props = {k: v for k, v in rel.props.items() if k != "strict"}
        for target in targets:
            key = (rel.type, rel.from_id, target, props.get("note"), props.get("whole"))
            if key not in seen:
                seen.add(key)
                out.rels.append(RelIn(rel.type, rel.from_id, target, props))
    return out, warnings


# ---------------------------------------------------------------- re-link fingerprint (D003)


def _catalog_rows(files: list[SourceFile]) -> list[Row]:
    rows: list[Row] = []
    for f in files:
        for node in f.result.nodes:
            if node.label in upsert.CATALOG_LABELS:
                rows.append(
                    {
                        "label": node.label,
                        "id": node.id,
                        "source_path": node.props.get("source_path"),
                        "anchor": node.props.get("anchor"),
                        "title": node.props.get("title"),
                        "spec_id": node.props.get("spec_id"),
                        "path": node.props.get("path"),
                    }
                )
        rows.append(
            {
                "label": "File",
                "id": f"file:{f.path}",
                "source_path": None,
                "anchor": None,
                "title": None,
                "spec_id": None,
                "path": f.path,
            }
        )
    return rows


def catalog_fingerprint(rows: Iterable[Mapping[str, Any]]) -> frozenset[tuple[Any, ...]]:
    """Everything a link resolves against: IDs, paths, anchors, title slugs, doc stems (D003)."""
    out: set[tuple[Any, ...]] = set()
    for row in rows:
        label, node_id = row["label"], row["id"]
        out.add(("id", node_id))
        if label in _PRIMARY_LABELS:
            out.add(("path", row.get("source_path"), node_id))
        if label == "File":
            out.add(("file", row.get("path")))
        elif label == "Section":
            spec = row.get("spec_id")
            out.add(("anchor", spec, row.get("anchor"), node_id))
            out.add(("slug", spec, id_slug(str(row.get("title") or "")), node_id))
        elif label == "Doc":
            stem = posixpath.splitext(posixpath.basename(str(row.get("source_path"))))[0]
            out.add(("doc", stem, node_id))
    return frozenset(out)


# ---------------------------------------------------------------- sync


@dataclass(slots=True)
class SyncReport:
    initial: bool
    scanned: int
    changed: list[str]
    removed: list[str]
    relinked: int
    warnings: list[ParseWarning]
    unresolved: dict[str, list[str]]
    events: int
    created: int
    updated: int
    deleted: int


def reset(store: Store) -> None:
    """Empty the store in one job (D002: ``sdd sync --reset`` never deletes the directory)."""

    def job(tx: Tx) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

    store.write(job)


def full_sync(store: Store, settings: Settings) -> SyncReport:
    """One full scan: skip unchanged files, upsert changed ones, remove vanished ones."""
    analysis = analyse(settings)
    now = settings.now_iso()
    state = upsert.read_state(store)
    initial = state.last_full_sync is None

    by_path = {f.path: f for f in analysis.files}
    changed = [f for f in analysis.by_kind() if state.files.get(f.path) != f.content_hash]
    removed = sorted(p for p in state.files if p not in by_path)
    relink_all = initial or catalog_fingerprint(state.catalog_rows) != catalog_fingerprint(
        analysis.catalog_rows
    )

    totals = NodeChanges()

    def phase1(f: SourceFile) -> NodeChanges:
        nodes = [NodeIn(n.label, n.id, dict(n.props)) for n in f.result.nodes]

        def job(tx: Tx) -> NodeChanges:
            return upsert.upsert_file_nodes(
                tx,
                FileIn(f.path, f.content_hash),
                nodes,
                keep_ids=analysis.keep_ids,
                now=now,
                initial=initial,
                writeback=settings.writeback,
            )

        return store.write(job)

    def removal(path: str) -> NodeChanges:
        def job(tx: Tx) -> NodeChanges:
            return upsert.delete_file(
                tx, path, keep_ids=analysis.keep_ids, now=now, initial=initial
            )

        return store.write(job)

    def phase2_job(f: SourceFile) -> int:
        res = analysis.resolved[f.path]

        def job(tx: Tx) -> int:
            return upsert.replace_file_rels(
                tx, f.path, res.rels, res.unresolved, content_hash=f.content_hash
            )

        return store.write(job)

    for f in changed:
        totals.extend(phase1(f))
    for path in removed:
        totals.extend(removal(path))
    phase2 = analysis.by_kind() if relink_all else changed
    for f in phase2:
        phase2_job(f)

    def meta(tx: Tx) -> None:
        upsert.write_meta(
            tx,
            schema_version=schema.SCHEMA_VERSION,
            project_name=settings.project_root.name,
            last_full_sync=now,
        )

    store.write(meta)
    store.checkpoint()
    return SyncReport(
        initial=initial,
        scanned=len(analysis.files),
        changed=[f.path for f in changed],
        removed=removed,
        relinked=len(phase2),
        warnings=analysis.warnings,
        unresolved=analysis.unresolved,
        events=totals.events,
        created=len(totals.created),
        updated=len(totals.updated),
        deleted=len(totals.deleted),
    )
