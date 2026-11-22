"""``sdd export`` (SPEC-08 §3): Mermaid, Cypher script, JSON and the CLAUDE.md status block.

Every export reads the graph through a :class:`Runtime` the caller opened (``commands.export_*``:
a read-only open of the store files beside a running daemon, or a throwaway sync for
``:memory:``). The renderers (:func:`render_mermaid`, :func:`render_cypher`,
:func:`status_block`) are pure, so their output is deterministic and golden-testable: no
timestamps, no ordering that depends on the engine.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import Any

from sdd.graph import queries, store
from sdd.service import impact, query_guard
from sdd.service.api_views import shape_node
from sdd.service.runtime import Runtime
from sdd.sync import writeback

__all__ = [
    "claude_status",
    "export_cypher",
    "export_json",
    "export_mermaid",
    "is_cypher",
    "load_cypher",
    "render_cypher",
    "render_mermaid",
    "status_block",
]

MAX_NODES = 60
MAX_LABEL = 60
# SPEC-08 §3: a --mermaid argument that starts like a Cypher clause is a query, else a preset.
_CYPHER_START = re.compile(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|CALL|RETURN)\b", re.IGNORECASE)

# node shape per label: (open, close); everything else is a plain box
_SHAPES: dict[str, tuple[str, str]] = {
    "Spec": ("[[", "]]"),
    "Section": ("[", "]"),
    "Task": ("(", ")"),
    "Deviation": ("{{", "}}"),
    "File": ("[/", "/]"),
    "Table": ("[(", ")]"),
    "Milestone": ("([", "])"),
    "Feature": (">", "]"),
}
_BOX = ("[", "]")
# fill (the dashboard's dark-theme hues, which read with dark text) and stroke (its light hues)
_COLORS: dict[str, tuple[str, str]] = {
    "Spec": ("#60a5fa", "#2563eb"),
    "Section": ("#93c5fd", "#60a5fa"),
    "Milestone": ("#a78bfa", "#7c3aed"),
    "Task": ("#2dd4bf", "#0d9488"),
    "Deviation": ("#f87171", "#dc2626"),
    "File": ("#94a3b8", "#64748b"),
    "Commit": ("#facc15", "#a16207"),
    "Feature": ("#f472b6", "#db2777"),
    "Domain": ("#fb923c", "#ea580c"),
    "Table": ("#4ade80", "#15803d"),
    "Column": ("#a3e635", "#65a30d"),
    "Agent": ("#22d3ee", "#0891b2"),
    "AcceptanceCheck": ("#38bdf8", "#0ea5e9"),
    "Doc": ("#c4b5fd", "#8b5cf6"),
    "Folder": ("#94a3b8", "#475569"),
}
_OTHER = ("#cbd5e1", "#64748b")


# ---------------------------------------------------------------- Mermaid


def is_cypher(argument: str) -> bool:
    """Whether a ``--mermaid`` argument is a Cypher query (else it names a preset)."""
    return _CYPHER_START.match(argument) is not None


def _label_text(node: dict[str, Any]) -> str:
    ident, title = str(node["id"]), str(node.get("title") or node["id"])
    if node["label"] == "Label":  # the schema preset: "Table (12)"
        text = title
    elif node["label"] == "Commit" and node.get("props", {}).get("message"):
        message = str(node["props"]["message"]).strip().splitlines()[0]
        text = f"{ident.removeprefix('commit:')[:7]}: {message}"  # a SHA alone says nothing
    else:
        text = ident if title == ident else f"{ident}: {title}"
    text = " ".join(text.split())  # newlines and runs of blanks
    if len(text) > MAX_LABEL:
        text = text[: MAX_LABEL - 1] + "…"
    text = re.sub(r"#(?=\w+;)", "#35;", text)  # a literal `#name;` would read as an entity
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def render_mermaid(graph: dict[str, Any], *, max_nodes: int = MAX_NODES) -> str:
    """A ``{nodes, edges}`` graph as a Mermaid ``flowchart LR`` (SPEC-08 §3).

    The first node is the root and stays first; the rest are sorted by ``(label, id)``. At most
    ``max_nodes`` are drawn (edges to dropped nodes go too) and a last ``%% truncated N nodes``
    line says how many were left out. Mermaid IDs are ``n0``, ``n1``, … in that order.
    """
    nodes = list(graph["nodes"])
    if nodes:
        nodes = [nodes[0], *sorted(nodes[1:], key=lambda n: (n["label"], n["id"]))]
    dropped = max(0, len(nodes) - max_nodes)
    nodes = nodes[:max_nodes]
    index = {n["id"]: i for i, n in enumerate(nodes)}
    lines = ["flowchart LR"]
    for i, node in enumerate(nodes):
        left, right = _SHAPES.get(node["label"], _BOX)
        lines.append(f'    n{i}{left}"{_label_text(node)}"{right}')
    edges = sorted(
        (index[e["source"]], str(e["type"]), index[e["target"]], e.get("count"))
        for e in graph["edges"]
        if e["source"] in index and e["target"] in index
    )
    for source, kind, target, count in edges:
        label = kind if count is None else f'"{kind} ({count})"'
        lines.append(f"    n{source} -->|{label}| n{target}")
    by_label: dict[str, list[str]] = {}
    for i, node in enumerate(nodes):
        # schema nodes (label "Label") take the colour of the label they stand for
        kind = node["id"] if node["label"] == "Label" else node["label"]
        by_label.setdefault(kind, []).append(f"n{i}")
    for label in sorted(by_label):
        fill, stroke = _COLORS.get(label, _OTHER)
        lines.append(f"    classDef {label.lower()} fill:{fill},stroke:{stroke},color:#111")
    for label in sorted(by_label):
        lines.append(f"    class {','.join(by_label[label])} {label.lower()}")
    if dropped:
        lines.append(f"%% truncated {dropped} nodes")
    return "\n".join(lines) + "\n"


def _cypher_graph(runtime: Runtime, cypher: str) -> dict[str, Any]:
    """A guarded query result as a graph: maps with an ``id`` are nodes, rows with ``source``
    and ``target`` columns are edges (``type`` optional, default ``RELATED``)."""
    result = query_guard.run_query(runtime, cypher)
    columns: list[str] = result["columns"]
    order: list[str] = []
    edges: list[tuple[str, str, str]] = []

    def ident(value: Any) -> str | None:
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            return str(value["id"])
        return value if isinstance(value, str) else None

    for row in result["rows"]:
        cells = dict(zip(columns, row, strict=False))
        for value in row:
            found = ident(value) if isinstance(value, dict) else None
            if found is not None and found not in order:
                order.append(found)
        if "source" in cells and "target" in cells:
            source, target = ident(cells["source"]), ident(cells["target"])
            if source is not None and target is not None:
                for end in (source, target):
                    if end not in order:
                        order.append(end)
                kind = cells.get("type")
                edges.append((source, target, str(kind) if kind else "RELATED"))
    found_nodes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(order), 500):
        for row in queries.run(
            runtime.store, "export.mermaid_nodes", ids=order[start : start + 500]
        ):
            node = shape_node(str(row["label"]), row["p"])
            found_nodes[node["id"]] = node
    known = [i for i in order if i in found_nodes]
    return {
        "nodes": [found_nodes[i] for i in known],
        "edges": [
            {"source": s, "target": t, "type": k}
            for s, t, k in edges
            if s in found_nodes and t in found_nodes
        ],
    }


def export_mermaid(runtime: Runtime, argument: str) -> str:
    """``--mermaid PRESET|CYPHER``: the Mermaid text of a preset or of a query result."""
    if is_cypher(argument):
        return render_mermaid(_cypher_graph(runtime, argument))
    return render_mermaid(impact.preset(runtime, argument.strip()))


# ---------------------------------------------------------------- the whole graph


def _all(runtime: Runtime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = queries.run(runtime.store, "export.nodes")
    edges = queries.run(runtime.store, "export.edges")
    return nodes, edges


def export_json(runtime: Runtime) -> str:
    """``--json``: ``{nodes, edges}`` in the ``/api/graph`` shape, no limit, sorted."""
    rows, rels = _all(runtime)
    nodes = sorted((shape_node(str(r["label"]), r["p"]) for r in rows), key=lambda n: n["id"])
    edges = sorted(
        ({"source": r["source"], "target": r["target"], "type": r["type"]} for r in rels),
        key=lambda e: (e["source"], e["type"], e["target"]),
    )
    return json.dumps({"nodes": nodes, "edges": edges}, indent=2, ensure_ascii=False) + "\n"


_PLAIN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Relate reads \n and \t but not \r in a string literal; \uXXXX works for any BMP character
_ESCAPES = {"\\": "\\\\", "'": "\\'", "\n": "\\n", "\t": "\\t", "\r": "\\u000d"}


def _escape(ch: str) -> str:
    if ch in _ESCAPES:
        return _ESCAPES[ch]
    # line separators and other unprintable characters never appear raw: one statement, one line
    if not ch.isprintable() and ord(ch) < 0x10000:
        return f"\\u{ord(ch):04x}"
    return ch


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_literal(v) for v in value) + "]"
    text = "".join(_escape(ch) for ch in str(value))
    return f"'{text}'"


def _props(props: dict[str, Any], *, skip: Iterable[str] = ()) -> str:
    """``{k: v, …}``: keys sorted, nulls and ``skip`` left out, keys backquoted if needed."""
    stored = store.encode_props(props)
    parts = []
    for key in sorted(stored):
        if key in skip or stored[key] is None:
            continue
        name = key if _PLAIN_KEY.match(key) else "`" + key.replace("`", "``") + "`"
        parts.append(f"{name}: {_literal(stored[key])}")
    return "{" + ", ".join(parts) + "}"


def render_cypher(nodes: Sequence[dict[str, Any]], edges: Sequence[dict[str, Any]]) -> str:
    """The idempotent Cypher script of a graph (SPEC-08 §3): one statement per line, each
    ending in ``;``; ``//`` header lines; nodes by ``id``, then relationships by source, type,
    target (properties inside the ``MERGE`` pattern, so parallel relationships survive).
    Properties are written as stored (``header_json`` stays a string), so re-importing
    round-trips them. No timestamp, so a re-export diffs cleanly."""
    lines = [
        f"// sdd export --cypher · {len(nodes)} nodes · {len(edges)} relationships",
        "// One statement per line; every statement ends in ';'. Idempotent (MERGE by id).",
    ]
    for node in sorted(nodes, key=lambda n: str(n["p"]["id"])):
        props = _props(node["p"], skip=("id",))
        ident = _literal(node["p"]["id"])
        tail = "" if props == "{}" else f" SET n += {props}"
        lines.append(f"MERGE (n:{node['label']} {{id: {ident}}}){tail};")
    for edge in sorted(edges, key=lambda e: (str(e["source"]), str(e["type"]), str(e["target"]))):
        # the properties are part of the MERGE pattern: two relationships of one type between
        # the same nodes (a deviation's own file and the spec note that amends) differ in `src`
        props = _props(edge["p"] or {})
        pattern = f"r:{edge['type']}" + ("" if props == "{}" else f" {props}")
        lines.append(
            f"MATCH (a:{edge['source_label']} {{id: {_literal(edge['source'])}}}), "
            f"(b:{edge['target_label']} {{id: {_literal(edge['target'])}}}) "
            f"MERGE (a)-[{pattern}]->(b);"
        )
    return "\n".join(lines) + "\n"


def export_cypher(runtime: Runtime) -> str:
    nodes, edges = _all(runtime)
    return render_cypher(nodes, edges)


def load_cypher(target: store.Store, script: str) -> int:
    """Run an exported script into ``target`` in one write job; returns the statements run.

    Lines are split on ``\\n`` only (strings are escaped, so one statement is one line); blank
    and ``//`` lines are skipped. Used by the tests and by the static demo build.
    """
    statements = [
        line.strip().removesuffix(";")
        for line in script.split("\n")
        if line.strip() and not line.lstrip().startswith("//")
    ]

    def job(tx: store.Tx) -> int:
        for statement in statements:
            tx.run(statement)
        return len(statements)

    return target.write(job)


# ---------------------------------------------------------------- the CLAUDE.md status block


def _section_name(row: dict[str, Any]) -> str:
    if row["label"] == "Spec":
        return str(row["id"])
    number = row.get("number")
    return f"{row['spec_id']} §{number}" if number else f"{row['spec_id']} {row['title']}"


def _number_key(row: dict[str, Any]) -> tuple[str, tuple[int, ...], str]:
    number = str(row.get("number") or "")
    parts = tuple(int(p) for p in number.split(".") if p.isdigit())
    return (str(row.get("spec_id") or row["id"]), parts, str(row["id"]))


def status_block(
    milestones: Sequence[dict[str, Any]],
    tasks: Sequence[dict[str, Any]],
    reads: Sequence[dict[str, Any]],
    deviations: Sequence[dict[str, Any]],
) -> str:
    """The text between the CLAUDE.md markers (SPEC-08 §3), deterministic, no timestamps."""
    ordered = sorted(milestones, key=lambda m: str(m["ord"]))
    done = [m for m in ordered if m["status"] == "done"]
    done_text = " · ".join(
        f"{m['id']} {m['title']}" + (f" ({m['done_date']})" if m["done_date"] else "") for m in done
    )
    pending = next((m for m in ordered if m["status"] != "done"), None)
    if pending is None:
        next_text = "none, every milestone is done"
    else:
        mine = [t for t in tasks if t["milestone_id"] == pending["id"]]
        open_count = sum(1 for t in mine if t["status"] != "done")
        link = f"[{pending['id']} {pending['title']}]({pending['path']})"
        refs = sorted((r for r in reads if r["milestone"] == pending["id"]), key=_number_key)
        names = " · ".join(dict.fromkeys(_section_name(r) for r in refs))
        next_text = f"{link} ({open_count}/{len(mine)} tasks open)" + (
            f". Read first: {names}" if names else ""
        )
    open_devs = sorted((d for d in deviations if d["status"] == "open"), key=lambda d: d["id"])
    dev_text = " · ".join(
        f"{d['id']} {d['title']}" + (f" ({d['milestone']})" if d["milestone"] else "")
        for d in open_devs
    )
    claimed = sorted(
        (t for t in tasks if t["claimed_by"] and t["status"] != "done"), key=lambda t: t["id"]
    )
    claim_text = " · ".join(f"{t['id']} by {t['claimed_by']}" for t in claimed)
    return "\n".join(
        [
            "_Generated by `sdd export --claude-status`; edit outside the markers._",
            f"- **Done:** {done_text or 'none'}",
            f"- **Next:** {next_text}",
            f"- **Open deviations:** {dev_text or 'none'}",
            f"- **Active claims:** {claim_text or 'none'}",
        ]
    )


def claude_status(runtime: Runtime) -> dict[str, Any]:
    """``--claude-status``: fill the block in the project's CLAUDE.md; ``{path, changed}``."""
    st = runtime.store
    milestones = st.read(
        "MATCH (m:Milestone) RETURN m.id AS id, m.title AS title, m.status AS status, "
        "m.order AS ord, m.done_date AS done_date, m.path AS path"
    )
    tasks = st.read(
        "MATCH (t:Task) RETURN t.id AS id, t.milestone_id AS milestone_id, t.status AS status, "
        "t.claimed_by AS claimed_by"
    )
    reads = st.read(
        "MATCH (m:Milestone)-[:READS]->(x) RETURN m.id AS milestone, x.id AS id, "
        "labels(x)[0] AS label, x.spec_id AS spec_id, x.number AS number, x.title AS title"
    )
    deviations = st.read(
        "MATCH (d:Deviation) OPTIONAL MATCH (d)-[:RAISED_IN]->(x) "
        "RETURN d.id AS id, d.title AS title, d.status AS status, x.id AS raised"
    )
    merged: dict[str, dict[str, Any]] = {}
    for row in deviations:
        entry = merged.setdefault(
            str(row["id"]),
            {"id": row["id"], "title": row["title"], "status": row["status"], "milestone": None},
        )
        raised = row["raised"]
        if raised and entry["milestone"] is None:
            entry["milestone"] = str(raised).split(".", 1)[0]  # a task ID → its milestone
    block = status_block(milestones, tasks, reads, list(merged.values()))
    path = "CLAUDE.md"
    return {"path": path, "changed": writeback.write_status_block(runtime.settings, block, path)}
