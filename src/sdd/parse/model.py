"""Parsed objects shared by every parser (SPEC-03, plan M01a §2).

Generic on purpose: ``graph/`` may not import ``parse/``, so nodes and relationships are plain
data (label, ID, dict of properties) that ``sync/`` hands to ``graph/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "WARNING_CODES",
    "FeatureLine",
    "IndexRow",
    "Node",
    "ParseResult",
    "ParseWarning",
    "Ref",
    "RefKind",
    "Rel",
    "Severity",
    "add_rel",
    "rel_props",
    "warn",
]

Severity = Literal["info", "warning", "error"]
RefKind = Literal["id", "section", "slug", "spec", "path", "doc", "mention"]

# SPEC-03 §1 warning-code table: the only place codes and severities are defined.
WARNING_CODES: dict[str, Severity] = {
    "bad_filename": "error",
    "task_duplicate_id": "error",
    "missing_h1": "warning",
    "h1_id_mismatch": "warning",
    "task_id_mismatch": "warning",
    "task_unstable_id": "warning",
    "task_bad_after": "warning",
    "ref_bad_range": "warning",
    "ac_duplicate_number": "warning",
    "feature_bad_line": "warning",
    "deviation_missing_section": "warning",
    "deviation_bad_field": "warning",
    "deviation_index_mismatch": "warning",
    "duplicate_id": "warning",
    "section_duplicate_id": "info",
    "link_moved": "info",
}


@dataclass(frozen=True, slots=True)
class ParseWarning:
    path: str
    line: int
    code: str
    message: str
    severity: Severity = "warning"


def warn(path: str, line: int, code: str, message: str) -> ParseWarning:
    """Build a warning; the severity comes from :data:`WARNING_CODES` (a typo raises KeyError)."""
    return ParseWarning(path, line, code, message, WARNING_CODES[code])


@dataclass(frozen=True, slots=True)
class Ref:
    """An unresolved relationship target, resolved later against the graph or a Catalog.

    ``target`` by kind: ``id`` any canonical ID; ``section`` ``SPEC-02#3``; ``slug`` the spec ID
    (the slug is in ``slug``); ``spec`` ``SPEC-03``; ``path`` the resolved project-relative path;
    ``doc`` the doc stem (``design-system``); ``mention`` the raw backticked identifier.
    """

    kind: RefKind
    target: str
    line: int
    anchor: str | None = None
    slug: str | None = None
    whole: bool = False
    note: str | None = None
    text: str = ""


@dataclass(frozen=True, slots=True)
class Node:
    label: str
    id: str
    props: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Rel:
    """A relationship. ``from_id`` may name a node in another file (AMENDS from a deviation).

    ``src`` is not set here: ``sync/`` uses the file's path.
    """

    type: str
    from_id: str
    to: Ref
    props: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FeatureLine:
    line: int
    raw: str
    name: str
    slug: str
    domain: str | None
    domain_slug: str | None
    implements: tuple[str, ...]
    tables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IndexRow:
    line: int
    id: str
    link_path: str | None
    title: str
    milestone: str
    spec: str
    status: str


@dataclass(slots=True)
class ParseResult:
    path: str
    nodes: list[Node] = field(default_factory=list)
    rels: list[Rel] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)
    features: list[FeatureLine] = field(default_factory=list)
    index_rows: list[IndexRow] = field(default_factory=list)


def rel_props(ref: Ref) -> dict[str, Any]:
    """The relationship properties a Ref carries (``note``, ``whole``)."""
    props: dict[str, Any] = {}
    if ref.note:
        props["note"] = ref.note
    if ref.whole:
        props["whole"] = True
    return props


def add_rel(rels: list[Rel], seen: set[tuple[object, ...]], rel: Rel) -> None:
    """Append ``rel`` unless an identical one (type, source, target, note) is already there."""
    r = rel.to
    key = (rel.type, rel.from_id, r.kind, r.target, r.anchor, r.slug, r.whole, r.note)
    if key not in seen:
        seen.add(key)
        rels.append(rel)
