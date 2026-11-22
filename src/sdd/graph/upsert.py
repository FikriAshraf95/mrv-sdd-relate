"""Graph upserts: nodes, ``src``-owned relationships, removals, Events, Meta (SPEC-02 §2, §4–5;
SPEC-04 §2–3; plan M01b §2).

Plain data in, Cypher out: this module never imports ``parse/`` or ``sync/``. ``sync/`` resolves
links and hands over :class:`NodeIn` / :class:`RelIn` lists. Every function that takes a
:class:`~sdd.graph.store.Tx` runs inside the caller's write job (one job = one transaction).

Write strategy (probed on relate-db 1.2): ``MERGE (n:Label {id: row.id}) SET n = row.props``
replaces the whole property map, so the final map is computed in Python by :func:`merge_props`
(pure, unit-tested) and written once. Labels and relationship types cannot be Cypher
parameters; they are formatted into statements only after a whitelist check.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sdd.graph import schema
from sdd.graph.store import Row, Store, Tx, encode_props
from sdd.ids import label_of, new_ulid

__all__ = [
    "CATALOG_LABELS",
    "GRAPH_ONLY_TASK_PROPS",
    "FileIn",
    "GraphState",
    "MergeFlags",
    "NodeChanges",
    "NodeIn",
    "RelIn",
    "add_event",
    "delete_file",
    "merge_props",
    "read_file_paths",
    "read_state",
    "replace_file_rels",
    "sync_shared_nodes",
    "task_status",
    "upsert_file_nodes",
    "write_meta",
]

GRAPH_ONLY_TASK_PROPS = ("claimed_by", "claimed_at", "completed_by", "done_at", "notes")
# Labels whose rows the re-link fingerprint reads back from the graph (plan M01b §2.6).
CATALOG_LABELS = (
    "Spec",
    "Section",
    "AcceptanceCheck",
    "Milestone",
    "Task",
    "Deviation",
    "Doc",
    "File",
    "Table",
)


@dataclass(frozen=True, slots=True)
class NodeIn:
    label: str
    id: str
    props: dict[str, Any]  # parsed properties, without ``last_synced``


@dataclass(frozen=True, slots=True)
class RelIn:
    type: str
    from_id: str
    to_id: str
    props: dict[str, Any] = field(default_factory=dict)  # ``note`` / ``whole``; no ``src``


@dataclass(frozen=True, slots=True)
class FileIn:
    path: str
    content_hash: str


@dataclass(slots=True)
class NodeChanges:
    """What one or more jobs did, for the report and the Events."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    sections_changed: list[str] = field(default_factory=list)
    ticked: list[str] = field(default_factory=list)
    unticked: list[str] = field(default_factory=list)
    released: list[str] = field(default_factory=list)
    events: int = 0

    def extend(self, other: NodeChanges) -> None:
        self.created += other.created
        self.updated += other.updated
        self.deleted += other.deleted
        self.sections_changed += other.sections_changed
        self.ticked += other.ticked
        self.unticked += other.unticked
        self.released += other.released
        self.events += other.events


@dataclass(frozen=True, slots=True)
class MergeFlags:
    ticked: bool = False
    unticked: bool = False
    section_changed: bool = False


@dataclass(frozen=True, slots=True)
class GraphState:
    files: dict[str, str]
    last_full_sync: str | None
    catalog_rows: list[Row]


def _label(label: str) -> str:
    if label not in schema.LABELS:
        raise ValueError(f"unknown label {label!r}")
    return label


def _rel_type(type_: str) -> str:
    if type_ not in schema.REL_TYPES:
        raise ValueError(f"unknown relationship type {type_!r}")
    return type_


# ---------------------------------------------------------------- pure property rules


def task_status(props: Mapping[str, Any], writeback: bool) -> str:
    """``done`` if checked (or completed by a tool without write-back); else claimed; else todo."""
    if props.get("checked") or (not writeback and props.get("completed_by")):
        return "done"
    return "claimed" if props.get("claimed_by") else "todo"


