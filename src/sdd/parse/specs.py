"""Spec files (SPEC-03 §3, plan M01a §5): header, sections, acceptance checks, notes."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from markdown_it.token import Token

from sdd.ids import id_from_filename, normalise
from sdd.parse.links import (
    Found,
    backticked,
    deviation_ids,
    has_deviation_marker,
    refs_in_inline,
)
from sdd.parse.md import (
    content_hash,
    github_slug,
    header_pairs,
    heading_text,
    id_slug,
    nl,
    split_number,
    tokens,
)
from sdd.parse.model import FeatureLine, Node, ParseResult, Ref, Rel, add_rel, rel_props, warn

__all__ = ["parse_spec"]

_H1_RE = re.compile(r"^(?P<id>SPEC-\d+)\s*[—–-]\s*(?P<title>.+)$", re.IGNORECASE)
_ITEM_MARKER_RE = re.compile(r"^(\s*)\d+[.)]\s+")


@dataclass(slots=True)
class _Section:
    tok_index: int
    level: int
    number: str | None
    title: str
    anchor: str
    start: int  # 0-based index of the heading's first line
    end: int  # 0-based exclusive end of the heading
    id: str = ""
    parent: str = ""
    text: str = ""
    line_end: int = 0


def parse_features(
    path: str, raw_lines: list[tuple[int, str]], result: ParseResult
) -> list[FeatureLine]:
    """Feature lines of the header (SPEC-03 §3.3), kept raw for M04b."""
    out: list[FeatureLine] = []
    for lineno, raw in raw_lines:
        values: dict[str, str] = {}
        for piece in raw.split(" · "):
            m = re.match(r"^\*\*(?P<key>[^*\n]+?):\*\*\s*(?P<val>.*)$", piece.strip())
            if m:
                values[m["key"].strip()] = m["val"].strip()
        name = values.get("Feature", "").strip()
        if not name:
            result.warnings.append(warn(path, lineno, "feature_bad_line", "Feature has no name"))
            continue
        domain = values.get("Domain") or None
        out.append(
            FeatureLine(
                line=lineno,
                raw=raw,
                name=name,
                slug=id_slug(name).replace("_", "-"),
                domain=domain,
                domain_slug=id_slug(domain).replace("_", "-") if domain else None,
                implements=tuple(re.findall(r"`([^`]+)`", values.get("Implements", ""))),
                tables=tuple(
                    t.strip(" `") for t in values.get("Tables", "").split(",") if t.strip(" `")
                ),
            )
        )
    return out


def _item_text(lines: list[str], start: int, end: int) -> str:
    chunk = lines[start:end]
    while chunk and not chunk[-1].strip():
        chunk.pop()
    if not chunk:
        return ""
    m = _ITEM_MARKER_RE.match(chunk[0])
    indent = len(m.group(0)) if m else 0
    first = chunk[0][indent:]
    rest = [ln[indent:] if not ln[:indent].strip() else ln.strip() for ln in chunk[1:]]
    return "\n".join([first, *rest]).strip()


def parse_spec(path: str, text: str) -> ParseResult:
    """Parse one spec file. Never raises on bad Markdown; problems are warnings."""
    result = ParseResult(path)
    raw_text = text
    text = nl(text)
    spec_id = id_from_filename(posixpath.basename(path))
    if not spec_id or not spec_id.startswith("SPEC-"):
        result.warnings.append(warn(path, 1, "bad_filename", "file name has no SPEC-NN ID"))
        return result
    lines = text.split("\n")
    toks = tokens(text)
    base = {"source_path": path}

    # ---- H1 and header
    h1_index = next(
        (
            i
            for i, t in enumerate(toks)
            if t.type == "heading_open" and t.tag == "h1" and t.level == 0
        ),
        None,
    )
    stem = posixpath.splitext(posixpath.basename(path))[0]
    title = stem
    if h1_index is None:
        result.warnings.append(warn(path, 1, "missing_h1", "no H1"))
    else:
        h1 = heading_text(toks[h1_index + 1])
        m = _H1_RE.match(h1)
        if m:
            title = m["title"].strip()
            if normalise(m["id"]) != spec_id:
                result.warnings.append(
                    warn(path, (toks[h1_index].map or [0])[0] + 1, "h1_id_mismatch", m["id"])
                )
        else:
            title = h1 or stem
    first_block = (h1_index + 3) if h1_index is not None else 0
    header: dict[str, str] = {}
    feature_lines: list[tuple[int, str]] = []
    if first_block < len(toks) and toks[first_block].type == "blockquote_open":
        bq = toks[first_block].map or [0, 0]
        pairs, feature_lines = header_pairs(lines[bq[0] : bq[1]], bq[0] + 1)
        for pair in pairs:
            header[pair.key] = pair.value
    result.features = parse_features(path, feature_lines, result)

    result.nodes.append(
        Node(
            "Spec",
            spec_id,
            {
                "title": title,
                "status": header.get("Status"),
                "owner_of": header.get("Owner of"),
                "header": header,
                **base,
                "source_line": 1,
                "content_hash": content_hash(raw_text),
            },
        )
    )

    # ---- sections
    sections = _collect_sections(path, spec_id, lines, toks, result)
    for i, sec in enumerate(sections):
        body_end = sections[i + 1].start if i + 1 < len(sections) else len(lines)
        body = lines[sec.end : body_end]
        idx = [j for j, ln in enumerate(body) if ln.strip()]
        if idx:
            sec.text = "\n".join(body[idx[0] : idx[-1] + 1])
            sec.line_end = sec.end + idx[-1] + 1
        else:
            sec.line_end = sec.end
        result.nodes.append(
            Node(
                "Section",
                sec.id,
                {
                    "spec_id": spec_id,
                    "number": sec.number,
                    "title": sec.title,
                    "anchor": "#" + sec.anchor,
                    "level": sec.level,
                    "line_start": sec.start + 1,
                    "line_end": sec.line_end,
                    "text": sec.text,
                    **base,
                    "source_line": sec.start + 1,
                    "content_hash": content_hash(sec.text),
                },
            )
        )
        result.rels.append(
            Rel("HAS_SECTION", sec.parent or spec_id, Ref("id", sec.id, sec.start + 1))
        )

    seen: set[tuple[object, ...]] = set()
    _walk(path, spec_id, toks, lines, sections, result, seen)
    _acceptance(path, spec_id, toks, lines, sections, result)
    return result


def _collect_sections(
    path: str, spec_id: str, lines: list[str], toks: list[Token], result: ParseResult
) -> list[_Section]:
    sections: list[_Section] = []
    counts: dict[str, int] = {}
    used: set[str] = set()
    stack: list[_Section] = []
    for i, t in enumerate(toks):
        if t.type != "heading_open" or t.level != 0 or not t.map:
            continue
        text = heading_text(toks[i + 1])
        slug = github_slug(text)
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        anchor = slug if n == 0 else f"{slug}-{n}"
        level = int(t.tag[1])
        if level not in (2, 3, 4):
            continue
        number, title = split_number(text)
        sec = _Section(i, level, number, title, anchor, t.map[0], t.map[1])
        base_id = f"{spec_id}#{number}" if number else f"{spec_id}#{id_slug(title)}"
        sec_id, k = base_id, 1
        while sec_id in used:
            k += 1
            sec_id = f"{base_id}-{k}"
        if k > 1:
            result.warnings.append(
                warn(path, sec.start + 1, "section_duplicate_id", f"{base_id} -> {sec_id}")
            )
        used.add(sec_id)
        sec.id = sec_id
        while stack and stack[-1].level >= level:
            stack.pop()
        sec.parent = stack[-1].id if stack else ""
        stack.append(sec)
        sections.append(sec)
    return sections


def _walk(  # noqa: PLR0917
    path: str,
    spec_id: str,
    toks: list[Token],
    lines: list[str],
    sections: list[_Section],
    result: ParseResult,
    seen: set[tuple[object, ...]],
) -> None:
    """LINKS_TO, MENTIONS and DEVIATION notes from the inline tokens, per own section."""
    by_token = {s.tok_index: s for s in sections}
    cur: _Section | None = None
    last_line = 1
    for i, t in enumerate(toks):
        if t.type == "heading_open":
            cur = by_token.get(i, cur)
            continue
        if t.type != "inline" or toks[i - 1].type == "heading_open":
            continue
        if t.map:
            last_line = t.map[0] + 1
        owner = cur.id if cur else spec_id
        children = t.children or []
        if cur is not None:
            for found in refs_in_inline(children, path=path, line=last_line):
                _links_from(owner, found, result, seen, (path, cur.anchor))
            for ident in backticked(children):
                add_rel(result.rels, seen, Rel("MENTIONS", owner, Ref("mention", ident, last_line)))
        if has_deviation_marker(children):
            for dev in deviation_ids(children):
                add_rel(result.rels, seen, Rel("AMENDS", dev, Ref("id", owner, last_line)))


def _links_from(
    owner: str,
    found: Found,
    result: ParseResult,
    seen: set[tuple[object, ...]],
    own: tuple[str, str],
) -> None:
    """LINKS_TO for one expression; a link back to the section itself is skipped."""
    result.warnings.extend(found.warnings)
    for ref in found.refs:
        if ref.kind in ("section", "id") and ref.target == owner:
            continue
        if ref.kind == "path" and (ref.target, ref.anchor) == own:
            continue
        add_rel(result.rels, seen, Rel("LINKS_TO", owner, ref, rel_props(ref)))


def _acceptance(  # noqa: PLR0917
    path: str,
    spec_id: str,
    toks: list[Token],
    lines: list[str],
    sections: list[_Section],
    result: ParseResult,
) -> None:
    taken: set[int] = set()
    for sec_i, sec in enumerate(sections):
        if sec.title.strip().lower() != "acceptance checks":
            continue
        stop = sections[sec_i + 1].tok_index if sec_i + 1 < len(sections) else len(toks)
        count = 0
        i = sec.tok_index
        while i < stop:
            t = toks[i]
            if t.type == "ordered_list_open" and t.level == 0:
                depth = t.level + 1
                for j in range(i + 1, stop):
                    item = toks[j]
                    if item.type == "ordered_list_close" and item.level == t.level:
                        i = j
                        break
                    if item.type != "list_item_open" or item.level != depth or not item.map:
                        continue
                    count += 1
                    number = int(item.info) if item.info.isdigit() else count
                    text = _item_text(lines, item.map[0], item.map[1])
                    line = item.map[0] + 1
                    if number in taken:
                        result.warnings.append(
                            warn(path, line, "ac_duplicate_number", f"check {number} repeated")
                        )
                        continue
                    taken.add(number)
                    ac_id = f"{spec_id}#ac{number}"
                    result.nodes.append(
                        Node(
                            "AcceptanceCheck",
                            ac_id,
                            {
                                "spec_id": spec_id,
                                "number": number,
                                "text": text,
                                "source_path": path,
                                "source_line": line,
                                "content_hash": content_hash(text),
                            },
                        )
                    )
                    result.rels.append(Rel("HAS_CHECK", spec_id, Ref("id", ac_id, line)))
            i += 1
