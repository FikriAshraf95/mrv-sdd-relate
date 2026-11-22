"""The context packet and section reads (SPEC-05 §4, tool 6 ``read_section``).

A reference to a section means the section **and its descendants** (SPEC-03 §2.2): ``READS``,
``GOVERNED_BY`` and the references people type name one section, and every reader here expands
it to the subtree. Each descendant is its own item, in document order, so ``amended_by`` stays
per section. Spec text is never cut: truncation drops whole parts and whole sections.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sdd.errors import SddError
from sdd.graph.store import Row, Store
from sdd.parse.links import spec_refs
from sdd.parse.md import id_slug
from sdd.parse.model import Ref
from sdd.service.coordination import agent_name, seen, task_ident
from sdd.service.runtime import Runtime

__all__ = ["DETAILS", "MAX_FILES", "get_context", "read_section"]

DETAILS = ("task", "milestone")
MAX_FILES = 50
MAX_COMMITS = 5
MIN_CHARS, MAX_CHARS = 1000, 1_000_000

GOVERNS = "governs task"
VERIFIES = "verifies checks"
ALWAYS = "always include"
READS = "milestone reads"


# ---------------------------------------------------------------- the section tree


@dataclass(slots=True)
class _Sec:
    id: str
    spec_id: str
    number: str | None
    title: str
    level: int
    line: int
    text: str
    children: list[str] = field(default_factory=list)
    parent: str | None = None


class _Tree:
    """The sections of every spec looked at so far, loaded one spec at a time."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self.secs: dict[str, _Sec] = {}
        self._specs: dict[str, bool] = {}  # spec ID → exists

    def load(self, spec_id: str) -> bool:
        if spec_id in self._specs:
            return self._specs[spec_id]
        exists = bool(
            self._store.read("MATCH (p:Spec {id: $id}) RETURN p.id AS id", {"id": spec_id})
        )
        self._specs[spec_id] = exists
        if not exists:
            return False
        for r in self._store.read(
            "MATCH (s:Section) WHERE s.spec_id = $spec RETURN s.id AS id, s.number AS number, "
            "s.title AS title, s.level AS level, s.line_start AS line, s.text AS text",
            {"spec": spec_id},
        ):
            self.secs[r["id"]] = _Sec(
                r["id"],
                spec_id,
                r["number"],
                str(r["title"] or ""),
                int(r["level"] or 2),
                int(r["line"] or 0),
                str(r["text"] or ""),
            )
        for r in self._store.read(
            "MATCH (a:Section)-[:HAS_SECTION]->(b:Section) WHERE a.spec_id = $spec "
            "RETURN a.id AS a, b.id AS b",
            {"spec": spec_id},
        ):
            if r["a"] in self.secs and r["b"] in self.secs:
                self.secs[r["a"]].children.append(r["b"])
                self.secs[r["b"]].parent = r["a"]
        for sec in self.secs.values():
            sec.children.sort(key=lambda c: self.secs[c].line)
        return True

    def top(self, spec_id: str) -> list[str]:
        """The spec's top-level sections, in document order."""
        self.load(spec_id)
        tops = [s for s in self.secs.values() if s.spec_id == spec_id and s.parent is None]
        return [s.id for s in sorted(tops, key=lambda s: s.line)]

    def subtree(self, sec_id: str) -> list[str]:
        """The section and its descendants, in document order."""
        out = [sec_id]
        for child in self.secs[sec_id].children:
            out.extend(self.subtree(child))
        return out

    def chars(self, sec_id: str) -> int:
        return sum(len(self.secs[s].text) for s in self.subtree(sec_id))

    def target(self, node_id: str) -> list[str]:
        """A READS / GOVERNED_BY target → section roots: a Section itself, a Spec's top level."""
        if "#" in node_id:
            spec = node_id.split("#", 1)[0]
            return [node_id] if self.load(spec) and node_id in self.secs else []
        return self.top(node_id) if self.load(node_id) else []

    def resolve(self, ref: Ref) -> list[str]:
        """One parsed reference → section roots (empty when it names nothing)."""
        spec = ref.target.split("#", 1)[0]
        if not self.load(spec):
            return []
        if ref.kind == "spec":
            return self.top(spec)
        if ref.kind == "section":
            return [ref.target] if ref.target in self.secs else []
        want = id_slug(ref.slug or "")
        return [
            s.id
            for s in sorted(self.secs.values(), key=lambda s: s.line)
            if s.spec_id == spec and id_slug(s.title) == want
        ][:1]


