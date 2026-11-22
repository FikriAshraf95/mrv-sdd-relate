"""``impact``, ``explain``, ``find_code`` and the presets (SPEC-06, plan M04b §4–6).

This module holds **no Cypher**: every read is a named query from ``graph/queries/*.cypher``
(``sdd.graph.queries``). The queries return rows ``{id, label, title, status, via}``; the code
here picks them by target kind, prefixes the ``via`` chains, counts hops, deduplicates, groups,
sorts and caps. Results are the same for the MCP tool, the HTTP endpoint and the CLI.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sdd.errors import SddError
from sdd.graph import queries
from sdd.graph.store import Row, Store
from sdd.ids import InvalidIdError, label_of, normalise
from sdd.parse.links import spec_refs
from sdd.parse.md import id_slug
from sdd.service.api_views import shape_node
from sdd.service.coordination import agent_name, seen
from sdd.service.runtime import Runtime

__all__ = [
    "GROUPS",
    "MAX_ITEMS",
    "explain",
    "find_code",
    "impact",
    "preset",
    "presets",
    "resolve_target",
]

MAX_ITEMS = 50
MAX_DEPTH = 5
MAX_COMMITS = 10
GROUPS = (
    "specs",
    "sections",
    "milestones",
    "tables",
    "features",
    "files",
    "tasks_open",
    "tasks_done",
    "deviations",
    "tests",
    "commits",
)
# Relationships that only say "is part of": a chain's hops do not count them (SPEC-06 §1 rule 2).
CONTAINMENT = frozenset({"HAS_SECTION", "HAS_CHECK", "HAS_COLUMN"})
_GROUP_OF_LABEL = {
    "Spec": "specs",
    "Section": "sections",
    "Milestone": "milestones",
    "Table": "tables",
    "Column": "tables",
    "Feature": "features",
    "Domain": "features",
    "File": "files",
    "Deviation": "deviations",
    "AcceptanceCheck": "tests",
    "Commit": "commits",
}

# A traversal step: a named query and the group it forces (``None``: by the item's label).
Step = tuple[str, str | None]
TABLE_STEPS: list[Step] = [
    ("impact.table.columns", None),
    ("impact.table.dependents", None),
    ("impact.table.defining_section", None),
    ("impact.table.defining_spec", None),
    ("impact.table.deviations_affects", None),  # before mentions: AFFECTS wins a one-hop tie
    ("impact.table.mentions", None),
    ("impact.table.linking_sections", None),
    ("impact.table.features", None),
    ("impact.table.feature_files", None),
    ("impact.table.feature_specs", None),
    ("impact.table.tasks_by_defining_section", None),
    ("impact.table.tasks_by_mentioning_section", None),
    ("impact.table.deviations_amending_defining", None),
    ("impact.table.deviations_amending_mentioning", None),
    ("impact.table.checks", None),
    ("impact.table.test_files", "tests"),
]
COLUMN_STEPS: list[Step] = [
    ("impact.column.table", None),
    ("impact.column.references", None),
    ("impact.column.same_target", None),
]
SPEC_STEPS: list[Step] = [
    ("impact.spec.sections", None),
    ("impact.spec.milestones", None),
    ("impact.spec.tasks", None),
    ("impact.spec.deviations", None),
    ("impact.spec.linking", None),
    ("impact.spec.checks", None),
    ("impact.spec.features", None),
    ("impact.spec.feature_files", None),
    ("impact.spec.test_files", "tests"),
]
# Run once for every section of a spec (``$ids``); the spec-level steps above cover the rest.
SECTION_OF_SPEC_STEPS: list[Step] = [
    ("impact.section.children", None),
    ("impact.section.linking", None),
    ("impact.section.milestones", None),
    ("impact.section.tasks", None),
    ("impact.section.deviations", None),
    ("impact.section.defined_tables", None),
    ("impact.section.mentioned_tables", None),
    ("impact.section.mentioned_files", None),
]
SECTION_STEPS: list[Step] = [
    *SECTION_OF_SPEC_STEPS,
    ("impact.section.features", None),
    ("impact.section.feature_files", None),
    ("impact.section.checks", None),
    ("impact.section.test_files", "tests"),
]
FILE_STEPS: list[Step] = [
    ("impact.file.features", None),
    ("impact.file.feature_specs", None),
    ("impact.file.deviations_affects", None),  # before mentions: AFFECTS wins a one-hop tie
    ("impact.file.mentions", None),
    ("impact.file.touching_tasks", None),
    ("impact.file.commits", None),
    ("impact.file.commit_tasks", None),
    ("impact.file.deviations_amending_sections", None),
    ("impact.file.deviations_amending_specs", None),
    ("impact.file.checks", None),
]
FEATURE_STEPS: list[Step] = [
    ("impact.feature.files", None),
    ("impact.feature.tables", None),
    ("impact.feature.specs", None),
    ("impact.feature.domain", None),
]
TASK_STEPS: list[Step] = [
    ("impact.task.milestone", None),
    ("impact.task.governing", None),
    ("impact.task.blocked_by", None),
    ("impact.task.blocking", None),
    ("impact.task.touches", None),
    ("impact.task.commits", None),
    ("impact.task.deviations", None),
]
MILESTONE_STEPS: list[Step] = [
    ("impact.milestone.tasks", None),
    ("impact.milestone.reads", None),
    ("impact.milestone.depends_on", None),
    ("impact.milestone.depended_on", None),
    ("impact.milestone.deviations", None),
    ("impact.milestone.commits", None),
]
SIMPLE_STEPS: dict[str, list[Step]] = {
    "Domain": [("impact.domain.features", None)],
    "Deviation": [
        ("impact.deviation.amends", None),
        ("impact.deviation.affects", None),
        ("impact.deviation.raised_in", None),
    ],
    "Task": TASK_STEPS,
    "Milestone": MILESTONE_STEPS,
    "File": FILE_STEPS,
}
# Every query name this module uses (a test checks that `queries.load()` has all of them).
QUERY_NAMES = frozenset(
    name
    for steps in (
        TABLE_STEPS,
        COLUMN_STEPS,
        SPEC_STEPS,
        SECTION_STEPS,
        FILE_STEPS,
        FEATURE_STEPS,
        TASK_STEPS,
        MILESTONE_STEPS,
        *SIMPLE_STEPS.values(),
    )
    for name, _ in steps
)


def hops(via: Sequence[str]) -> int:
    """Relationships in a ``via`` chain that are not containment (``~PATH`` counts as one)."""
    return sum(1 for step in via[1::2] if step[2:] not in CONTAINMENT)


def _spec_of(section_id: str) -> str:
    return section_id.split("#", 1)[0]


# ---------------------------------------------------------------- target resolution


def _ids(rows: Iterable[Row]) -> list[str]:
    return [str(r["id"]) for r in rows]


def _node(store: Store, ident: str) -> Row | None:
    rows = queries.run(store, "resolve.node", id=ident)
    return rows[0] if rows else None


def resolve_target(store: Store, raw: str) -> tuple[str, str]:
    """A target as typed → ``(canonical ID, label)`` (SPEC-06 §2).

    Unambiguous forms (spec reference, task or milestone ID, prefixed ID) resolve by format; a
    bare name is looked up in every kind at once and must match exactly one node, else
    ``ambiguous_target`` (candidates in ``details``) or ``node_not_found``.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise SddError("invalid_input", "target must be a non-empty string.")
    text = raw.strip()
    try:
        ident = normalise(text)
    except InvalidIdError:
        refs = spec_refs(text) if text.upper().startswith("SPEC") else []
        if len(refs) != 1:
            return _bare(store, text)
        ident = (refs[0].slug and f"{refs[0].target}#{id_slug(refs[0].slug)}") or refs[0].target
    row = _node(store, ident)
    if row is None and "#" in ident:  # `SPEC-02 documents`: a section named by its title slug
        spec, _, part = ident.partition("#")
        slugs = {
            str(r["id"]): id_slug(str(r["title"]))
            for r in queries.run(store, "resolve.spec_section_titles", spec=spec)
        }
        hit = [i for i, s in slugs.items() if s == part]
        if len(hit) == 1:
            row = _node(store, hit[0])
    if row is None:
        raise SddError("node_not_found", f"No node {ident}.", details={"id": ident})
    return str(row["id"]), str(row["label"])


