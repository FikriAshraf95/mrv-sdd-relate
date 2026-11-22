"""``sdd sync`` and ``sdd doctor`` (SPEC-08 §2): one full sync, and a read-only Markdown check."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sdd.config import Settings
from sdd.graph import schema
from sdd.graph.store import Store
from sdd.parse import ParseWarning
from sdd.service import remote
from sdd.sync import indexer, pipeline

SEVERITIES = ("error", "warning", "info")


def warning_dict(w: ParseWarning) -> dict[str, Any]:
    return {
        "path": w.path,
        "line": w.line,
        "code": w.code,
        "severity": w.severity,
        "message": w.message,
    }


def by_severity(warnings: list[ParseWarning]) -> dict[str, int]:
    return {s: sum(1 for w in warnings if w.severity == s) for s in SEVERITIES}


def report_dict(
    settings: Settings, report: indexer.SyncReport, counts: schema.Counts
) -> dict[str, Any]:
    """The result shape of one sync, shared by ``sdd sync`` and the daemon's ``POST /api/sync``."""
    return {
        "store": settings.store_path,
        "initial": report.initial,
        "scanned": report.scanned,
        "changed": report.changed,
        "removed": report.removed,
        "relinked": report.relinked,
        "created": report.created,
        "updated": report.updated,
        "deleted": report.deleted,
        "events": report.events,
        "warnings": [warning_dict(w) for w in report.warnings],
        "warnings_by_severity": by_severity(report.warnings),
        "unresolved": report.unresolved,
        "unresolved_total": sum(len(v) for v in report.unresolved.values()),
        "code": asdict(report.code) if report.code is not None else None,
        "git": report.git.as_dict() if report.git is not None else None,
        "nodes": counts.total_nodes,
        "relationships": counts.total_relationships,
    }


def sync(settings: Settings, *, reset: bool = False) -> dict[str, Any]:
    """One full sync into the store (``daemon_running`` if another process holds it).

    A running daemon for this project's store refuses first (SPEC-01 §1 rule 3); the writer lock
    is the final authority. ``reset`` empties the store in place first (D002); graph-only state
    is lost. An in-memory store is new anyway, so nothing is written to disk.
    """
    remote.ensure_no_daemon(settings)
    with Store.open(settings.store_path) as store:
        schema.ensure(store)
        if reset:
            indexer.reset(store)
        report = pipeline.run(store, settings, pipeline.SyncState.new(settings), full=True)
        counts = schema.counts(store)
    return report_dict(settings, report, counts)


def doctor(settings: Settings) -> dict[str, Any]:
    """Parse and resolve the Markdown; report every warning and unresolved link.

    Never opens the store (SPEC-08 §2), so it runs on a read-only checkout.
    """
    analysis = indexer.analyse(settings)
    nodes = [n for f in analysis.files for n in f.result.nodes]
    unresolved = analysis.unresolved
    severities = by_severity(analysis.warnings)
    return {
        "project": str(settings.project_root),
        "counts": {
            "files": len(analysis.files),
            "specs": sum(1 for n in nodes if n.label == "Spec"),
            "sections": sum(1 for n in nodes if n.label == "Section"),
            "milestones": sum(1 for n in nodes if n.label == "Milestone"),
            "tasks": sum(1 for n in nodes if n.label == "Task"),
            "deviations": sum(1 for n in nodes if n.label == "Deviation"),
            "tables": sum(1 for n in nodes if n.label == "Table"),
            "columns": sum(1 for n in nodes if n.label == "Column"),
            "references": sum(
                1 for res in analysis.resolved.values() for r in res.rels if r.type == "REFERENCES"
            ),
            "legacy_task_lines": sum(
                1 for n in nodes if n.label == "Task" and not n.props.get("stable_id")
            ),
            "unresolved_links": sum(len(v) for v in unresolved.values()),
        },
        "warnings_by_severity": severities,
        "warnings": [warning_dict(w) for w in analysis.warnings],
        "unresolved": unresolved,
        "ok": severities["error"] == 0,
    }