def _amended_by(store: Store, tree: _Tree, ids: Sequence[str]) -> dict[str, list[Row]]:
    """Deviations amending each section, or its whole spec: section ID → deviation rows."""
    specs = sorted({tree.secs[i].spec_id for i in ids})
    rows = store.read(
        "MATCH (d:Deviation)-[:AMENDS]->(x) WHERE x.id IN $ids RETURN x.id AS target, "
        "d.id AS id, d.title AS title, d.status AS status, "
        "d.implementation_does AS implementation_does ORDER BY id",
        {"ids": [*ids, *specs]},
    )
    out: dict[str, list[Row]] = {}
    for sec_id in ids:
        spec = tree.secs[sec_id].spec_id
        out[sec_id] = [r for r in rows if r["target"] in (sec_id, spec)]
    return out


def _section_item(sec: _Sec, amended: list[Row]) -> dict[str, Any]:
    return {
        "id": sec.id,
        "title": sec.title,
        "number": sec.number,
        "level": sec.level,
        "text": sec.text,
        "amended_by": sorted({str(d["id"]) for d in amended}),
    }


# ---------------------------------------------------------------- read_section (tool 6)


def read_section(
    runtime: Runtime, refs: str | Sequence[str], agent: str | None = None
) -> dict[str, Any]:
    """The text of one or more sections by reference (``"SPEC-03 §4.2"``, ``"SPEC-02 §3–4"``,
    ``"SPEC-02 `documents`"``, ``"SPEC-03#4.2"``), each with its descendants."""
    name = agent_name(agent, required=False)
    raw = [refs] if isinstance(refs, str) else list(refs)
    raw = [r.strip() for r in raw if isinstance(r, str) and r.strip()]
    if not raw:
        raise SddError("invalid_input", "refs needs at least one reference, e.g. 'SPEC-03 §4.2'.")
    seen(runtime, name)
    tree = _Tree(runtime.store)
    ordered: list[str] = []
    for text in raw:
        parsed = spec_refs(text)
        found = [tree.resolve(ref) for ref in parsed]
        if not parsed or not all(found):
            raise SddError(
                "unknown_section",
                f"{text!r} names no section in the graph. Use the form 'SPEC-03 §4.2'.",
                details={"ref": text},
            )
        for root in (root for roots in found for root in roots):
            for sec_id in tree.subtree(root):
                if sec_id not in ordered:
                    ordered.append(sec_id)
    amended = _amended_by(runtime.store, tree, ordered)
    sections = []
    for sec_id in ordered:
        sec = tree.secs[sec_id]
        sections.append({**_section_item(sec, amended[sec_id]), "spec_id": sec.spec_id})
    return {"sections": sections, "synced_at": runtime.synced()}


# ---------------------------------------------------------------- get_context (tool 5)


@dataclass(slots=True)
class _Pick:
    root: str
    why: str
    keep: bool  # governing: never dropped by truncation


