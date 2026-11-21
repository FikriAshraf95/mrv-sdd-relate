"""Docs and plans (SPEC-03 §5.3, plan M01a §7)."""

from __future__ import annotations

import posixpath

from sdd.ids import id_from_filename
from sdd.parse.links import refs_in_inline
from sdd.parse.md import content_hash, heading_text, nl, tokens
from sdd.parse.model import Node, ParseResult, Ref, Rel, add_rel, rel_props, warn

__all__ = ["parse_doc", "parse_plan"]

_KINDS = {
    "CLAUDE.md": "claude_md",
    "IDEA.md": "idea",
    "design-system.md": "design_system",
    "HANDOFF.md": "handoff",
    "README.md": "readme",
}


def _parse(path: str, text: str, kind: str) -> ParseResult:
    result = ParseResult(path)
    toks = tokens(nl(text))
    doc_id = f"doc:{path}"
    name = posixpath.basename(path)
    title = name
    for i, t in enumerate(toks):
        if t.type == "heading_open" and t.tag == "h1" and t.level == 0:
            title = heading_text(toks[i + 1]) or name
            break
    result.nodes.append(
        Node(
            "Doc",
            doc_id,
            {
                "kind": kind,
                "title": title,
                "path": path,
                "source_path": path,
                "source_line": 1,
                "content_hash": content_hash(text),
            },
        )
    )
    seen: set[tuple[object, ...]] = set()
    for t in toks:
        if t.type != "inline":
            continue
        for found in refs_in_inline(t.children, path=path, line=(t.map or [0])[0] + 1):
            result.warnings.extend(found.warnings)
            for ref in found.refs:
                add_rel(result.rels, seen, Rel("LINKS_TO", doc_id, ref, rel_props(ref)))
    return result


def parse_doc(path: str, text: str) -> ParseResult:
    """A CLAUDE.md, IDEA, design system, HANDOFF or README: a Doc whose links are LINKS_TO."""
    return _parse(path, text, _KINDS.get(posixpath.basename(path), "other"))


def parse_plan(path: str, text: str) -> ParseResult:
    """A ``M20f-plan.md``: a Doc with ``kind = plan`` and ``PLANS`` to its milestone."""
    result = _parse(path, text, "plan")
    ms = id_from_filename(posixpath.basename(path))
    if ms and ms.startswith("M"):
        result.rels.append(Rel("PLANS", f"doc:{path}", Ref("id", ms, 1)))
    else:
        result.warnings.append(warn(path, 1, "bad_filename", "plan file name has no M<nn> ID"))
    return result
