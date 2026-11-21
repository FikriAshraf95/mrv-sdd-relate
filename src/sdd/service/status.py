"""``sdd status`` (SPEC-08 §2): milestones with their tasks, claims, warnings, unresolved links."""

from __future__ import annotations

from typing import Any

from sdd.config import Settings
from sdd.graph import schema
from sdd.graph.store import Store
from sdd.parse import ParseWarning
from sdd.service.indexing import by_severity
from sdd.sync import indexer


def status(settings: Settings) -> dict[str, Any]:
    """Read the planning state from the store.

    ``:memory:`` syncs into the throwaway store first. Otherwise the store is opened read-only
    (``invalid_input`` if it does not exist yet), so it works next to a running writer.
    """
    analysis = indexer.analyse(settings)
    if settings.in_memory:
        with Store.open(settings.store_path) as store:
            schema.ensure(store)
            indexer.full_sync(store, settings)
            return _read(store, settings, analysis.warnings)
    with Store.open(settings.store_path, read_only=True) as store:
        return _read(store, settings, analysis.warnings)


def _read(store: Store, settings: Settings, warnings: list[ParseWarning]) -> dict[str, Any]:
    milestones = store.read(
        "MATCH (m:Milestone) RETURN m.id AS id, m.title AS title, m.status AS status, "
        "m.order AS ord"
    )
    tasks = store.read(
        "MATCH (t:Task) RETURN t.id AS id, t.milestone_id AS milestone_id, t.title AS title, "
        "t.checked AS checked, t.status AS status, t.claimed_by AS claimed_by, "
        "t.claimed_at AS claimed_at, t.order AS ord"
    )
    by_milestone: dict[str, list[dict[str, Any]]] = {}
    for task in sorted(tasks, key=lambda t: (str(t["milestone_id"]), t["ord"] or 0)):
        by_milestone.setdefault(str(task["milestone_id"]), []).append(
            {
                "id": task["id"],
                "title": task["title"],
                "checked": bool(task["checked"]),
                "status": task["status"],
                "claimed_by": task["claimed_by"],
            }
        )
    out_milestones = []
    for m in sorted(milestones, key=lambda m: str(m["ord"])):
        items = by_milestone.get(m["id"], [])
        out_milestones.append(
            {
                "id": m["id"],
                "title": m["title"],
                "status": m["status"],
                "order": m["ord"],
                "done": sum(1 for t in items if t["status"] == "done"),
                "total": len(items),
                "tasks": items,
            }
        )
    claims = [
        {"task": t["id"], "agent": t["claimed_by"], "claimed_at": t["claimed_at"]}
        for t in tasks
        if t["claimed_by"] and t["status"] != "done"
    ]
    unresolved = {
        row["id"]: row["unresolved"]
        for row in store.read(
            "MATCH (n) WHERE n.unresolved IS NOT NULL RETURN n.id AS id, n.unresolved AS unresolved"
        )
    }
    unticked = store.read(
        "MATCH (c:Commit)-[:COMPLETES]->(t:Task) WHERE t.checked = false "
        "RETURN t.id AS task, c.id AS commit ORDER BY t.id"
    )
    return {
        "milestones": out_milestones,
        "claims": sorted(claims, key=lambda c: str(c["task"])),
        "unresolved": dict(sorted(unresolved.items())),
        "warnings": by_severity(warnings),
        "unticked_completed": unticked,
        "writeback": settings.writeback,
    }