def _bare(store: Store, text: str) -> tuple[str, str]:
    path = text.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    slug = id_slug(text)
    found: set[str] = set()
    found.update(_ids(queries.run(store, "resolve.table_by_name", name=text)))
    if "." in text:
        table, _, col = text.partition(".")
        found.update(
            _ids(queries.run(store, "resolve.column_by_table_and_name", table=table, name=col))
        )
    found.update(_ids(queries.run(store, "resolve.file_by_path", path=path)))
    found.update(
        _ids(queries.run(store, "resolve.features_by_name", slug=slug.replace("_", "-"), name=text))
    )
    found.update(_ids(queries.run(store, "resolve.columns_by_name", name=text)))
    found.update(
        str(r["id"])
        for r in queries.run(store, "resolve.section_titles")
        if id_slug(str(r["title"])) == slug
    )
    if not found:
        raise SddError("node_not_found", f"No node named {text!r}.", details={"target": text})
    if len(found) > 1:
        candidates = sorted(found)
        raise SddError(
            "ambiguous_target",
            f"{text!r} names {len(candidates)} nodes: repeat with one of {', '.join(candidates)}.",
            details={"target": text, "candidates": candidates},
        )
    (ident,) = found
    return ident, label_of(ident)


# ---------------------------------------------------------------- impact