def merge_props(
    label: str,
    existing: Mapping[str, Any] | None,
    parsed: Mapping[str, Any],
    *,
    now: str,
    initial: bool,
    writeback: bool,
    spec_existed: bool,
) -> tuple[dict[str, Any], MergeFlags]:
    """The final property map of one node (SPEC-02 §2, SPEC-04 §2.1). Pure.

    ``existing`` is the node as stored (decoded), or ``None`` for a new node. ``unresolved`` is
    never taken from Markdown; Section ``changed_at`` and the graph-only Task properties are kept
    from ``existing`` except in the cases of the SPEC-04 §2.1 table.
    """
    props: dict[str, Any] = {k: v for k, v in parsed.items() if v is not None}
    props["last_synced"] = now
    flags = MergeFlags()
    old = existing or {}
    if "unresolved" in old:
        props["unresolved"] = old["unresolved"]

    if label == "Section":
        changed = old.get("changed_at")
        if existing is None:
            if not initial and spec_existed:
                changed = now
        elif not initial and old.get("content_hash") != props.get("content_hash"):
            changed = now
        if changed is not None:
            props["changed_at"] = changed
        flags = MergeFlags(section_changed=changed == now and old.get("changed_at") != now)
    elif label == "Task":
        for key in GRAPH_ONLY_TASK_PROPS:
            if old.get(key) is not None:
                props[key] = old[key]
        ticked = unticked = False
        if existing is not None:
            was, is_ = bool(old.get("checked")), bool(props.get("checked"))
            if not was and is_ and not initial:
                ticked = True
                props["done_at"] = old.get("done_at") or now
                props.pop("claimed_by", None)
                props.pop("claimed_at", None)
            elif was and not is_:
                unticked = True
                props.pop("done_at", None)
                props.pop("completed_by", None)
        props["status"] = task_status(props, writeback)
        flags = MergeFlags(ticked=ticked, unticked=unticked)
    return props, flags


# ---------------------------------------------------------------- phase 1


def _existing_nodes(tx: Tx, nodes: list[NodeIn]) -> dict[str, Row]:
    by_label: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        by_label[node.label].append(node.id)
    found: dict[str, Row] = {}
    for label, ids in by_label.items():
        rows = tx.run(
            f"MATCH (n:{_label(label)}) WHERE n.id IN $ids RETURN properties(n) AS p",
            {"ids": ids},
        )
        found.update({row["p"]["id"]: row["p"] for row in rows})
    return found


