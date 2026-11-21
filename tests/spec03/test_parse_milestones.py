"""SPEC-03 §4: milestone headers, task lines and IDs, status."""

from __future__ import annotations

from sdd.parse import ParseResult, parse_milestone
from tests.spec03.helpers import codes, parse_file, rel_targets, rels


def tasks(result: ParseResult) -> dict[str, dict[str, object]]:
    return {n.id: n.props for n in result.nodes if n.label == "Task"}


def ms(body: str, name: str = "M02-x.md") -> ParseResult:
    return parse_milestone(f"docs/milestones/{name}", f"# M02 — Sample\n\n{body}")


def test_spec03_ac05_task_lines() -> None:
    timer = parse_file("tool_style", "docs/milestones/M01-timer.md")
    t = tasks(timer)
    assert list(t) == ["M01.1", "M01.2", "M01.3", "M01.4"]
    assert all(p["stable_id"] for p in t.values())
    assert codes(timer) == []
    assert [(r.from_id, r.to.target) for r in rels(timer, "BLOCKED_BY")] == [
        ("M01.2", "M01.1"),
        ("M01.3", "M01.2"),
    ]
    assert t["M01.2"]["title"] == "Countdown endpoint"  # the (after …) is removed

    legacy = parse_file("suite_style", "docs/milestones/M17-photo-attachments.md")
    lt = tasks(legacy)
    assert list(lt) == ["M17.p1", "M17.p2", "M17.p3"]
    assert [p["stable_id"] for p in lt.values()] == [False, False, False]
    assert codes(legacy) == ["task_unstable_id"] * 3

    line = ms("- [ ] **M02.3** Hash and re-parse only changed files (after M02.1)\n")
    assert tasks(line)["M02.3"]["stable_id"] is True
    assert rel_targets(line, "BLOCKED_BY", "M02.3") == ["M02.1"]


def test_continuation_lines_nested_bullets_and_nested_checkboxes() -> None:
    legacy = parse_file("suite_style", "docs/milestones/M17-photo-attachments.md")
    first = tasks(legacy)["M17.p1"]
    assert first["title"] == (
        "Store uploaded photos on disk under the configured folder, keyed by the batch id\n"
        "- keep the original file name\n- reject files over ten megabytes"
    )
    assert first["group"] == "Backend"
    assert first["checked"] is True
    assert first["order"] == 1
    timer = tasks(parse_file("tool_style", "docs/milestones/M01-timer.md"))
    assert timer["M01.3"]["title"] == "Pause and resume"
    assert timer["M01.2"]["title"] == "Countdown endpoint"
    assert timer["M01.4"]["group"] == "Tests"
    assert timer["M01.4"]["checked"] is True
    assert timer["M01.4"]["source_line"] == 16


def test_hash_ignores_nested_checkbox_edits() -> None:
    a = ms("- [ ] **M02.1** one\n  - [ ] **M02.2** two\n")
    b = ms("- [ ] **M02.1** one\n  - [x] **M02.2** two edited\n")
    assert tasks(a)["M02.1"]["content_hash"] == tasks(b)["M02.1"]["content_hash"]
    assert tasks(a)["M02.2"]["content_hash"] != tasks(b)["M02.2"]["content_hash"]


def test_group_resets_at_h2() -> None:
    r = ms("### Backend\n- [ ] **M02.1** a\n\n## Later\n- [ ] **M02.2** b\n")
    t = tasks(r)
    assert (t["M02.1"]["group"], t["M02.2"]["group"]) == ("Backend", None)


def test_id_mismatch_duplicate_and_bad_after() -> None:
    r = ms(
        "- [ ] **M01.4** wrong milestone\n- [ ] **M02.1** a\n"
        "- [ ] **M02.1** again (after M02.1, soon)\n"
    )
    assert sorted(codes(r)) == ["task_bad_after", "task_duplicate_id", "task_id_mismatch"]
    assert sorted(w.severity for w in r.warnings) == ["error", "warning", "warning"]
    t = tasks(r)
    assert list(t) == ["M01.4", "M02.1", "M02.p3"]  # ID kept as written; duplicate goes positional
    assert t["M02.p3"]["stable_id"] is False
    assert rel_targets(r, "BLOCKED_BY", "M02.p3") == ["M02.1"]


def test_governed_by_and_verifies() -> None:
    r = ms(
        "- [ ] **M02.1** see [SPEC-03 §4.2](../specs/SPEC-03-x.md#42-y) and SPEC-02 `documents` "
        "and `src/a.py`\n"
        "- [ ] **M02.2** [SPEC-03 §10](../specs/SPEC-03-x.md#10-z) checks 3–4, 6 (rules)\n"
    )
    assert rel_targets(r, "GOVERNED_BY", "M02.1") == ["SPEC-03#4.2", "SPEC-02"]
    assert rel_targets(r, "VERIFIES", "M02.2") == ["SPEC-03#ac3", "SPEC-03#ac4", "SPEC-03#ac6"]
    assert rel_targets(r, "MENTIONS", "M02.1") == ["documents", "src/a.py"]
    timer = parse_file("tool_style", "docs/milestones/M01-timer.md")
    assert rel_targets(timer, "VERIFIES", "M01.4") == ["SPEC-01#ac1", "SPEC-01#ac2", "SPEC-01#ac3"]