@dataclass(slots=True)
class _Item:
    id: str
    label: str
    title: str
    status: str | None
    via: list[str]
    group: str
    hops: int


def _group(label: str, status: str | None, forced: str | None) -> str | None:
    if forced is not None:
        return forced
    if label == "Task":
        return "tasks_done" if status == "done" else "tasks_open"
    return _GROUP_OF_LABEL.get(label)


class _Walk:
    """Collects the items of one ``impact`` call: shortest chain per node, depth-bounded."""

    def __init__(self, store: Store, target: str, depth: int) -> None:
        self.store = store
        self.target = target
        self.depth = depth
        self.items: dict[str, _Item] = {}

    def run(
        self,
        steps: Sequence[Step],
        *,
        prefix: Sequence[str] = (),
        **params: object,
    ) -> list[Row]:
        """Run each step, record its rows (chains prefixed) and return every row."""
        rows: list[Row] = []
        for name, forced in steps:
            for row in queries.run(self.store, name, **params):
                rows.append(row)
                self._add(row, prefix, forced)
        return rows

    def _add(self, row: Row, prefix: Sequence[str], forced: str | None) -> None:
        ident = str(row["id"])
        if ident == self.target:
            return
        label = str(row["label"])
        status = row.get("status")
        group = _group(label, status if isinstance(status, str) else None, forced)
        if group is None:
            return
        via = [*prefix, *(str(v) for v in row["via"])]
        n = hops(via)
        if n > self.depth:
            return
        old = self.items.get(ident)
        if old is not None and old.hops <= n:
            return
        self.items[ident] = _Item(
            ident,
            label,
            str(row["title"]),
            status if isinstance(status, str) else None,
            via,
            group,
            n,
        )

    # ---- one traversal per target kind

    def table(self, table_id: str, prefix: Sequence[str] = ()) -> None:
        self.run(TABLE_STEPS, prefix=prefix, id=table_id)

    def spec(self, spec_id: str, prefix: Sequence[str] = ()) -> None:
        rows = self.run(SPEC_STEPS, prefix=prefix, id=spec_id)
        sections = [str(r["id"]) for r in rows if r["label"] == "Section" and "#" in str(r["id"])]
        sections = [s for s in sections if _spec_of(s) == spec_id]
        if sections:
            self.run(
                SECTION_OF_SPEC_STEPS,
                prefix=[*prefix, spec_id, "->HAS_SECTION"],
                ids=sorted(set(sections)),
            )

    def feature(self, feature_id: str) -> None:
        rows = self.run(FEATURE_STEPS, id=feature_id)
        for row in rows:
            if row["label"] == "Spec":
                self.spec(str(row["id"]), prefix=[feature_id, "->SPECIFIED_BY"])


