"""Read views behind the HTTP API (SPEC-07 §2 endpoints 1–4, 6; plan M02 §5.3).

Every read runs through ``runtime.store.read`` (the store's worker thread, after any queued write).
Variable-length paths are not used: the focus expansion is a breadth-first search in Python,
one directed query per direction and hop.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sdd.errors import SddError
from sdd.graph import schema
from sdd.graph.store import Row
from sdd.ids import InvalidIdError, label_of, normalise
from sdd.service.runtime import Runtime
from sdd.service.status import read_status

__all__ = ["graph", "health", "milestones", "node", "status"]

DEFAULT_HIDDEN = frozenset({"Event", "Meta", "Agent"})
MAX_LIMIT = 2000
MAX_DEPTH = 3


def _canonical(raw: str) -> tuple[str, str]:
    try:
        ident = normalise(raw)
        return ident, label_of(ident)
    except InvalidIdError as exc:
        raise SddError("invalid_input", str(exc), details={"id": raw}) from None


def _shape(label: str, props: dict[str, Any]) -> dict[str, Any]:
    title = props.get("title") or props.get("name") or props["id"]
    return {"id": props["id"], "label": label, "title": title, "props": props}


def health(runtime: Runtime) -> dict[str, Any]:
    synced = runtime.synced_at
    if synced is None:
        rows = runtime.store.read("MATCH (m:Meta {id: 'meta'}) RETURN m.last_full_sync AS at")
        synced = rows[0]["at"] if rows else None
    return {
        "ok": True,
        "mode": runtime.mode,
        "synced_at": synced,
        "schema_version": schema.SCHEMA_VERSION,
        "instance": runtime.instance,
        "project": runtime.settings.project_root.name,
    }


def status(runtime: Runtime) -> dict[str, Any]:
    """As ``sdd status``; the warnings are the last sync's, not a re-parse per request."""
    warnings = runtime.last_report.warnings if runtime.last_report else []
    return read_status(runtime.store, runtime.settings, warnings)


def milestones(runtime: Runtime) -> list[dict[str, Any]]:
    out = []
    for m in status(runtime)["milestones"]:
        claimed = sum(1 for t in m["tasks"] if t["status"] == "claimed")
        out.append(
            {
                "id": m["id"],
                "title": m["title"],
                "status": m["status"],
                "order": m["order"],
                "done": m["done"],
                "claimed": claimed,
                "total": m["total"],
            }
        )
    return out


def graph(
    runtime: Runtime,
    labels: Iterable[str] | None = None,
    focus: str | None = None,
    depth: int = 1,
    limit: int = 300,
) -> dict[str, Any]:
    """``{nodes: [{id, label, title, props}], edges: [{source, target, type}]}``."""
    wanted = list(labels) if labels else [x for x in schema.LABELS if x not in DEFAULT_HIDDEN]
    unknown = [x for x in wanted if x not in schema.LABELS]
    if unknown:
        raise SddError("invalid_input", f"Unknown label(s): {', '.join(unknown)}.")
    if not 1 <= limit <= MAX_LIMIT:
        raise SddError("invalid_input", f"limit must be 1 to {MAX_LIMIT}.")
    if not 1 <= depth <= MAX_DEPTH:
        raise SddError("invalid_input", f"depth must be 1 to {MAX_DEPTH}.")
    store = runtime.store
    nodes: dict[str, dict[str, Any]] = {}

    if focus is None:
        for label in wanted:
            room = limit - len(nodes)
            if room <= 0:
                break
            rows = store.read(
                f"MATCH (n:{label}) RETURN properties(n) AS p ORDER BY n.id LIMIT {int(room)}"
            )
            for row in rows:
                nodes[row["p"]["id"]] = _shape(label, row["p"])
    else:
        ident, label = _canonical(focus)
        rows = store.read(f"MATCH (n:{label} {{id: $id}}) RETURN properties(n) AS p", {"id": ident})
        if not rows:
            raise SddError("node_not_found", f"No node {ident}.", details={"id": ident})
        nodes[ident] = _shape(label, rows[0]["p"])
        frontier = [ident]
        for _ in range(depth):
            found = _neighbours(runtime, frontier)
            frontier = []
            for row in sorted(found, key=lambda r: str(r["id"])):
                node_id = row["id"]
                if node_id in nodes or row["label"] not in wanted:
                    continue
                if len(nodes) >= limit:
                    break
                nodes[node_id] = _shape(row["label"], row["p"])
                frontier.append(node_id)
            if not frontier or len(nodes) >= limit:
                break

    edges: list[dict[str, str]] = []
    if nodes:
        ids = sorted(nodes)
        for row in store.read(
            "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids "
            "RETURN a.id AS source, b.id AS target, type(r) AS type",
            {"ids": ids},
        ):
            edges.append({"source": row["source"], "target": row["target"], "type": row["type"]})
    edges.sort(key=lambda e: (e["source"], e["target"], e["type"]))
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": edges}


def _neighbours(runtime: Runtime, frontier: list[str]) -> list[Row]:
    """Nodes one hop away from ``frontier`` in either direction: ``{id, label, p}`` rows."""
    out: list[Row] = []
    for cypher in (
        "MATCH (a)-[r]->(b) WHERE a.id IN $f RETURN b.id AS id, labels(b) AS l, properties(b) AS p",
        "MATCH (b)-[r]->(a) WHERE a.id IN $f RETURN b.id AS id, labels(b) AS l, properties(b) AS p",
    ):
        for row in runtime.store.read(cypher, {"f": frontier}):
            out.append({"id": row["id"], "label": row["l"][0], "p": row["p"]})
    return out


def node(runtime: Runtime, raw_id: str) -> dict[str, Any]:
    """One node with all properties and its relationships grouped by type (endpoint 4)."""
    ident, label = _canonical(raw_id)
    store = runtime.store
    rows = store.read(f"MATCH (n:{label} {{id: $id}}) RETURN properties(n) AS p", {"id": ident})
    if not rows:
        raise SddError("node_not_found", f"No node {ident}.", details={"id": ident})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for direction, cypher in (
        (
            "out",
            f"MATCH (n:{label} {{id: $id}})-[r]->(m) "
            "RETURN type(r) AS type, m.id AS id, labels(m) AS l, properties(m) AS p",
        ),
        (
            "in",
            f"MATCH (m)-[r]->(n:{label} {{id: $id}}) "
            "RETURN type(r) AS type, m.id AS id, labels(m) AS l, properties(m) AS p",
        ),
    ):
        for row in store.read(cypher, {"id": ident}):
            entry = _shape(row["l"][0], row["p"])
            grouped.setdefault(row["type"], []).append({"direction": direction, **entry})
    for items in grouped.values():
        items.sort(key=lambda e: (e["direction"], e["id"]))
    return {
        "id": ident,
        "label": label,
        "props": rows[0]["p"],
        "relationships": dict(sorted(grouped.items())),
    }
