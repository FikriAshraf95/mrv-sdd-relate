"""One sync order for startup, watcher batches, HEAD changes and ``sdd sync`` (SPEC-04 §2, §4, §6).

1. **Code phase 1**: File and Folder nodes for what changed (``files.sync_code``).
2. **Indexer**: the SDD Markdown, two phases (``indexer.sync``).
3. **Walker relationships**: ``TESTS`` and empty-folder pruning.
4. **Git**: commits and their links, when the sync is full or HEAD moved.

One ``checkpoint()`` at the end if the code or git steps wrote anything, then one
:class:`~sdd.sync.indexer.SyncReport` that carries ``code`` and ``git`` and every changed ID.
The caller serializes calls (the runtime's ``sync_lock``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from sdd.config import Settings
from sdd.graph.store import Store
from sdd.parse import ParseWarning
from sdd.parse.model import warn
from sdd.sync import files, git, indexer

__all__ = ["SyncState", "run"]


@dataclass
class SyncState:
    """What survives between syncs of one process (held by the Runtime)."""

    parse: indexer.ParseCache
    code: files.CodeCache
    rules: files.IgnoreRules
    classifier: indexer.Classifier
    tracked: set[str] = field(default_factory=set)  # SDD paths of the last indexer run

    @classmethod
    def new(cls, settings: Settings, parse: indexer.ParseCache | None = None) -> SyncState:
        """A fresh state (``sdd sync`` builds one per run)."""
        return cls(
            parse={} if parse is None else parse,
            code={},
            rules=files.IgnoreRules(settings.project_root),
            classifier=indexer.Classifier(settings),
        )


def run(
    store: Store,
    settings: Settings,
    state: SyncState,
    *,
    full: bool,
    paths: Iterable[str] = (),
    sdd_files: Mapping[str, str] | None = None,
    git_sync: bool = False,
) -> indexer.SyncReport:
    """Run the steps in order; ``paths`` are a batch's changed paths (ignored when ``full``)."""
    paths = frozenset(paths)
    state.rules.invalidate()
    code = files.sync_code(
        store,
        settings,
        cache=state.code,
        rules=state.rules,
        classifier=state.classifier,
        full=full,
        paths=paths,
    )

    # a code file that appeared or went away moves the links of the documents that mention it
    touched = frozenset(code.added | code.removed)
    mentioned = bool(touched) and bool(touched & indexer.mentions(state.parse).keys())
    if (
        full
        or any(p in state.tracked or (sdd_files and p in sdd_files) for p in paths)
        or mentioned
    ):
        tracked = dict(sdd_files) if sdd_files is not None else None
        if tracked is None:
            tracked = indexer.discover(settings, rules=state.rules)
        report = indexer.sync(
            store, settings, full=full, files=tracked, cache=state.parse, code_touched=touched
        )
        state.tracked = set(tracked)
    else:
        report = indexer.SyncReport.empty()

    # Walker relationships.
    if full or code.removed or report.removed:
        files.prune_folders(store, code)
    # a check that appeared or went away re-scans every test file, so late checks get their tests
    checks_moved = any(i.startswith("SPEC-") and "#ac" in i for i in report.changed_ids)
    files.scan_tests(store, settings, state.code, code, all_tests=full or checks_moved)
    # Feature globs: a diff against the stored IMPLEMENTED_IN, so a no-op sync writes nothing.
    features_moved = any(i.startswith("feature:") for i in report.changed_ids)
    counts: dict[str, int] = {}
    if full or code.wrote or report.indexed or features_moved:
        counts = files.expand_features(store, state.code, code)
        if report.indexed:
            report.warnings += _empty_globs(state, counts)

    git_report = None
    if full or git_sync:
        extra = files.CodeResult()  # files the git step had to add before it could link them

        def code_step(commit_paths: Sequence[str]) -> None:
            fresh = [
                p
                for p in commit_paths
                if p not in state.code and (settings.project_root / p).is_file()
            ]
            if fresh:
                extra.merge(_walk_paths(store, settings, state, fresh))

        git_report = git.sync_git(store, settings, code_step=code_step)
        if extra.written:  # a new test file in a commit gets its TESTS links now
            files.scan_tests(store, settings, state.code, extra, all_tests=False)
            files.expand_features(store, state.code, extra)  # and a new file its feature
        code.merge(extra)
        code.report.tests_links += extra.report.tests_links
        code.changed_ids |= extra.changed_ids

    if code.wrote or code.report.tests_links or (git_report is not None and git_report.wrote):
        store.checkpoint()

    report.code = code.report
    report.git = git_report
    ids = set(report.changed_ids) | code.changed_ids
    if git_report is not None:
        ids.update(git_report.changed_ids)
    report.changed_ids = sorted(ids)
    return report


def _empty_globs(state: SyncState, counts: Mapping[str, int]) -> list[ParseWarning]:
    """``feature_glob_empty`` for every Feature line whose globs matched no file (SPEC-03 §1)."""
    out: list[ParseWarning] = []
    for path, (_, kind, parsed) in sorted(state.parse.items()):
        if kind != "spec":
            continue
        for line in parsed.features:
            if line.implements and counts.get(f"feature:{line.slug}", 0) == 0:
                globs = ", ".join(line.implements)
                out.append(
                    warn(
                        path, line.line, "feature_glob_empty", f"{line.name}: {globs} match no file"
                    )
                )
    return out


def _walk_paths(
    store: Store, settings: Settings, state: SyncState, paths: Sequence[str]
) -> files.CodeResult:
    return files.sync_code(
        store,
        settings,
        cache=state.code,
        rules=state.rules,
        classifier=state.classifier,
        full=False,
        paths=paths,
    )