def test_header_depends_blocks_reads_model() -> None:
    m17 = parse_file("suite_style", "docs/milestones/M17-photo-attachments.md")
    assert sorted(rel_targets(m17, "DEPENDS_ON", "M17")) == ["M02", "M16"]
    # "Blocks: nothing directly" yields nothing in either direction
    assert [r for r in rels(m17, "DEPENDS_ON") if r.to.target == "M17"] == []
    assert m17.nodes[0].props["model"] == "Sonnet"
    reads = rels(m17, "READS", "M17")
    assert [r.to.target for r in reads] == ["SPEC-18#5", "SPEC-18#2.4", "SPEC-02", "SPEC-06#7"]
    assert reads[1].props == {"note": "streaming"}
    assert reads[2].to.kind == "slug"
    assert reads[2].to.slug == "file_shares"

    m16 = parse_file("suite_style", "docs/milestones/M16-order-flow.md")
    # reversed Blocks: M17 depends on M16
    assert [(r.from_id, r.to.target) for r in rels(m16, "DEPENDS_ON")] == [
        ("M16", "M02"),
        ("M17", "M16"),
    ]
    none = ms("> **Depends on:** — · **Blocks:** None\n> **Model:** Haiku.\n")
    assert rels(none, "DEPENDS_ON") == []
    assert none.nodes[0].props["model"] == "Haiku"
    assert ms("> **Model:** Fast.\n").nodes[0].props["model"] is None


def test_non_spec_read_first_links_are_dropped_silently() -> None:
    r = ms(
        "> **Read first:** [DEVIATIONS](../DEVIATIONS.md) · [SPEC-03 §1](../specs/SPEC-03-x.md)\n"
    )
    assert rel_targets(r, "READS", "M02") == ["SPEC-03#1"]
    assert codes(r) == []


def test_order_and_goal_and_acceptance_and_later_checks() -> None:
    r = parse_milestone(
        "docs/milestones/M20f-x.md",
        "# M20f — X\n\n## Goal\nDo it.\nMore.\n\n## Acceptance criteria\n"
        "1. First\n   continued\n2. Second\n\n### Checks finished in later milestones\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n",
    )
    props = r.nodes[0].props
    assert r.nodes[0].id == "M20f"
    assert props["order"] == "0020f"
    assert props["goal"] == "Do it.\nMore."
    assert props["acceptance"] == ["First continued", "Second"]
    assert props["header"]["later_checks"].startswith("| a | b |")
    assert (
        parse_milestone("docs/milestones/M100-x.md", "# M100 — X\n").nodes[0].props["order"]
        == "0100"
    )


def test_status_variants() -> None:
    empty = ms("- [ ] **M02.1** a\n\n**Status:**\n")
    assert empty.nodes[0].props["status"] == "todo"
    assert empty.nodes[0].props["status_text"] is None
    started = ms("- [x] **M02.1** a\n\n**Status:**\n")
    assert started.nodes[0].props["status"] == "in_progress"
    done = ms(
        "- [x] **M02.1** a\n\n"
        "**Status:** DONE (2026-11-21), verified. Deviations: [D003](x.md), D004.\n"
    )
    props = done.nodes[0].props
    assert (props["status"], props["done_date"]) == ("done", "2026-11-21")
    assert rels(done, "RAISED_IN")[0].from_id == "D003"
    assert sorted(r.from_id for r in rels(done, "RAISED_IN")) == ["D003", "D004"]
    wrapped = ms("**Status: done (2026-01-02) with bullets.**\n- one\n- two\n")
    assert wrapped.nodes[0].props["status"] == "done"
    assert wrapped.nodes[0].props["status_text"].endswith("- two")
    text = ms("**Status:** In progress, 2 of 4.\n")
    assert (text.nodes[0].props["status"], text.nodes[0].props["done_date"]) == ("todo", None)
    suite = parse_file("suite_style", "docs/milestones/M17-photo-attachments.md")
    assert suite.nodes[0].props["status"] == "done"
    assert suite.nodes[0].props["done_date"] == "2026-11-01"
    assert "Open: thumbnail size" in suite.nodes[0].props["status_text"]
    assert [(r.from_id, r.to.target) for r in rels(suite, "RAISED_IN")] == [("D021", "M17")]


def test_includes_and_bad_names() -> None:
    r = ms("- [ ] **M02.1** a\n- [ ] b\n")
    assert [(x.from_id, x.to.target) for x in rels(r, "INCLUDES")] == [
        ("M02", "M02.1"),
        ("M02", "M02.p2"),
    ]
    bad = parse_milestone("docs/milestones/notes.md", "# Notes\n")
    assert codes(bad) == ["bad_filename"]
    mismatch = parse_milestone("docs/milestones/M02-x.md", "# M03 — X\n")
    assert codes(mismatch) == ["h1_id_mismatch"]
    assert parse_milestone("docs/milestones/done/M02-x.md", "# M02 — X\n").nodes[0].id == "M02"