def upsert_file_nodes(
    tx: Tx,
    file: FileIn,
    nodes: list[NodeIn],
    *,
    keep_ids: set[str],
    now: str,
    initial: bool,
    writeback: bool,
) -> NodeChanges:
    """Phase 1 for one file: write its nodes and File node, delete the nodes it no longer has."""
    changes = NodeChanges()
    existing = _existing_nodes(tx, nodes)
    spec_ids = [n.id for n in nodes if n.label == "Spec"]
    spec_existed = any(i in existing for i in spec_ids)

    ordered = sorted(nodes, key=lambda n: n.label == "Milestone")  # tasks before their milestone
    final: dict[str, tuple[str, dict[str, Any]]] = {}
    task_states: dict[str, list[str]] = defaultdict(list)
    for node in ordered:
        old = existing.get(node.id)
        props, flags = merge_props(
            node.label,
            old,
            node.props,
            now=now,
            initial=initial,
            writeback=writeback,
            spec_existed=spec_existed,
        )
        props["id"] = node.id
        if node.label == "Task":
            task_states[str(props.get("milestone_id"))].append(props["status"])
        elif node.label == "Milestone" and props.get("status") != "done":
            states = task_states.get(node.id, [])
            props["status"] = (
                "in_progress" if any(s in ("done", "claimed") for s in states) else "todo"
            )
        final[node.id] = (node.label, props)
        if old is None:
            changes.created.append(node.id)
        elif _differs(old, props):
            changes.updated.append(node.id)
        if flags.section_changed:
            changes.sections_changed.append(node.id)
        if flags.ticked:
            changes.ticked.append(node.id)
        if flags.unticked:
            changes.unticked.append(node.id)

    rows_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, (label, props) in final.items():
        rows_by_label[label].append({"id": node_id, "props": encode_props(props)})
    for label, rows in rows_by_label.items():
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{_label(label)} {{id: row.id}}) SET n = row.props",
            {"rows": rows},
        )
    for task_id in changes.ticked:
        tx.run("MATCH (:Agent)-[r:CLAIMED]->(:Task {id: $id}) DELETE r", {"id": task_id})

    # content_hash is left as it was: phase 2 sets it with the relationships, so a sync that
    # stops between the phases sees this file as changed next time.
    tx.run(
        "MERGE (f:File {id: $id}) SET f.path = $path, f.name = $name, f.last_synced = $now",
        {
            "id": f"file:{file.path}",
            "path": file.path,
            "name": file.path.rsplit("/", 1)[-1],
            "now": now,
        },
    )

    produced = set(final)
    stale = tx.run(
        "MATCH (n) WHERE n.source_path = $path "
        "RETURN n.id AS id, labels(n) AS labels, n.claimed_by AS claimed_by",
        {"path": file.path},
    )
    gone = [r for r in stale if r["id"] not in produced and r["id"] not in keep_ids]
    _delete_nodes(tx, gone, changes, now=now, initial=initial)

    if not initial:
        _emit_phase1_events(tx, changes, final, now)
    return changes