def impact(
    runtime: Runtime, target: str, depth: int = 3, agent: str | None = None
) -> dict[str, Any]:
    """What else is affected if ``target`` changes (SPEC-06 §2)."""
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= MAX_DEPTH:
        raise SddError("invalid_input", f"depth must be an integer from 1 to {MAX_DEPTH}.")
    name = agent_name(agent, required=False)
    store = runtime.store
    ident, label = resolve_target(store, target)
    seen(runtime, name)
    walk = _Walk(store, ident, depth)
    if label == "Column":
        rows = walk.run(COLUMN_STEPS, id=ident)
        table = next((str(r["id"]) for r in rows if list(r["via"])[1:2] == ["<-HAS_COLUMN"]), None)
        if table is not None:
            walk.table(table, prefix=[ident, "<-HAS_COLUMN"])
    elif label == "Table":
        walk.table(ident)
    elif label == "Spec":
        walk.spec(ident)
    elif label == "Section":
        walk.run(SECTION_STEPS, ids=[ident])
    elif label == "Feature":
        walk.feature(ident)
    else:
        walk.run(SIMPLE_STEPS.get(label, []), id=ident)
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
    counts: dict[str, int] = {}
    by_group: dict[str, list[_Item]] = {g: [] for g in GROUPS}
    for item in walk.items.values():
        by_group[item.group].append(item)
    for group in GROUPS:
        ordered = sorted(by_group[group], key=lambda i: (i.hops, i.id))
        counts[group] = len(ordered)
        groups[group] = [_shape_item(i) for i in ordered[:MAX_ITEMS]]
    node = _node(store, ident)
    return {
        "target": {
            "id": ident,
            "label": label,
            "title": str(node["title"]) if node else ident,
        },
        "groups": groups,
        "counts": counts,
        "synced_at": runtime.synced(),
    }


def _shape_item(item: _Item) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item.id,
        "label": item.label,
        "title": item.title,
        "via": item.via,
    }
    if item.group in ("tasks_open", "tasks_done", "deviations"):
        out["status"] = item.status
    return out


# ---------------------------------------------------------------- explain


def _find_file(store: Store, raw: str) -> str:
    """A path as typed → ``file:<path>``: exact, else the one file whose path ends with it."""
    if not isinstance(raw, str) or not raw.strip():
        raise SddError("invalid_input", "path must be a non-empty string.")
    path = raw.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    exact = _ids(queries.run(store, "resolve.file_by_path", path=path))
    if exact:
        return exact[0]
    tail = _ids(queries.run(store, "resolve.files_by_suffix", suffix="/" + path))
    if len(tail) > 1:
        candidates = sorted(tail)
        raise SddError(
            "ambiguous_target",
            f"{path!r} ends {len(candidates)} paths: repeat with one of {', '.join(candidates)}.",
            details={"path": path, "candidates": candidates},
        )
    if not tail:
        raise SddError("file_not_found", f"No file {path!r} in the graph.", details={"path": path})
    return tail[0]