def get_context(
    runtime: Runtime,
    task_id: str,
    detail: str = "task",
    max_chars: int = 24000,
    agent: str | None = None,
) -> dict[str, Any]:
    """The context packet for one task (SPEC-05 §4)."""
    ident = task_ident(task_id)
    name = agent_name(agent, required=False)
    if detail not in DETAILS:
        raise SddError("invalid_input", "detail must be 'task' or 'milestone'.")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int):
        raise SddError("invalid_input", "max_chars must be an integer.")
    if not MIN_CHARS <= max_chars <= MAX_CHARS:
        raise SddError("invalid_input", f"max_chars must be {MIN_CHARS} to {MAX_CHARS}.")
    store = runtime.store
    rows = store.read(
        "MATCH (t:Task {id: $id}) RETURN t.id AS id, t.title AS title, t.group AS grp, "
        "t.status AS status, t.milestone_id AS milestone_id",
        {"id": ident},
    )
    if not rows:
        raise SddError(
            "task_not_found",
            f"No task {ident}. List claimable tasks with next_tasks.",
            details={"task": ident},
        )
    seen(runtime, name)
    t = rows[0]
    mid = str(t["milestone_id"])
    blocked = store.read(
        "MATCH (t:Task {id: $id})-[:BLOCKED_BY]->(b:Task) RETURN b.id AS id ORDER BY id",
        {"id": ident},
    )
    ms = store.read(
        "MATCH (m:Milestone {id: $id}) RETURN m.id AS id, m.title AS title, m.goal AS goal, "
        "m.acceptance AS acceptance, m.model AS model",
        {"id": mid},
    )
    milestone: dict[str, Any] = (
        dict(ms[0])
        if ms
        else {"id": mid, "title": None, "goal": None, "acceptance": [], "model": None}
    )

    tree = _Tree(store)
    governed = [
        root
        for r in store.read(
            "MATCH (t:Task {id: $id})-[:GOVERNED_BY]->(x) RETURN x.id AS id", {"id": ident}
        )
        for root in tree.target(str(r["id"]))
    ]
    checks = store.read(
        "MATCH (t:Task {id: $id})-[:VERIFIES]->(c:AcceptanceCheck) RETURN c.id AS id, "
        "c.spec_id AS spec_id, c.number AS number, c.text AS text",
        {"id": ident},
    )
    checks.sort(key=lambda c: (str(c["spec_id"]), int(c["number"] or 0)))
    reads: list[str] = []
    for r in store.read(
        "MATCH (m:Milestone {id: $id})-[:READS]->(x) RETURN x.id AS id", {"id": mid}
    ):
        reads.extend(x for x in tree.target(str(r["id"])) if x not in reads)
    reads.sort(key=lambda s: (tree.secs[s].spec_id, tree.secs[s].line))

    picks = [_Pick(root, GOVERNS, True) for root in _sorted(tree, governed)]
    for spec in sorted({str(c["spec_id"]) for c in checks}):
        picks += [_Pick(root, VERIFIES, False) for root in _check_sections(tree, spec)]
    for text in runtime.settings.always_include:
        picks += [
            _Pick(root, ALWAYS, False) for ref in spec_refs(text) for root in tree.resolve(ref)
        ]
    if not governed:
        picks += [_Pick(root, READS, True) for root in reads]
    elif detail == "milestone":
        picks += [_Pick(root, READS, False) for root in reads]

    chosen: dict[str, _Pick] = {}  # section ID → the pick that pulled it in
    for pick in picks:
        for sec_id in tree.subtree(pick.root):
            chosen.setdefault(sec_id, pick)
    outline = [
        {"id": root, "title": tree.secs[root].title, "why": READS, "chars": tree.chars(root)}
        for root in reads
        if root not in chosen
    ]

    packet: dict[str, Any] = {
        "task": {
            "id": ident,
            "title": t["title"],
            "group": t["grp"],
            "status": t["status"],
            "blocked_by": [r["id"] for r in blocked],
        },
        "milestone": milestone,
        "sections": [],
        "outline": outline,
        "checks": [{"id": c["id"], "text": c["text"]} for c in checks],
        "deviations": [],
        "upstream": _upstream(store, ident, mid, [str(r["id"]) for r in blocked]),
        "code": _code(store, tree, ident, governed or reads, list(chosen)),
    }
    order = sorted(chosen, key=lambda s: picks.index(chosen[s]))
    _fill_sections(store, tree, packet, order, chosen)

    truncated = _truncate(store, tree, packet, order, chosen, max_chars=max_chars)

    chars = _size(packet)
    packet["size"] = {"chars": chars, "tokens_est": math.ceil(chars / 4), "truncated": truncated}
    packet["synced_at"] = runtime.synced()
    return packet


def _truncate(
    store: Store,
    tree: _Tree,
    packet: dict[str, Any],
    order: list[str],
    chosen: dict[str, _Pick],
    *,
    max_chars: int,
) -> list[str]:
    """Drop parts until the packet fits: code, upstream, outline, then the longest
    non-governing sections, whole. Returns what was dropped, in order."""
    truncated: list[str] = []
    empty_code: dict[str, list[Any]] = {
        "features": [],
        "files": [],
        "tables": [],
        "recent_commits": [],
    }
    for part, empty in (("code", empty_code), ("upstream", []), ("outline", [])):
        if _size(packet) <= max_chars:
            return truncated
        if packet[part] != empty:
            packet[part] = empty
            truncated.append(part)
    droppable = sorted(
        (s for s in order if not chosen[s].keep),
        key=lambda s: (-len(tree.secs[s].text), tree.secs[s].line),
    )
    for sec_id in droppable:
        if _size(packet) <= max_chars:
            break
        order.remove(sec_id)
        truncated.append(sec_id)
        _fill_sections(store, tree, packet, order, chosen)
    return truncated


def _sorted(tree: _Tree, roots: Iterable[str]) -> list[str]:
    unique = list(dict.fromkeys(roots))
    return sorted(unique, key=lambda s: (tree.secs[s].spec_id, tree.secs[s].line))


def _check_sections(tree: _Tree, spec_id: str) -> list[str]:
    """The section holding a spec's acceptance checks (its title starts 'Acceptance checks')."""
    tree.load(spec_id)
    return [
        s.id
        for s in sorted(tree.secs.values(), key=lambda s: s.line)
        if s.spec_id == spec_id and id_slug(s.title).startswith("acceptance-check")
    ][:1]