def sync_shared_nodes(tx: Tx, nodes: list[NodeIn], *, now: str) -> NodeChanges:
    """Write the Feature and Domain nodes the specs declare, delete the ones nobody declares.

    They have no ``source_path`` (several specs can declare one), so the per-file rules do not
    apply; the caller merged them across files. Only a node whose properties differ is written.
    No Events (plan M04b §2).
    """
    changes = NodeChanges()
    wanted = {n.id: n for n in nodes}
    stored: dict[str, tuple[str, Row]] = {}
    for label in ("Feature", "Domain"):
        for row in tx.run(f"MATCH (n:{_label(label)}) RETURN properties(n) AS p"):
            stored[row["p"]["id"]] = (label, row["p"])
    rows_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, node in wanted.items():
        props = {**node.props, "id": node_id}
        old = stored.get(node_id)
        if old is None:
            changes.created.append(node_id)
        elif _differs(old[1], props):
            changes.updated.append(node_id)
        else:
            continue
        rows_by_label[node.label].append(
            {"id": node_id, "props": encode_props({**props, "last_synced": now})}
        )
    for label, rows in rows_by_label.items():
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{_label(label)} {{id: row.id}}) SET n = row.props",
            {"rows": rows},
        )
    gone: dict[str, list[str]] = defaultdict(list)
    for node_id, (label, _) in stored.items():
        if node_id not in wanted:
            gone[label].append(node_id)
            changes.deleted.append(node_id)
    for label, ids in gone.items():
        tx.run(f"MATCH (n:{_label(label)}) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})
    return changes


def _differs(old: Mapping[str, Any], new: Mapping[str, Any]) -> bool:
    skip = {"last_synced", "unresolved"}
    return {k: v for k, v in old.items() if k not in skip} != {
        k: v for k, v in new.items() if k not in skip
    }


def _emit_phase1_events(
    tx: Tx, changes: NodeChanges, final: Mapping[str, tuple[str, dict[str, Any]]], now: str
) -> None:
    for task_id in changes.ticked:
        add_event(
            tx,
            kind="task_completed",
            actor="human",
            target_id=task_id,
            summary=f"{task_id} ticked by hand",
            data={},
            now=now,
        )
        changes.events += 1
    for section_id in changes.sections_changed:
        add_event(
            tx,
            kind="section_changed",
            actor="sync",
            target_id=section_id,
            summary=f"{section_id} changed",
            data={},
            now=now,
        )
        changes.events += 1
    for node_id in changes.created:
        if final[node_id][0] == "Spec":
            add_event(
                tx,
                kind="spec_added",
                actor="sync",
                target_id=node_id,
                summary=f"{node_id} added",
                data={},
                now=now,
            )
            changes.events += 1


def _delete_nodes(
    tx: Tx, rows: list[Row], changes: NodeChanges, *, now: str, initial: bool
) -> None:
    """Detach-delete the rows, then record the Events (so no ABOUT is created and then removed:
    deleting a relationship created in the same transaction panics the engine)."""
    by_label: dict[str, list[str]] = defaultdict(list)
    pending: list[dict[str, Any]] = []
    for row in rows:
        label = next((lb for lb in row["labels"] if lb in schema.LABELS), None)
        if label is None:
            continue
        by_label[label].append(row["id"])
        changes.deleted.append(row["id"])
        if initial:
            continue
        if label == "Task" and row.get("claimed_by"):
            changes.released.append(row["id"])
            pending.append(
                {
                    "kind": "task_released",
                    "target_id": row["id"],
                    "summary": f"{row['id']} removed while claimed by {row['claimed_by']}",
                    "data": {"claimed_by": row["claimed_by"]},
                }
            )
        elif label == "Spec":
            pending.append(
                {
                    "kind": "spec_removed",
                    "target_id": row["id"],
                    "summary": f"{row['id']} removed",
                    "data": {},
                }
            )
    for label, ids in by_label.items():
        tx.run(f"MATCH (n:{_label(label)}) WHERE n.id IN $ids DETACH DELETE n", {"ids": ids})
    for event in pending:
        add_event(tx, actor="sync", now=now, **event)
        changes.events += 1


# ---------------------------------------------------------------- phase 2


def replace_file_rels(
    tx: Tx,
    src: str,
    rels: list[RelIn],
    unresolved: Mapping[str, list[str]],
    *,
    content_hash: str | None = None,
) -> int:
    """Phase 2 for one file: delete the relationships it owns, create the new ones.

    Only ``src = <path>`` is touched (never ``tool``, ``walker`` or ``git:*``). Also rewrites the
    ``unresolved`` list of every node of the file and, when given, stores the File node's
    ``content_hash`` (only now is the file fully synced). Returns the number created.
    """
    if content_hash is not None:
        tx.run(
            "MATCH (f:File {id: $id}) SET f.content_hash = $hash",
            {"id": f"file:{src}", "hash": content_hash},
        )
    tx.run("MATCH ()-[r {src: $src}]->() DELETE r", {"src": src})
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for rel in rels:
        key = (_rel_type(rel.type), label_of(rel.from_id), label_of(rel.to_id))
        groups[key].append({"f": rel.from_id, "t": rel.to_id, "p": {**rel.props, "src": src}})
    created = 0
    for (type_, from_label, to_label), rows in groups.items():
        out = tx.run(
            f"UNWIND $rows AS row "
            f"MATCH (a:{_label(from_label)} {{id: row.f}}) "
            f"MATCH (b:{_label(to_label)} {{id: row.t}}) "
            f"CREATE (a)-[r:{type_}]->(b) SET r = row.p RETURN count(r) AS n",
            {"rows": rows},
        )
        created += int(out[0]["n"]) if out else 0
    if created != len(rels):
        raise RuntimeError(
            f"{src}: created {created} of {len(rels)} relationships; an endpoint is missing"
        )

    tx.run(
        "MATCH (n) WHERE n.source_path = $src AND n.unresolved IS NOT NULL SET n.unresolved = null",
        {"src": src},
    )
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, strings in unresolved.items():
        if strings:
            by_label[label_of(node_id)].append({"id": node_id, "u": sorted(set(strings))})
    for label, rows in by_label.items():
        tx.run(
            f"UNWIND $rows AS row MATCH (n:{_label(label)} {{id: row.id}}) "
            "SET n.unresolved = row.u",
            {"rows": rows},
        )
    return created


# ---------------------------------------------------------------- removals


def delete_file(tx: Tx, path: str, *, keep_ids: set[str], now: str, initial: bool) -> NodeChanges:
    """Remove a file: its relationships, its File node, and the nodes no other file produces."""
    changes = NodeChanges()
    tx.run("MATCH ()-[r {src: $src}]->() DELETE r", {"src": path})
    rows = tx.run(
        "MATCH (n) WHERE n.source_path = $path "
        "RETURN n.id AS id, labels(n) AS labels, n.claimed_by AS claimed_by",
        {"path": path},
    )
    gone = [r for r in rows if r["id"] not in keep_ids]
    _delete_nodes(tx, gone, changes, now=now, initial=initial)
    tx.run("MATCH (f:File {id: $id}) DETACH DELETE f", {"id": f"file:{path}"})
    return changes


# ---------------------------------------------------------------- events and meta


def add_event(
    tx: Tx,
    *,
    kind: str,
    actor: str,
    target_id: str,
    summary: str,
    data: Mapping[str, Any],
    now: str,
) -> str:
    """Append an Event (SPEC-02 §2) and link it to its target with ``ABOUT {src: 'tool'}``."""
    event_id = f"event:{new_ulid(datetime.fromisoformat(now))}"
    props = encode_props(
        {
            "id": event_id,
            "at": now,
            "kind": kind,
            "actor": actor,
            "target_id": target_id,
            "summary": summary,
            "data": dict(data),
        }
    )
    tx.run("CREATE (e:Event) SET e = $props", {"props": props})
    try:
        target_label = label_of(target_id)
    except ValueError:
        return event_id
    tx.run(
        f"MATCH (e:Event {{id: $e}}) MATCH (t:{_label(target_label)} {{id: $t}}) "
        "CREATE (e)-[:ABOUT {src: 'tool'}]->(t)",
        {"e": event_id, "t": target_id},
    )
    return event_id


def write_meta(
    tx: Tx, *, schema_version: int, project_name: str, last_full_sync: str | None
) -> None:
    """Create or update the Meta node; ``last_git_sha`` and a missing ``last_full_sync`` stay."""
    props: dict[str, Any] = {
        "id": "meta",
        "schema_version": schema_version,
        "project_name": project_name,
    }
    if last_full_sync is not None:
        props["last_full_sync"] = last_full_sync
    tx.run("MERGE (m:Meta {id: 'meta'}) SET m += $props", {"props": props})


# ---------------------------------------------------------------- reading state


def read_file_paths(store: Store | Tx) -> set[str]:
    """The path of every File node (SDD documents and code files)."""
    run = store.run if isinstance(store, Tx) else store.read
    return {row["path"] for row in run("MATCH (f:File) RETURN f.path AS path")}


def read_state(store: Store | Tx) -> GraphState:
    """File hashes, ``Meta.last_full_sync`` and the rows the link catalog is rebuilt from.

    ``store`` may be a write job's :class:`Tx` (write-back re-syncs inside its job, M03a).
    """
    run = store.run if isinstance(store, Tx) else store.read
    files = {
        row["path"]: row["hash"]
        for row in run(
            "MATCH (f:File) WHERE f.content_hash IS NOT NULL "
            "RETURN f.path AS path, f.content_hash AS hash"
        )
    }
    meta = run("MATCH (m:Meta {id: 'meta'}) RETURN m.last_full_sync AS last")
    rows: list[Row] = []
    for label in CATALOG_LABELS:
        rows += run(
            f"MATCH (n:{_label(label)}) RETURN '{label}' AS label, n.id AS id, "
            "n.source_path AS source_path, n.anchor AS anchor, n.title AS title, "
            "n.spec_id AS spec_id, n.path AS path"
        )
    return GraphState(files, meta[0]["last"] if meta else None, rows)