def _built_by(via: Sequence[str]) -> bool:
    return any(step in ("<-TOUCHES", "->COMPLETES") for step in via[1::2])


def explain(runtime: Runtime, path: str, agent: str | None = None) -> dict[str, Any]:
    """Why this file exists and what shaped it (SPEC-06 §3)."""
    name = agent_name(agent, required=False)
    store = runtime.store
    file_id = _find_file(store, path)
    seen(runtime, name)
    info = queries.run(store, "explain.file", id=file_id)[0]
    walk = _Walk(store, file_id, MAX_DEPTH)
    walk.run(FILE_STEPS, id=file_id)
    by_label: dict[str, list[_Item]] = {}
    for item in walk.items.values():
        by_label.setdefault(item.label, []).append(item)

    def of(label: str) -> list[_Item]:
        return sorted(by_label.get(label, []), key=lambda i: (i.hops, i.id))

    features = _explain_features(store, of("Feature"))
    sections = [{"id": i.id, "title": i.title, "via": i.via} for i in of("Section")]
    tasks = _explain_tasks(store, of("Task"))
    commits = _explain_commits(store, of("Commit"))
    deviations = [
        {"id": i.id, "title": i.title, "status": i.status, "via": i.via}
        for i in sorted(of("Deviation"), key=lambda i: (i.status != "open", i.hops, i.id))
    ]
    checks = _explain_checks(store, of("AcceptanceCheck"))
    result: dict[str, Any] = {
        "file": {
            "id": file_id,
            "path": info["path"],
            "language": info["language"],
            "is_test": bool(info["is_test"]),
        },
        "features": features,
        "sections": sections,
        "tasks": tasks,
        "commits": commits,
        "deviations": deviations,
        "checks": checks,
    }
    result["summary"] = _summary(str(info["path"]), result)
    result["synced_at"] = runtime.synced()
    return result


def _explain_features(store: Store, items: list[_Item]) -> list[dict[str, Any]]:
    if not items:
        return []
    ids = [i.id for i in items]
    details = {str(r["id"]): r for r in queries.run(store, "explain.features", ids=ids)}
    specs: dict[str, list[str]] = {}
    for r in queries.run(store, "explain.feature_specs", ids=ids):
        specs.setdefault(str(r["feature"]), []).append(str(r["spec"]))
    return [
        {
            "id": i.id,
            "name": i.title,
            "domain": details.get(i.id, {}).get("domain"),
            "specs": sorted(specs.get(i.id, [])),
            "via": i.via,
        }
        for i in items
    ]


def _explain_tasks(store: Store, items: list[_Item]) -> list[dict[str, Any]]:
    if not items:
        return []
    details = {
        str(r["id"]): r for r in queries.run(store, "explain.tasks", ids=[i.id for i in items])
    }
    return [
        {
            "id": i.id,
            "title": i.title,
            "status": i.status,
            "milestone": details.get(i.id, {}).get("milestone"),
            "notes": details.get(i.id, {}).get("notes"),
            "via": i.via,
        }
        for i in items
    ]


def _explain_commits(store: Store, items: list[_Item]) -> list[dict[str, Any]]:
    if not items:
        return []
    rows = queries.run(store, "explain.commits", ids=[i.id for i in items])
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by_id.setdefault(
            str(r["id"]),
            {
                "sha": r["sha"],
                "short": r["short"],
                "message": r["message"],
                "at": r["at"],
                "tasks": [],
            },
        )
        if r["task"] and r["task"] not in entry["tasks"]:
            entry["tasks"].append(r["task"])
    out = []
    for i in items:
        if i.id in by_id:
            out.append({**by_id[i.id], "tasks": sorted(by_id[i.id]["tasks"]), "via": i.via})
    out.sort(key=lambda c: str(c["at"]), reverse=True)
    return out[:MAX_COMMITS]


