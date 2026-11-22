"""Schema tables of a ``schema_specs`` file (SPEC-03 §6, plan M04b §1): Table, Column and rels.

Pure, like every parser: tokens in, nodes and relationships out. The caller (``parse_spec``)
passes the heading structure it already computed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it.token import Token

from sdd.ids import InvalidIdError, normalise
from sdd.parse.md import render_plain
from sdd.parse.model import Node, Ref, Rel

__all__ = ["TableSection", "parse_tables"]

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# a trailing parenthetical, one level of nesting allowed: `(append-only)`, `([SPEC-18](…))`
_PAREN_RE = re.compile(r"\s*\([^)]*(\([^)]*\))?[^)]*\)\s*$")
_NOT_NULL_RE = re.compile(r"\bnot\s+null\b", re.IGNORECASE)
_NULL_RE = re.compile(r"\bnull\b", re.IGNORECASE)
_PK_RE = re.compile(r"\bPK\b")
_REF_RE = re.compile(r"(?:FK\s*)?→\s*`?([A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True, slots=True)
class TableSection:
    """A section as ``parse_spec`` knows it: ID, title (number removed) and token range."""

    id: str
    title: str
    tok_index: int  # the ``heading_open`` token
    end_tok: int  # the next heading of any level (or ``len(toks)``)


def _table_name(title: str) -> str | None:
    name = _PAREN_RE.sub("", title).strip().strip("`").strip()
    return name if _IDENT_RE.match(name) else None


def _rows(toks: list[Token], start: int, stop: int) -> tuple[list[tuple[int, list[str]]], int]:
    """Rows of the table opening at ``start``: ``(line, cell texts)``, header row first."""
    rows: list[tuple[int, list[str]]] = []
    cells: list[str] = []
    line = 0
    i = start
    while i < stop:
        t = toks[i]
        if t.type == "table_close":
            break
        if t.type == "tr_open":
            cells, line = [], (t.map or [0])[0] + 1
        elif t.type == "inline":
            cells.append(render_plain(t.children).strip())
        elif t.type == "tr_close":
            rows.append((line, cells))
        i += 1
    return rows, i


def _first_column_table(toks: list[Token], start: int, stop: int) -> int | None:
    for i in range(start, stop):
        if toks[i].type != "table_open":
            continue
        for j in range(i, stop):
            if toks[j].type == "inline":
                head = render_plain(toks[j].children).strip().strip("`").lower()
                if head == "column":
                    return i
                break
    return None


def _clean_type(cell: str) -> str:
    text = _NULL_RE.sub("", _NOT_NULL_RE.sub("", cell.replace("`", "")))
    return re.sub(r"\s+", " ", text).strip()


def parse_tables(
    path: str, spec_id: str, toks: list[Token], sections: list[TableSection]
) -> tuple[list[Node], list[Rel]]:
    """Table and Column nodes plus ``DEFINES_TABLE``, ``HAS_COLUMN`` and ``REFERENCES`` rels."""
    nodes: list[Node] = []
    rels: list[Rel] = []
    for sec in sections:
        name = _table_name(sec.title)
        if name is None:
            continue
        start = _first_column_table(toks, sec.tok_index, sec.end_tok)
        if start is None:
            continue
        rows, _ = _rows(toks, start, sec.end_tok)
        if rows:
            _one_table(path, sec, name, rows, nodes, rels)
    return nodes, rels


def _one_table(  # noqa: PLR0917
    path: str,
    sec: TableSection,
    name: str,
    rows: list[tuple[int, list[str]]],
    nodes: list[Node],
    rels: list[Rel],
) -> None:
    try:
        table_id = normalise(f"table:{name}")
    except InvalidIdError:
        return
    head_line, head = rows[0]
    names = [h.replace("`", "").strip().lower() for h in head]
    type_i = names.index("type") if "type" in names else None
    notes_i = next((names.index(k) for k in ("rules", "notes") if k in names), None)
    if notes_i is None and len(head) > 2:
        notes_i = 2
    props = {"name": name, "defined_in": sec.id, "source_path": path, "source_line": head_line}
    nodes.append(Node("Table", table_id, props))
    rels.append(Rel("DEFINES_TABLE", sec.id, Ref("id", table_id, head_line)))
    seen: set[str] = set()
    for line, cells in rows[1:]:
        type_cell = cells[type_i] if type_i is not None and type_i < len(cells) else ""
        notes_cell = cells[notes_i] if notes_i is not None and notes_i < len(cells) else ""
        flags = f"{type_cell} {notes_cell}"
        extra: dict[str, object] = {}
        if _NOT_NULL_RE.search(flags):
            extra["nullable"] = False
        elif _NULL_RE.search(flags):
            extra["nullable"] = True
        if col_type := _clean_type(type_cell):
            extra["type"] = col_type
        if notes_cell:
            extra["notes"] = notes_cell
        targets = list(dict.fromkeys(_REF_RE.findall(flags)))
        for raw in (cells[0] if cells else "").split(","):
            col = raw.replace("`", "").strip()
            if not _IDENT_RE.match(col) or col in seen:
                continue
            try:
                col_id = normalise(f"column:{name}.{col}")
            except InvalidIdError:
                continue
            seen.add(col)
            col_props = {"table": name, "name": col, "pk": bool(_PK_RE.search(flags)), **extra}
            col_props |= {"source_path": path, "source_line": line}
            nodes.append(Node("Column", col_id, col_props))
            rels.append(Rel("HAS_COLUMN", table_id, Ref("id", col_id, line)))
            for target in targets:
                try:
                    rels.append(
                        Rel("REFERENCES", col_id, Ref("id", normalise(f"table:{target}"), line))
                    )
                except InvalidIdError:
                    continue