def _fill_sections(
    store: Store, tree: _Tree, packet: dict[str, Any], order: list[str], chosen: dict[str, _Pick]
) -> None:
    """(Re)build ``sections`` and ``deviations`` from the sections still in the packet."""
    amended = _amended_by(store, tree, order) if order else {}
    sections = []
    for sec_id in order:
        pick = chosen[sec_id]
        why = pick.why if sec_id == pick.root else f"{pick.why} ({pick.root})"
        item = _section_item(tree.secs[sec_id], amended[sec_id])
        sections.append({**item, "why": why})
    packet["sections"] = sections
    devs: dict[str, dict[str, Any]] = {}
    for sec_id in order:
        for d in amended[sec_id]:
            entry = devs.setdefault(
                str(d["id"]),
                {"id": d["id"], "title": d["title"], "status": d["status"], "amends": []},
            )
            if d["status"] == "open":
                entry["implementation_does"] = d["implementation_does"]
            if d["target"] not in entry["amends"]:
                entry["amends"].append(d["target"])
    packet["deviations"] = [devs[k] for k in sorted(devs)]


def _upstream(store: Store, ident: str, mid: str, blocked_by: list[str]) -> list[dict[str, Any]]:
    """``BLOCKED_BY`` tasks and the milestone's done tasks, with notes and files touched."""
    rows = store.read(
        "MATCH (t:Task) WHERE (t.id IN $blocked OR (t.milestone_id = $mid AND t.status = 'done'))"
        " AND t.id <> $id RETURN t.id AS id, t.title AS title, t.status AS status, "
        "t.notes AS notes, t.milestone_id AS mid, t.order AS ord",
        {"blocked": blocked_by, "mid": mid, "id": ident},
    )
    rows.sort(key=lambda r: (r["mid"] != mid, str(r["mid"]), r["ord"] or 0))
    files: dict[str, list[str]] = {}
    for e in store.read(
        "MATCH (e:Event)-[:ABOUT]->(t:Task) WHERE t.id IN $ids AND e.kind = 'task_completed' "
        "RETURN t.id AS id, e.data_json AS data_json, e.at AS at ORDER BY at",
        {"ids": [r["id"] for r in rows]},
    ):
        data = e.get("data") or {}
        files[str(e["id"])] = list(data.get("files_touched") or [])  # the latest completion
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "notes": r["notes"],
            "files_touched": files.get(str(r["id"]), []),
        }
        for r in rows
    ]


def _code(
    store: Store, tree: _Tree, ident: str, governed: list[str], sections: list[str]
) -> dict[str, Any]:
    """Features of the governing specs (the READS specs when the task governs nothing; they
    stand in for governing sections), their files, tables mentioned by the task or its
    sections, and the latest commits touching those files (filled from M04a/M04b on)."""
    specs = sorted({tree.secs[s].spec_id for s in governed})
    features = store.read(
        "MATCH (f:Feature)-[:SPECIFIED_BY]->(p:Spec) WHERE p.id IN $specs "
        "RETURN DISTINCT f.id AS id, f.slug AS slug ORDER BY slug",
        {"specs": specs},
    )
    feature_ids = [f["id"] for f in features]
    paths = [
        str(r["path"])
        for r in store.read(
            "MATCH (f:Feature)-[:IMPLEMENTED_IN]->(x:File) WHERE f.id IN $ids "
            f"RETURN DISTINCT x.path AS path ORDER BY path LIMIT {MAX_FILES}",
            {"ids": feature_ids},
        )
    ]
    tables = store.read(
        "MATCH (n)-[:MENTIONS]->(t:Table) WHERE n.id IN $ids RETURN DISTINCT t.name AS name "
        "ORDER BY name",
        {"ids": [ident, *sections]},
    )
    # the commits of every file of the features, not just the listed ones
    commits = (
        store.read(
            "MATCH (f:Feature)-[:IMPLEMENTED_IN]->(x:File)<-[:CHANGED]-(c:Commit) "
            "WHERE f.id IN $ids "
            "RETURN DISTINCT c.short AS short, c.message AS message, c.at AS at "
            f"ORDER BY at DESC LIMIT {MAX_COMMITS}",
            {"ids": feature_ids},
        )
        if feature_ids
        else []
    )
    return {
        "features": [f["slug"] for f in features],
        "files": paths,
        "tables": [r["name"] for r in tables],
        "recent_commits": [{"short": c["short"], "message": c["message"]} for c in commits],
    }


def _size(packet: dict[str, Any]) -> int:
    return len(json.dumps(packet, ensure_ascii=False))
