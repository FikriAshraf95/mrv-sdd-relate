"""SPEC-03 §6 and §7 check 7: schema tables from both reference layouts."""

from __future__ import annotations

from sdd.parse import ParseResult, parse_spec
from sdd.parse.model import Node
from tests.spec03.helpers import FIXTURES, rel_targets


def _spec(style: str, name: str, *, schema: bool = True) -> ParseResult:
    rel = f"docs/specs/{name}"
    return parse_spec(rel, (FIXTURES / style / rel).read_text(encoding="utf-8"), schema=schema)


def _node(result: ParseResult, node_id: str) -> Node:
    return next(n for n in result.nodes if n.id == node_id)


def test_spec03_ac07_schema_tables_rag_layout() -> None:
    result = _spec("rag_style", "SPEC-02-database-schema.md")
    tables = [n.id for n in result.nodes if n.label == "Table"]
    assert tables == ["table:documents", "table:loans", "table:jobs"]  # not "Table → milestone map"
    assert _node(result, "table:documents").props["defined_in"] == "SPEC-02#2"
    columns = [
        n.id for n in result.nodes if n.label == "Column" and n.props["table"] == "documents"
    ]
    assert columns == [
        "column:documents.id",
        "column:documents.title",
        "column:documents.shelf",
        "column:documents.created_at",  # one cell, two columns
        "column:documents.updated_at",
    ]
    assert _node(result, "column:documents.id").props["pk"] is True
    assert _node(result, "column:documents.title").props["nullable"] is False
    assert _node(result, "column:documents.shelf").props["nullable"] is True
    assert "nullable" not in _node(result, "column:documents.id").props
    assert _node(result, "column:documents.title").props["type"] == "text"
    assert rel_targets(result, "REFERENCES", "column:loans.document_id") == ["table:documents"]
    assert rel_targets(result, "DEFINES_TABLE", "SPEC-02#3") == ["table:loans"]
    assert rel_targets(result, "HAS_COLUMN", "table:loans") == [
        "column:loans.id",
        "column:loans.document_id",
        "column:loans.due_on",
    ]


def test_spec03_ac07_schema_tables_suite_layout() -> None:
    result = _spec("suite_style", "SPEC-02-database-schema.md")
    assert [n.id for n in result.nodes if n.label == "Table"] == [
        "table:users",
        "table:attachments",
        "table:file_shares",
    ]
    assert rel_targets(result, "REFERENCES", "column:attachments.uploaded_by") == ["table:users"]
    assert _node(result, "column:attachments.ts").props["type"] == "timestamptz"
    email = _node(result, "column:users.email")
    assert email.props["type"] == "text"
    assert email.props["nullable"] is False
    assert email.props["notes"] == "unique"
    assert rel_targets(result, "DEFINES_TABLE", "SPEC-02#attachments") == ["table:attachments"]


def test_schema_tables_only_in_schema_specs() -> None:
    result = _spec("rag_style", "SPEC-02-database-schema.md", schema=False)
    assert [n for n in result.nodes if n.label in ("Table", "Column")] == []


def test_schema_tables_ignore_code_fences_and_other_headings() -> None:
    text = (
        "# SPEC-02 — X\n\n## 1. `a`\n\n```\n| Column | Type |\n|---|---|\n| x | int |\n```\n\n"
        "## 2. `b` (append-only)\n\nSome text.\n\n| Column | Type | Rules |\n|---|---|---|\n"
        "| `k` | int | PK |\n| `k` | int | |\n\n### sub\n\n## 3. two words\n\n"
        "| Column | Type |\n|---|---|\n| x | int |\n"
    )
    result = parse_spec("docs/specs/SPEC-02-x.md", text, schema=True)
    assert [n.id for n in result.nodes if n.label == "Table"] == ["table:b"]
    assert [n.id for n in result.nodes if n.label == "Column"] == ["column:b.k"]  # first kept


def test_schema_tables_table_after_next_heading_is_not_taken() -> None:
    text = (
        "# SPEC-02 — X\n\n## 1. `a`\n\n### two words\n\n| Column | Type |\n|---|---|\n| x | int |\n"
    )
    result = parse_spec("docs/specs/SPEC-02-x.md", text, schema=True)
    assert [n for n in result.nodes if n.label == "Table"] == []
