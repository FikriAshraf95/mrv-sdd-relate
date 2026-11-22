"""Full scan of the SDD Markdown and the two-phase sync into the graph (SPEC-04 §2–3; plan M01b §3).

``analyse`` is pure with respect to the store: it discovers, reads, hashes and parses every SDD
file, drops duplicate IDs, cross-checks the deviation index and resolves every link against one
catalog. ``sdd doctor`` runs only this. ``sync`` adds the store: it decides what changed,
runs phase 1 (nodes) and phase 2 (relationships), handles removals and writes Meta.

M02 adds the parse cache (unchanged files are not re-parsed, SPEC-04 §2 step 3), the ignore and
classify helpers the watcher shares with ``discover``, and ``sync(full=False)`` for watcher
batches (plan M02 §2).
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

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
from sdd.sync.files import IgnoreRules, builtin_ignored, file_hash, globspec, iter_files

if TYPE_CHECKING:
    from sdd.sync.files import CodeReport
    from sdd.sync.git import GitReport

__all__ = [
    "Analysis",
    "Classifier",
    "ParseCache",
    "Resolved",
    "SourceFile",
    "SyncReport",
    "analyse",
    "catalog_fingerprint",
    "classify",
    "discover",
    "file_hash",
    "full_sync",
    "globspec",
    "mentions",
    "reset",
    "sync",
    "sync_tx",
]

# Phase 1 order (SPEC-04 §2 step 4).
KIND_ORDER = ("spec", "milestone", "plan", "deviation", "deviation_index", "doc")
# path -> (content hash, kind, pristine parse result); see analyse()
ParseCache = dict[str, tuple[str, str, ParseResult]]
_PLAN_NAME = re.compile(r"^M\d+[a-z]?-plan\.md$")
_MILESTONE_NAME = re.compile(r"^M\d+[a-z]?-.+\.md$")
_PRIMARY_LABELS = ("Spec", "Milestone", "Deviation", "Doc")
_SHARED_LABELS = ("Feature", "Domain")  # no source_path: merged across specs (plan M04b §2)
_PARSERS = {
    "spec": parse_spec,
    "milestone": parse_milestone,
    "plan": parse_plan,
    "deviation": parse_deviation,
    "deviation_index": parse_deviation_index,
    "doc": parse_doc,
}


# ---------------------------------------------------------------- discovery


class Classifier:
    """Classify project-relative paths against the SDD globs; the pathspecs are built once."""

    def __init__(self, settings: Settings) -> None:
        self._specs = {key: globspec(globs) for key, globs in settings.paths.items()}

    def classify(self, rel: str) -> str | None:
        """The SDD kind of ``rel`` (a ``.md`` file under no built-in skip), else ``None``.

        Only the built-in skips are checked here; ``.gitignore`` rules are applied by the walkers.
        """
        name = rel.rsplit("/", 1)[-1]
        if not name.endswith(".md") or builtin_ignored(rel):
            return None
        return _classify(rel, name, self._specs)

    def is_test(self, rel: str) -> bool:
        """Whether ``rel`` matches a ``tests`` glob (SPEC-03 §1)."""
        return self._specs["tests"].match_file(rel)

    def is_schema(self, rel: str) -> bool:
        """Whether ``rel`` matches a ``schema_specs`` glob (its table sections are parsed)."""
        return self._specs["schema_specs"].match_file(rel)


def classify(settings: Settings, rel: str) -> str | None:
    """One-off :meth:`Classifier.classify`; hold a ``Classifier`` when classifying many paths."""
    return Classifier(settings).classify(rel)


def discover(settings: Settings, *, rules: IgnoreRules | None = None) -> dict[str, str]:
    """``{project-relative POSIX path: kind}`` for every SDD Markdown file, sorted by path.

    Walks with the code walker's ignore rules (SPEC-04 §4), so an ignored Markdown file is not an
    SDD document.
    """
    classifier = Classifier(settings)
    root = settings.project_root
    found: dict[str, str] = {}
    for rel in iter_files(root, rules or IgnoreRules(root)):
        if rel.endswith(".md") and (kind := classifier.classify(rel)):
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
    shared: list[NodeIn] = field(default_factory=list)  # Feature and Domain nodes, merged

    @property
    def unresolved(self) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for res in self.resolved.values():
            for node_id, strings in res.unresolved.items():
                out.setdefault(node_id, set()).update(strings)
        return {k: sorted(v) for k, v in sorted(out.items())}

    def by_kind(self) -> list[SourceFile]:
        return sorted(self.files, key=lambda f: (KIND_ORDER.index(f.kind), f.path))


def analyse(
    settings: Settings,
    *,
    cache: ParseCache | None = None,
    files: Mapping[str, str] | None = None,
    file_exists: Callable[[str], bool] | None = None,
) -> Analysis:
    """Discover, read, parse and resolve every SDD file. Reads Markdown only; no store.

    ``file_exists`` says whether a backticked path names a file (the graph's File nodes, from
    ``sync``); without it the project folder decides, honouring the ignore rules (``sdd doctor``).

    ``files`` (``{path: kind}``, the watcher's SDD set) replaces discovery. With a ``cache``, a
    file whose hash and kind are unchanged is not re-parsed (SPEC-04 §2 step 3); resolution still
    runs over every file. Each analysis works on a copy of the cached result, because
    ``_drop_duplicates`` reassigns ``nodes`` and ``rels``.
    """
    found = discover(settings) if files is None else dict(sorted(files.items()))
    classifier = Classifier(settings)
    files_: list[SourceFile] = []
    for path, kind in found.items():
        try:
            data = (settings.project_root / path).read_bytes()
        except FileNotFoundError:
            continue  # vanished after the watcher's snapshot; the next batch reports it
        digest = file_hash(data)
        hit = cache.get(path) if cache is not None else None
        if hit is not None and hit[0] == digest and hit[1] == kind:
            pristine = hit[2]
        else:
            text = data.decode("utf-8", errors="replace")
            options = {"schema": True} if kind == "spec" and classifier.is_schema(path) else {}
            pristine = _PARSERS[kind](path, text, **options)
            if cache is not None:
                cache[path] = (digest, kind, pristine)
        result = replace(
            pristine,
            nodes=list(pristine.nodes),
            rels=list(pristine.rels),
            warnings=list(pristine.warnings),
        )
        files_.append(SourceFile(path, kind, digest, result))
    if cache is not None:
        for gone in set(cache) - {f.path for f in files_}:
            del cache[gone]
    return _analyse_files(files_, file_exists or _disk_exists(settings))


def _disk_exists(settings: Settings) -> Callable[[str], bool]:
    """``file_exists`` for an analysis without a store: a regular, non-ignored file on disk."""
    root = settings.project_root.resolve()
    rules = IgnoreRules(root)

    def exists(rel: str) -> bool:
        if not rel or rel.startswith("/") or ".." in rel.split("/") or "\\" in rel:
            return False
        try:
            return (root / rel).is_file() and not rules.ignored(rel)
        except (OSError, ValueError):
            return False

    return exists


def _take_shared(files: list[SourceFile]) -> list[NodeIn]:
    """Pull the Feature and Domain nodes out of every file and merge them by ID.

    The first file by path gives ``name`` and ``slug``; a Feature's ``globs`` are the sorted union
    over every declaration. Their relationships stay with the declaring file.
    """
    merged: dict[str, NodeIn] = {}
    for f in files:
        keep = []
        for node in f.result.nodes:
            if node.label not in _SHARED_LABELS:
                keep.append(node)
                continue
            old = merged.get(node.id)
            if old is None:
                merged[node.id] = NodeIn(node.label, node.id, dict(node.props))
            elif "globs" in node.props:
                globs = sorted({*old.props.get("globs", []), *node.props["globs"]})
                merged[node.id] = NodeIn(old.label, old.id, {**old.props, "globs": globs})
        f.result.nodes = keep
    for shared in merged.values():
        if "globs" in shared.props:
            shared.props["globs"] = sorted(set(shared.props["globs"]))
    return sorted(merged.values(), key=lambda n: n.id)


def _analyse_files(files: list[SourceFile], file_exists: Callable[[str], bool]) -> Analysis:
    shared = _take_shared(files)

    warnings = [w for f in files for w in f.result.warnings]
    warnings += _drop_duplicates(files)
    warnings += _check_index(files)

    catalog = Catalog.from_results(f.result for f in files)
    catalog.ids.update(n.id for n in shared)
    tracked = {f.path for f in files}
    for path in sorted(tracked):
        catalog.ids.add(f"file:{path}")
        catalog.paths.setdefault(path, f"file:{path}")

    resolved: dict[str, Resolved] = {}
    for f in files:
        resolved[f.path], extra = _resolve_file(f, catalog, tracked, file_exists)
        warnings += extra

    keep_ids = {n.id for f in files for n in f.result.nodes}
    warnings.sort(key=lambda w: (w.path, w.line, w.code))
    return Analysis(files, resolved, warnings, keep_ids, _catalog_rows(files), shared)


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
    f: SourceFile, catalog: Catalog, tracked: set[str], file_exists: Callable[[str], bool]
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
            targets = _mention_targets(rel.to.target, catalog, tracked, file_exists)
            if not targets:
                if not rel.props.get("strict"):
                    continue
                missing = [rel.to.target]
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


def _mentions(result: ParseResult) -> set[str]:
    return {r.to.target for r in result.rels if r.to.kind == "mention"}


def mentions(cache: ParseCache) -> dict[str, set[str]]:
    """``{mentioned identifier: {SDD paths}}`` over the cached parse results."""
    out: dict[str, set[str]] = {}
    for path, (_, _, result) in cache.items():
        for ident in _mentions(result):
            out.setdefault(ident, set()).add(path)
    return out


def _mention_targets(
    ident: str, catalog: Catalog, tracked: set[str], file_exists: Callable[[str], bool]
) -> list[str]:
    """What a backticked identifier names: a Table, an existing file, or both (plan M04b §3)."""
    out = []
    if f"table:{ident}" in catalog.ids:
        out.append(f"table:{ident}")
    if ident in tracked or file_exists(ident):
        out.append(f"file:{ident}")
    return out


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
    changed_ids: list[str] = field(default_factory=list)  # node IDs and file:<path> that changed
    indexed: bool = True  # False for a batch that touched no SDD document (the pipeline's shell)
    code: CodeReport | None = None  # M04a: the code walker's part of this sync
    git: GitReport | None = None  # M04a: the git part, ``None`` when skipped

    @classmethod
    def empty(cls) -> SyncReport:
        """A report for a sync that did not run the indexer."""
        return cls(False, 0, [], [], 0, [], {}, 0, 0, 0, 0, indexed=False)


def reset(store: Store) -> None:
    """Empty the store in one job (D002: ``sdd sync --reset`` never deletes the directory)."""

    def job(tx: Tx) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

    store.write(job)


def sync(
    store: Store,
    settings: Settings,
    *,
    full: bool = True,
    files: Mapping[str, str] | None = None,
    cache: ParseCache | None = None,
    code_touched: frozenset[str] = frozenset(),
) -> SyncReport:
    """Skip unchanged files, upsert changed ones, remove vanished ones.

    ``full`` marks a startup or requested scan: it writes ``Meta.last_full_sync`` and checkpoints.
    A watcher batch passes ``full=False`` and its SDD file set; it checkpoints only when it wrote
    something. ``cache`` lets unchanged files skip parsing. ``code_touched`` are the code paths
    this sync added or removed: a document that mentions one gets its relationships rebuilt even
    if its text is unchanged (SPEC-04 §4, Mentions). The caller serializes calls.
    """
    known = upsert.read_file_paths(store)
    analysis = analyse(settings, cache=cache, files=files, file_exists=known.__contains__)
    state = _scope(upsert.read_state(store), Classifier(settings))
    report = _apply(store.write, state, analysis, settings, full=full, code_touched=code_touched)
    if full or report.changed or report.removed or report.relinked:
        store.checkpoint()  # no flush for a no-op watcher batch
    return report


def sync_tx(tx: Tx, settings: Settings, *, cache: ParseCache | None = None) -> SyncReport:
    """The same sync of every SDD file, inside the caller's write job (one transaction).

    Write-back calls this after writing Markdown (SPEC-04 §5.2, §5.4): the files it wrote, and
    any other edit not synced yet, are re-parsed and stored with their new hashes before the job
    commits, so the watcher finds nothing to do. A move is a removal plus an addition here. No
    checkpoint (the store flushes after the next batch) and ``Meta.last_full_sync`` is unchanged.
    """
    analysis = analyse(settings, cache=cache, file_exists=upsert.read_file_paths(tx).__contains__)

    def run_here(job: Callable[[Tx], Any]) -> Any:
        return job(tx)

    return _apply(
        run_here,
        _scope(upsert.read_state(tx), Classifier(settings)),
        analysis,
        settings,
        full=False,
    )


def _scope(state: upsert.GraphState, classifier: Classifier) -> upsert.GraphState:
    """Keep only what the Markdown sync owns: SDD documents (M04a.6).

    The code walker also gives every other file a hashed File node, so ``read_state`` returns
    those too. Without this the full sync would delete them as "removed", and the catalog
    fingerprint would differ on every sync. The File catalog rows are those of the SDD documents
    that carry a hash (fully synced), which is what the fingerprint was before the walker.
    """
    files = {p: h for p, h in state.files.items() if classifier.classify(p) is not None}
    rows = [r for r in state.catalog_rows if r["label"] != "File" or r["path"] in files]
    return replace(state, files=files, catalog_rows=rows)


def _apply(
    run_job: Callable[[Callable[[Tx], Any]], Any],
    state: upsert.GraphState,
    analysis: Analysis,
    settings: Settings,
    *,
    full: bool,
    code_touched: frozenset[str] = frozenset(),
) -> SyncReport:
    """Phase 1, removals, phase 2 and Meta, each step through ``run_job`` (a job or the Tx)."""
    now = settings.now_iso()
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

        result: NodeChanges = run_job(job)
        return result

    def removal(path: str) -> NodeChanges:
        def job(tx: Tx) -> NodeChanges:
            return upsert.delete_file(
                tx, path, keep_ids=analysis.keep_ids, now=now, initial=initial
            )

        result: NodeChanges = run_job(job)
        return result

    def phase2_job(f: SourceFile) -> None:
        res = analysis.resolved[f.path]

        def job(tx: Tx) -> int:
            return upsert.replace_file_rels(
                tx, f.path, res.rels, res.unresolved, content_hash=f.content_hash
            )

        run_job(job)

    for f in changed:
        totals.extend(phase1(f))
    for path in removed:
        totals.extend(removal(path))

    def shared_job(tx: Tx) -> NodeChanges:
        return upsert.sync_shared_nodes(tx, analysis.shared, now=now)

    shared_changes: NodeChanges = run_job(shared_job)
    totals.extend(shared_changes)
    if relink_all:
        phase2 = analysis.by_kind()
    else:
        # a document that mentions a code file that appeared or went away follows it
        done = {f.path for f in changed}
        moved = [
            f
            for f in analysis.by_kind()
            if f.path not in done and _mentions(f.result) & code_touched
        ]
        phase2 = sorted([*changed, *moved], key=lambda f: (KIND_ORDER.index(f.kind), f.path))
    for f in phase2:
        phase2_job(f)

    def meta(tx: Tx) -> None:
        upsert.write_meta(
            tx,
            schema_version=schema.SCHEMA_VERSION,
            project_name=settings.project_root.name,
            last_full_sync=now if full else None,
        )

    run_job(meta)
    changed_ids = {*totals.created, *totals.updated, *totals.deleted}
    changed_ids.update(f"file:{f.path}" for f in changed)
    changed_ids.update(f"file:{p}" for p in removed)
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
        changed_ids=sorted(changed_ids),
    )


def full_sync(store: Store, settings: Settings) -> SyncReport:
    """``sync(full=True)`` (the M01b name, kept for the CLI path and the tests)."""
    return sync(store, settings)
