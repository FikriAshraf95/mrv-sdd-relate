"""SPEC-03 §5: deviation files, the index cross-check, docs and plans."""

from __future__ import annotations

from sdd.parse import (
    cross_check_index,
    parse_deviation,
    parse_deviation_index,
    parse_doc,
    parse_plan,
)
from tests.spec03.helpers import codes, parse_file, rel_targets, rels


def test_deviation_fields_task_and_affects() -> None:
    r = parse_file("tool_style", "docs/deviations/D001-steep-time-default.md")
    (node,) = r.nodes
    assert node.id == "D001"
    props = node.props
    assert props["title"] == "Default steep time is configurable"
    assert props["date"] == "2026-11-02"
    assert (props["status"], props["status_text"]) == ("open", "Open")
    assert props["spec_says"] == "The default steep time is fixed per tea."
    assert props["consequences"] == "Tests set the setting explicitly."
    assert rel_targets(r, "RAISED_IN", "D001") == ["M01", "M01.2"]
    assert rel_targets(r, "AMENDS", "D001") == ["SPEC-01#1"]
    affects = rels(r, "AFFECTS", "D001")
    assert [x.to.target for x in affects] == ["src/kettle/brew.py", "brews"]
    assert all(x.to.kind == "mention" and x.props == {"strict": True} for x in affects)
    assert codes(r) == []


def test_resolved_status_and_plain_spec_field() -> None:
    r = parse_file("suite_style", "docs/deviations/D012-line-rounding.md")
    assert r.nodes[0].props["status"] == "resolved"
    (amend,) = rels(r, "AMENDS", "D012")
    assert (amend.to.target, amend.to.note, amend.props) == (
        "SPEC-06#7",
        "step 1",
        {"note": "step 1"},
    )
    assert codes(r) == []  # no task, no Affects, still no warnings


def test_non_id_milestone_part_and_doc_spec() -> None:
    r = parse_file("suite_style", "docs/deviations/D023-ui-refresh-tokens.md")
    assert r.nodes[0].props["milestone_text"] == "UI refresh"
    assert rels(r, "RAISED_IN") == []
    (amend,) = rels(r, "AMENDS")
    assert (amend.to.kind, amend.to.target, amend.to.note) == ("doc", "design-system", "§1, §2")
    assert codes(r) == []


def test_missing_sections_and_bad_date() -> None:
    r = parse_deviation(
        "docs/deviations/D007-x.md",
        "# D007 — X\n\n- **Date / milestone:** soon · M01\n"
        "- **Status:** Resolved → spec updated\n\n"
        "## Spec says\nA\n\n## Why\nB\n",
    )
    assert codes(r) == [
        "deviation_bad_field",
        "deviation_missing_section",
        "deviation_missing_section",
    ]
    props = r.nodes[0].props
    assert props["date"] is None
    assert props["implementation_does"] == ""
    assert (props["spec_says"], props["why"]) == ("A", "B")
    assert props["status"] == "resolved"
    assert codes(parse_deviation("docs/deviations/notes.md", "")) == ["bad_filename"]


def test_deviation_index_ignores_fenced_template() -> None:
    rag = parse_file("rag_style", "docs/DEVIATIONS.md")
    assert rag.index_rows == []  # the template is fenced; the table has only a placeholder row
    suite = parse_file("suite_style", "docs/DEVIATIONS.md")
    assert [row.id for row in suite.index_rows] == ["D023", "D021", "D018", "D012"]
    row = suite.index_rows[1]
    assert row.link_path == "docs/deviations/D021-photo-thumbnails.md"
    assert (row.milestone, row.spec, row.status) == ("M17", "SPEC-18 §5", "Open")
    assert suite.index_rows[0].milestone == "UI refresh"
    assert suite.index_rows[0].spec == "design-system §1, §2"


def test_cross_check_index_both_directions() -> None:
    rows = parse_deviation_index(
        "docs/DEVIATIONS.md",
        "| # | T |\n|---|---|\n| [D001](deviations/D001-a.md) | x |\n| D002 | y |\n",
    ).index_rows
    paths = {"D001": "docs/deviations/D001-a.md", "D003": "docs/deviations/D003-c.md"}
    warnings = cross_check_index(rows, paths, "docs/DEVIATIONS.md")
    assert [(w.code, w.severity) for w in warnings] == [("deviation_index_mismatch", "warning")] * 2
    assert sorted(w.line for w in warnings) == [1, 4]
    assert cross_check_index(rows[:1], {"D001": "x"}, "docs/DEVIATIONS.md") == []


def test_docs_kinds_and_links() -> None:
    kinds = {
        "CLAUDE.md": "claude_md",
        "docs/IDEA.md": "idea",
        "docs/design-system.md": "design_system",
        "HANDOFF.md": "handoff",
        "README.md": "readme",
        "docs/other.md": "other",
        "backend/CLAUDE.md": "claude_md",
    }
    for path, kind in kinds.items():
        (node,) = parse_doc(path, "# Title\n").nodes
        assert (node.id, node.props["kind"], node.props["title"]) == (f"doc:{path}", kind, "Title")
    assert parse_doc("README.md", "no heading").nodes[0].props["title"] == "README.md"

    claude = parse_file("rag_style", "CLAUDE.md")
    links = rels(claude, "LINKS_TO", "doc:CLAUDE.md")
    assert [x.to.target for x in links][:2] == [
        "SPEC-00#6",
        "docs/milestones/M00-foundation.md",
    ]
    assert rels(parse_doc("a.md", "`[x](y.md)` and `SPEC-03 §1`"), "LINKS_TO") == []


def test_plan_files() -> None:
    r = parse_file("suite_style", "docs/milestones/M20f-plan.md")
    (node,) = r.nodes
    assert (node.id, node.props["kind"]) == ("doc:docs/milestones/M20f-plan.md", "plan")
    (plans,) = rels(r, "PLANS")
    assert (plans.from_id, plans.to.target) == ("doc:docs/milestones/M20f-plan.md", "M20f")
    assert codes(parse_plan("docs/milestones/notes.md", "# x")) == ["bad_filename"]
