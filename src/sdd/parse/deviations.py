"""Deviation files and the deviation index (SPEC-03 §5.1–5.2, plan M01a §7)."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping

from markdown_it.token import Token

from sdd.ids import id_from_filename, normalise
from sdd.parse.links import backticked, refs_in_markdown
from sdd.parse.md import content_hash, heading_text, nl, render_plain, tokens
from sdd.parse.model import (
    IndexRow,
    Node,
    ParseResult,
    ParseWarning,
    Ref,
    Rel,
    add_rel,
    rel_props,
    warn,
)

__all__ = ["cross_check_index", "parse_deviation", "parse_deviation_index"]

_H1_RE = re.compile(r"^(?P<id>D\d+)\s*[—–-]\s*(?P<title>.+)$", re.IGNORECASE)
_FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*(?P<key>[^*\n]+?):\*\*\s*(?P<val>.*)$", re.DOTALL)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ID_RE = re.compile(r"(?<![A-Za-z0-9_])M\d+[a-z]?(?:\.\d+)?\b")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EXTERNAL_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
_SECTIONS = {
    "spec says": "spec_says",
    "implementation does": "implementation_does",
    "why": "why",
    "consequences": "consequences",
}
_SPEC_KINDS = ("section", "slug", "spec", "doc")


def parse_deviation(path: str, text: str) -> ParseResult:  # noqa: PLR0915
    """Parse one ``D<nnn>-*.md`` file. Never raises on bad Markdown."""
    result = ParseResult(path)
    raw_text = text
    text = nl(text)
    dev = id_from_filename(posixpath.basename(path))
    if not dev or not dev.startswith("D"):
        result.warnings.append(warn(path, 1, "bad_filename", "file name has no D<nnn> ID"))
        return result
    lines = text.split("\n")
    toks = tokens(text)
    seen: set[tuple[object, ...]] = set()

    stem = posixpath.splitext(posixpath.basename(path))[0]
    title = stem
    h1_index = next(
        (i for i, t in enumerate(toks) if t.type == "heading_open" and t.tag == "h1"), None
    )
    if h1_index is None:
        result.warnings.append(warn(path, 1, "missing_h1", "no H1"))
    else:
        h1 = heading_text(toks[h1_index + 1])
        m = _H1_RE.match(h1)
        title = m["title"].strip() if m else (h1 or stem)
        if m and normalise(m["id"]) != dev:
            result.warnings.append(
                warn(path, (toks[h1_index].map or [0])[0] + 1, "h1_id_mismatch", m["id"])
            )

    # (level, title, first line, line after the heading) of every top-level heading
    heads: list[tuple[int, str, int, int]] = [
        (int(t.tag[1]), heading_text(toks[i + 1]), t.map[0], t.map[1])
        for i, t in enumerate(toks)
        if t.type == "heading_open" and t.level == 0 and t.map
    ]
    first_h2 = next((h[2] for h in heads if h[0] == 2), len(lines))

    # ---- fields: top-level bullets before the first H2
    fields: dict[str, tuple[str, int]] = {}
    for t in toks:
        if t.type == "list_item_open" and t.level == 1 and t.map and t.map[0] < first_h2:
            m = _FIELD_RE.match("\n".join(lines[t.map[0] : t.map[1]]))
            if m:
                value = re.sub(r"\s+", " ", m["val"]).strip()
                fields.setdefault(m["key"].strip().lower(), (value, t.map[0] + 1))

    date: str | None = None
    milestone_text: str | None = None
    if "date / milestone" in fields:
        val, line = fields["date / milestone"]
        parts = [p.strip() for p in val.split("·")]
        dm = _DATE_RE.search(parts[0])
        if dm:
            date = dm.group(0)
        else:
            result.warnings.append(warn(path, line, "deviation_bad_field", "unparsable date"))
        for part in parts[1:]:
            idm = _ID_RE.search(_LINK_RE.sub(r"\1", part))
            if idm:
                ref = Ref("id", normalise(idm.group(0)), line)
                add_rel(result.rels, seen, Rel("RAISED_IN", dev, ref))
            elif part:
                milestone_text = part
    if "spec" in fields:
        val, line = fields["spec"]
        for found in refs_in_markdown(val, path=path, line=line):
            result.warnings.extend(found.warnings)
            for ref in found.refs:
                spec_path = (
                    ref.kind == "path"
                    and (ident := id_from_filename(posixpath.basename(ref.target))) is not None
                    and ident.startswith("SPEC-")
                )
                if ref.kind in _SPEC_KINDS or spec_path:
                    add_rel(result.rels, seen, Rel("AMENDS", dev, ref, rel_props(ref)))
    if "affects" in fields:
        val, line = fields["affects"]
        for entry in re.findall(r"`([^`]+)`", val):
            ref = Ref("mention", entry.strip(), line)
            add_rel(result.rels, seen, Rel("AFFECTS", dev, ref, {"strict": True}))
    status_text = fields.get("status", ("", 1))[0]
    status = "resolved" if status_text.lower().startswith("resolved") else "open"

    # ---- template sections
    body: dict[str, str] = {}
    for hi, (level, name, _start, after) in enumerate(heads):
        key = _SECTIONS.get(name.strip().lower())
        if level != 2 or key is None:
            continue
        end_line = next((h[2] for h in heads[hi + 1 :] if h[0] <= 2), len(lines))
        body[key] = "\n".join(lines[after:end_line]).strip()
    for name, key in _SECTIONS.items():
        if key not in body:
            result.warnings.append(
                warn(path, 1, "deviation_missing_section", f"no '{name.title()}' section")
            )
            body[key] = ""

    # ---- MENTIONS from the whole body
    for t in toks:
        if t.type == "inline":
            line = (t.map or [0])[0] + 1
            for ident in backticked(t.children):
                add_rel(result.rels, seen, Rel("MENTIONS", dev, Ref("mention", ident, line)))

    props: dict[str, object] = {
        "title": title,
        "date": date,
        "status": status,
        "status_text": status_text,
        **body,
        "source_path": path,
        "source_line": 1,
        "content_hash": content_hash(raw_text),
    }
    if milestone_text:
        props["milestone_text"] = milestone_text
    result.nodes.append(Node("Deviation", dev, props))
    return result


def _row_cells(toks: list[Token], i: int) -> list[Token]:
    out: list[Token] = []
    j = i + 1
    while j < len(toks) and toks[j].type != "tr_close":
        if toks[j].type == "inline":
            out.append(toks[j])
        j += 1
    return out


def parse_deviation_index(path: str, text: str) -> ParseResult:
    """Rows of ``DEVIATIONS.md``'s index table (tables outside code only)."""
    result = ParseResult(path)
    toks = tokens(nl(text))
    for i, t in enumerate(toks):
        if t.type != "tr_open" or not t.map:
            continue
        cells = _row_cells(toks, i)
        if not cells:
            continue
        m = re.search(r"\bD(\d+)\b", render_plain(cells[0].children))
        if not m:
            continue
        href = next(
            (
                str(ch.attrGet("href") or "")
                for ch in cells[0].children or []
                if ch.type == "link_open"
            ),
            "",
        )
        link_path: str | None = None
        target = href.partition("#")[0]
        if target and not _EXTERNAL_RE.match(target):
            link_path = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        texts = [render_plain(c.children).strip() for c in cells]
        texts += [""] * (5 - len(texts))
        title, milestone, spec, status = texts[1:5]
        result.index_rows.append(
            IndexRow(
                t.map[0] + 1, normalise(f"D{m.group(1)}"), link_path, title, milestone, spec, status
            )
        )
    return result


def cross_check_index(
    index_rows: list[IndexRow], deviation_paths: Mapping[str, str], index_path: str
) -> list[ParseWarning]:
    """A file without an index row, or a row without a file, is ``deviation_index_mismatch``."""
    out: list[ParseWarning] = []
    rows = {r.id: r for r in index_rows}
    for dev_id, dev_path in sorted(deviation_paths.items()):
        if dev_id not in rows:
            out.append(warn(index_path, 1, "deviation_index_mismatch", f"{dev_path} has no row"))
    for dev_id, row in rows.items():
        if dev_id not in deviation_paths:
            out.append(warn(index_path, row.line, "deviation_index_mismatch", f"{dev_id} no file"))
    return out
