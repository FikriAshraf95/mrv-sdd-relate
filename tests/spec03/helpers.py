"""Shared helpers for the SPEC-03 tests."""

from __future__ import annotations

from pathlib import Path

from sdd.parse import (
    ParseResult,
    Ref,
    Rel,
    parse_deviation,
    parse_deviation_index,
    parse_doc,
    parse_milestone,
    parse_plan,
    parse_spec,
)
from sdd.parse.links import Found, refs_in_markdown

FIXTURES = Path(__file__).parent.parent / "fixtures"


def found(text: str, path: str = "docs/milestones/M01-x.md") -> list[Found]:
    return refs_in_markdown(text, path=path, line=1)


def refs(text: str, path: str = "docs/milestones/M01-x.md") -> list[Ref]:
    return [r for f in found(text, path) for r in f.refs]


def targets(text: str, path: str = "docs/milestones/M01-x.md") -> list[str]:
    return [r.target for r in refs(text, path)]


def rels(result: ParseResult, type_: str, from_id: str | None = None) -> list[Rel]:
    return [r for r in result.rels if r.type == type_ and (from_id is None or r.from_id == from_id)]


def rel_targets(result: ParseResult, type_: str, from_id: str | None = None) -> list[str]:
    return [r.to.target for r in rels(result, type_, from_id)]


def codes(result: ParseResult) -> list[str]:
    return [w.code for w in result.warnings]


def parse_file(style: str, rel: str) -> ParseResult:
    """Run the right parser for a fixture file by its location and name."""
    text = (FIXTURES / style / rel).read_text(encoding="utf-8")
    name = rel.rsplit("/", 1)[-1]
    if "docs/specs/" in rel:
        return parse_spec(rel, text)
    if "docs/milestones/" in rel:
        if name.endswith("-plan.md"):
            return parse_plan(rel, text)
        return parse_milestone(rel, text)
    if "docs/deviations/" in rel and name.startswith("D") and name[1:4].isdigit():
        return parse_deviation(rel, text)
    if name == "DEVIATIONS.md":
        return parse_deviation_index(rel, text)
    return parse_doc(rel, text)


def parse_style(style: str) -> dict[str, ParseResult]:
    """Every parseable Markdown file of a fixture, keyed by project-relative path."""
    root = FIXTURES / style
    out: dict[str, ParseResult] = {}
    for f in sorted(root.rglob("*.md")):
        rel = f.relative_to(root).as_posix()
        if "docs/deviations/" in rel and not (f.name.startswith("D") and f.name[1:4].isdigit()):
            continue
        out[rel] = parse_file(style, rel)
    return out