def _explain_checks(store: Store, items: list[_Item]) -> list[dict[str, Any]]:
    if not items:
        return []
    details = {
        str(r["id"]): r for r in queries.run(store, "explain.checks", ids=[i.id for i in items])
    }
    return [
        {
            "id": i.id,
            "spec_id": details.get(i.id, {}).get("spec_id"),
            "text": details.get(i.id, {}).get("text"),
            "via": i.via,
        }
        for i in items
    ]


def _join(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _summary(path: str, result: dict[str, Any]) -> str:
    """A short paragraph from a template; empty parts are skipped (SPEC-06 §3)."""
    features, tasks = result["features"], result["tasks"]
    commits, deviations = result["commits"], result["deviations"]
    sections, checks = result["sections"], result["checks"]
    if not (features or tasks or commits or deviations or sections or checks):
        return (
            f"{path} has no recorded connections: no feature, spec, task, commit, deviation "
            "or check names it (orphan code)."
        )
    parts: list[str] = []
    if features:
        names = [
            f"feature {f['name']}" + (f" ({f['domain']})" if f["domain"] else "") for f in features
        ]
        sentence = f"{path} implements {_join(names)}"
        specs = sorted({s for f in features for s in f["specs"]})
        if specs:
            sentence += f", specified by {_join(specs)}"
        parts.append(sentence + ".")
    built = [t["id"] for t in tasks if _built_by(t["via"])]
    mentioned = [t["id"] for t in tasks if not _built_by(t["via"])]
    shorts = [str(c["short"]) for c in ([c for c in commits if c["tasks"]] or commits)[:3]]
    if built:
        sentence = f"Built by {_join(built)}"
        if shorts:
            sentence += f" (commits {', '.join(shorts)})"
        parts.append(sentence + ".")
    elif shorts:
        parts.append(f"Changed in commits {', '.join(shorts)}.")
    if mentioned:
        parts.append(f"Mentioned by {_join(mentioned)}.")
    if sections:
        parts.append(f"Named in {_join([s['id'] for s in sections])}.")
    if deviations:
        shaped = [f"{d['id']} ({d['status']}): {d['title']}" for d in deviations]
        parts.append(f"Shaped by {'; '.join(shaped)}.")
    if checks:
        parts.append(f"Tests {', '.join(c['id'] for c in checks)}.")
    if not features:
        parts.insert(0, f"{path} is not part of any feature.")
    return " ".join(parts)


# ---------------------------------------------------------------- find_code


def _one(rows: list[Row], what: str, raw: str) -> str:
    ids = _ids(rows)
    if not ids:
        raise SddError("node_not_found", f"No {what} {raw!r}.", details={what: raw})
    if len(ids) > 1:
        raise SddError(
            "ambiguous_target",
            f"{raw!r} names {len(ids)} {what}s: repeat with one of {', '.join(sorted(ids))}.",
            details={what: raw, "candidates": sorted(ids)},
        )
    return ids[0]


def _named(store: Store, prefix: str, what: str, lookup: str, raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith(prefix + ":"):
        rows = queries.run(store, "resolve.node", id=normalise(text))
        return _one(rows, what, raw)
    return _one(
        queries.run(store, lookup, slug=id_slug(text).replace("_", "-"), name=text), what, raw
    )


def find_code(
    runtime: Runtime,
    *,
    feature: str | None = None,
    domain: str | None = None,
    table: str | None = None,
    spec: str | None = None,
    text: str | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    """Files by feature, domain, table, spec or path text; several arguments intersect."""
    given = {k: v for k, v in (("feature", feature), ("domain", domain), ("table", table)) if v} | {
        k: v for k, v in (("spec", spec), ("text", text)) if v
    }
    if not given:
        raise SddError(
            "invalid_input", "give at least one of feature, domain, table, spec or text."
        )
    name = agent_name(agent, required=False)
    store = runtime.store
    routes: list[dict[str, Row]] = []
    try:
        if feature:
            fid = _named(store, "feature", "feature", "resolve.features_by_name", feature)
            routes.append(_by_path(queries.run(store, "find.feature", id=fid)))
        if domain:
            did = _named(store, "domain", "domain", "resolve.domains_by_name", domain)
            routes.append(_by_path(queries.run(store, "find.domain", id=did)))
        if table:
            tid = _table(store, table)
            rows: list[Row] = []
            for q in ("find.table.features", "find.table.mentions", "find.table.affects"):
                rows += queries.run(store, q, id=tid)
            rows += queries.run(store, "find.table.paths", id=tid)
            routes.append(_by_path(rows))
        if spec:
            sid = normalise(spec).split("#", 1)[0]
            if not _one_exists(store, sid):
                raise SddError("node_not_found", f"No spec {sid}.", details={"id": sid})
            rows = queries.run(store, "find.spec.features", id=sid)
            rows += queries.run(store, "find.spec.mentions", id=sid)
            routes.append(_by_path(rows))
    except InvalidIdError as exc:
        raise SddError("invalid_input", str(exc)) from None
    if text:
        routes.append(_by_path(queries.run(store, "find.text", text=text)))
    seen(runtime, name)
    paths = set(routes[0])
    for route in routes[1:]:
        paths &= set(route)
    files = [
        {
            "path": p,
            "language": routes[0][p]["language"],
            "via": [str(v) for v in routes[0][p]["via"]],
        }
        for p in sorted(paths)
    ]
    return {
        "files": files[:MAX_ITEMS],
        "counts": {"files": len(files)},
        "synced_at": runtime.synced(),
    }


def _by_path(rows: Iterable[Row]) -> dict[str, Row]:
    """The first route to each file, by path."""
    out: dict[str, Row] = {}
    for r in rows:
        out.setdefault(str(r["path"]), r)
    return out


def _one_exists(store: Store, ident: str) -> bool:
    return bool(queries.run(store, "resolve.node", id=ident))


def _table(store: Store, raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith("table:"):
        ident = normalise(text)
        if not _one_exists(store, ident):
            raise SddError("node_not_found", f"No table {raw!r}.", details={"table": raw})
        return ident
    return _one(queries.run(store, "resolve.table_by_name", name=text), "table", raw)


# ---------------------------------------------------------------- presets

PRESETS: list[dict[str, Any]] = [
    {
        "name": "schema",
        "params": [],
        "description": "Labels and relationship types with counts (the meta-graph).",
    },
    {
        "name": "milestone:<id>",
        "params": ["id"],
        "description": "The milestone, its tasks, READS sections and deviations raised in it.",
    },
    {
        "name": "impact:<target>",
        "params": ["target"],
        "description": "The impact result for a target as a graph.",
    },
    {
        "name": "explain:<path>",
        "params": ["path"],
        "description": "The explain result for a file as a graph.",
    },
    {
        "name": "lineage:<section>",
        "params": ["section"],
        "description": "Deviations amending the section, the tasks they were raised in and "
        "the files those tasks touched.",
    },
    {
        "name": "feature:<slug>",
        "params": ["slug"],
        "description": "A feature with its specs, files and tables.",
    },
]


def presets() -> list[dict[str, Any]]:
    """The preset list: ``[{name, params, description}]`` (SPEC-06 §5)."""
    return [dict(p) for p in PRESETS]


def _edges_of(via: Sequence[str]) -> list[tuple[str, str, str]]:
    """``(source, type, target)`` for every relationship step of a chain."""
    out = []
    for i in range(1, len(via) - 1, 2):
        step = via[i]
        a, b = via[i - 1], via[i + 1]
        if step.startswith("->"):
            out.append((a, step[2:], b))
        elif step.startswith("<-"):
            out.append((b, step[2:], a))
    return out


def _chain_graph(
    store: Store, vias: Iterable[Sequence[str]], extra: Iterable[str] = ()
) -> dict[str, Any]:
    """``{nodes, edges}`` from via chains (the ``/api/graph`` shape); unknown nodes are dropped."""
    ids: set[str] = set(extra)
    edges: set[tuple[str, str, str]] = set()
    for via in vias:
        ids.update(via[0::2])
        edges.update(_edges_of(via))
    nodes: dict[str, dict[str, Any]] = {}
    ordered = sorted(ids)
    for start in range(0, len(ordered), 500):
        for row in queries.run(store, "presets.nodes", ids=ordered[start : start + 500]):
            node = shape_node(str(row["label"]), row["p"])
            nodes[node["id"]] = node
    return {
        "nodes": [nodes[i] for i in sorted(nodes)],
        "edges": [
            {"source": s, "target": t, "type": ty}
            for s, ty, t in sorted(edges)
            if s in nodes and t in nodes
        ],
    }


def preset(runtime: Runtime, name: str) -> dict[str, Any]:
    """One preset as a graph ``{nodes: [{id, label, title, props}], edges}`` (SPEC-06 §5)."""
    store = runtime.store
    kind, _, arg = (name or "").partition(":")
    arg = arg.strip()
    if kind == "schema" and not arg:
        return _schema_graph(store)
    if not arg or kind not in ("milestone", "impact", "explain", "lineage", "feature"):
        raise SddError("node_not_found", f"No preset {name!r}.", details={"preset": name})
    if kind == "impact":
        result = impact(runtime, arg)
        vias = [i["via"] for items in result["groups"].values() for i in items]
        return _chain_graph(store, vias, [result["target"]["id"]])
    if kind == "explain":
        result = explain(runtime, arg)
        vias = [
            item["via"]
            for key in ("features", "sections", "tasks", "commits", "deviations", "checks")
            for item in result[key]
        ]
        vias += [[f["id"], "->SPECIFIED_BY", s] for f in result["features"] for s in f["specs"]]
        return _chain_graph(store, vias, [result["file"]["id"]])
    if kind == "milestone":
        ident, label = resolve_target(store, arg)
        if label != "Milestone":
            raise SddError("node_not_found", f"{arg!r} is not a milestone.", details={"id": ident})
        walk = _Walk(store, ident, 1)
        walk.run(MILESTONE_STEPS, id=ident)
        return _chain_graph(store, [i.via for i in walk.items.values()], [ident])
    if kind == "feature":
        fid = _named(store, "feature", "feature", "resolve.features_by_name", arg)
        walk = _Walk(store, fid, 1)
        walk.run(FEATURE_STEPS[:3], id=fid)
        return _chain_graph(store, [i.via for i in walk.items.values()], [fid])
    ident, label = resolve_target(store, arg)  # lineage
    if label != "Section":
        raise SddError("node_not_found", f"{arg!r} is not a section.", details={"id": ident})
    vias = [
        [str(v) for v in r["via"]]
        for q in (
            "presets.lineage.deviations",
            "presets.lineage.raised_in",
            "presets.lineage.touched",
        )
        for r in queries.run(store, q, id=ident)
    ]
    return _chain_graph(store, vias, [ident])


def _schema_graph(store: Store) -> dict[str, Any]:
    counts = {str(r["label"]): int(r["count"]) for r in queries.run(store, "presets.schema_nodes")}
    nodes = [
        {"id": label, "label": "Label", "title": f"{label} ({n})", "props": {"count": n}}
        for label, n in sorted(counts.items())
    ]
    edges = [
        {
            "source": str(r["from_label"]),
            "target": str(r["to_label"]),
            "type": str(r["type"]),
            "count": int(r["count"]),
        }
        for r in sorted(
            queries.run(store, "presets.schema_edges"),
            key=lambda r: (str(r["from_label"]), str(r["type"]), str(r["to_label"])),
        )
    ]
    return {"nodes": nodes, "edges": edges}
