"""SPEC-03 §3: spec headers, sections, acceptance checks, Feature lines, DEVIATION notes."""

from __future__ import annotations

from sdd.parse import parse_spec
from tests.spec03.helpers import FIXTURES, codes, parse_file, rel_targets, rels

SPEC = """# SPEC-05 — Sample

> **Status:** v1 (2026-11-21) · **Owner of:** things and more
> **Related:** [SPEC-00 §6](SPEC-00-x.md#6-global)

Preamble text.

## 5. Parent
Parent body [self](#5-parent), [other](SPEC-06-y.md#2-x) and `table_x`.

### 5.1 Child
Child body.

#### 5.1.1 Grandchild
grand text

## 6. Next
next text

## 7. Deep
#### Loose
deep text
"""


def sections(text: str = SPEC) -> dict[str, dict[str, object]]:
    result = parse_spec("docs/specs/SPEC-05-sample.md", text)
    return {n.id: n.props for n in result.nodes if n.label == "Section"}


def test_both_header_styles() -> None:
    rag = parse_file("rag_style", "docs/specs/SPEC-00-overview.md")
    props = rag.nodes[0].props
    assert props["title"] == "Overview"
    assert props["status"] == "v1 (2026-11-01)"
    assert props["owner_of"] == "glossary, global conventions, milestone order"
    assert props["header"]["Read with"] == "[IDEA](../IDEA.md)"

    suite = parse_file("suite_style", "docs/specs/SPEC-02-database-schema.md")
    props = suite.nodes[0].props
    assert props["status"] is None
    assert props["header"]["Spec ID"] == "SPEC-02"
    assert props["header"]["Consumed by"] == "SPEC-03, SPEC-06, SPEC-18"
    assert props["header"]["Related"].startswith("[SPEC-00 §6 conventions]")


def test_spec03_ac08_feature_line_parse() -> None:
    result = parse_file("tool_style", "docs/specs/SPEC-01-timer.md")
    (feature,) = result.features
    assert feature.name == "Brewing"
    assert feature.slug == "brewing"
    assert feature.domain == "Tea"
    assert feature.domain_slug == "tea"
    assert feature.implements == ("src/kettle/**",)
    assert feature.tables == ("brews", "teas")
    assert feature.line == 4
    assert "Feature" not in result.nodes[0].props["header"]
    bad = parse_spec("docs/specs/SPEC-05-x.md", "# SPEC-05 — X\n\n> **Feature:** · **Domain:** A\n")
    assert codes(bad) == ["feature_bad_line"]
    assert bad.features == []


def test_sections_numbers_anchors_and_ranges() -> None:
    secs = sections()
    assert list(secs) == [
        "SPEC-05#5",
        "SPEC-05#5.1",
        "SPEC-05#5.1.1",
        "SPEC-05#6",
        "SPEC-05#7",
        "SPEC-05#loose",
    ]
    parent = secs["SPEC-05#5"]
    assert (parent["number"], parent["title"], parent["level"]) == ("5", "Parent", 2)
    assert parent["anchor"] == "#5-parent"
    assert secs["SPEC-05#5.1"]["anchor"] == "#51-child"
    assert secs["SPEC-05#loose"]["number"] is None
    # own text only: the child's text is not in the parent's
    assert parent["text"].startswith("Parent body")
    assert "Child body" not in str(parent["text"])
    assert parent["line_start"] == 8
    assert parent["line_end"] == 9
    assert secs["SPEC-05#5.1"]["line_start"] == 11


def test_own_text_hash_changes_only_for_the_edited_section() -> None:
    before = sections()
    after = sections(SPEC.replace("Child body.", "Child body, edited."))
    assert before["SPEC-05#5"]["content_hash"] == after["SPEC-05#5"]["content_hash"]
    assert before["SPEC-05#5.1"]["content_hash"] != after["SPEC-05#5.1"]["content_hash"]
    assert before["SPEC-05#6"]["content_hash"] == after["SPEC-05#6"]["content_hash"]


def test_has_section_nesting() -> None:
    result = parse_spec("docs/specs/SPEC-05-sample.md", SPEC)
    parents = {r.to.target: r.from_id for r in rels(result, "HAS_SECTION")}
    assert parents == {
        "SPEC-05#5": "SPEC-05",
        "SPEC-05#5.1": "SPEC-05#5",
        "SPEC-05#5.1.1": "SPEC-05#5.1",
        "SPEC-05#6": "SPEC-05",
        "SPEC-05#7": "SPEC-05",
        "SPEC-05#loose": "SPEC-05#7",  # an H4 directly under an H2 hangs from the H2
    }


def test_links_mentions_and_self_links() -> None:
    result = parse_spec("docs/specs/SPEC-05-sample.md", SPEC)
    links = rels(result, "LINKS_TO", "SPEC-05#5")
    assert [(r.to.kind, r.to.target) for r in links] == [("path", "docs/specs/SPEC-06-y.md")]
    assert links[0].to.anchor == "2-x"
    assert rel_targets(result, "MENTIONS", "SPEC-05#5") == ["table_x"]
    # the header blockquote (preamble) yields no relationships
    assert not rels(result, "LINKS_TO", "SPEC-05")


def test_duplicate_slug_is_deduped() -> None:
    text = "# SPEC-05 — X\n\n## 1. A\n### same\none\n### same\ntwo\n"
    result = parse_spec("docs/specs/SPEC-05-x.md", text)
    ids = [n.id for n in result.nodes if n.label == "Section"]
    assert ids == ["SPEC-05#1", "SPEC-05#same", "SPEC-05#same-2"]
    assert [w.severity for w in result.warnings if w.code == "section_duplicate_id"] == ["info"]
    anchors = [n.props["anchor"] for n in result.nodes if n.label == "Section"]
    assert anchors == ["#1-a", "#same", "#same-1"]


def test_acceptance_checks() -> None:
    result = parse_file("tool_style", "docs/specs/SPEC-01-timer.md")
    checks = [n for n in result.nodes if n.label == "AcceptanceCheck"]
    assert [n.id for n in checks] == ["SPEC-01#ac1", "SPEC-01#ac2", "SPEC-01#ac3"]
    assert checks[1].props["number"] == 2
    assert checks[1].props["text"] == "A black tea brew defaults to 240 seconds."
    assert rel_targets(result, "HAS_CHECK", "SPEC-01") == [n.id for n in checks]

    text = (
        "# SPEC-05 — X\n\n## Acceptance checks\n\n"
        "4. one\n   more\n   - nested\n\n9. two\n\n9. three\n"
    )
    result = parse_spec("docs/specs/SPEC-05-x.md", text)
    checks = [n for n in result.nodes if n.label == "AcceptanceCheck"]
    assert [n.id for n in checks] == ["SPEC-05#ac4", "SPEC-05#ac9"]
    assert checks[0].props["text"] == "one\nmore\n- nested"
    assert codes(result) == ["ac_duplicate_number"]


def test_spec03_ac06_nested_deviation_note() -> None:
    suite = parse_file("suite_style", "docs/specs/SPEC-02-database-schema.md")
    amends = rels(suite, "AMENDS", "D018")
    assert [r.to.target for r in amends] == ["SPEC-02#attachments"]
    assert [r.to.kind for r in amends] == ["id"]
    # the same note inside a list item (indented blockquote)
    six = parse_file("suite_style", "docs/specs/SPEC-06-stock-and-orders.md")
    assert rel_targets(six, "AMENDS", "D012") == ["SPEC-06#7"]
    # a note before the first H2 amends the Spec
    pre = parse_spec(
        "docs/specs/SPEC-05-x.md",
        "# SPEC-05 — X\n\n> > **DEVIATION:** see [D007](d.md) — x\n\n## 1. A\n",
    )
    assert rel_targets(pre, "AMENDS", "D007") == ["SPEC-05"]


def test_deviation_markers_in_code_are_ignored() -> None:
    template = (FIXTURES / "rag_style/docs/DEVIATIONS.md").read_text(encoding="utf-8")
    result = parse_spec("docs/specs/SPEC-09-x.md", "# SPEC-09 — X\n\n## 1. Rules\n\n" + template)
    assert rels(result, "AMENDS") == []
    inline = parse_spec(
        "docs/specs/SPEC-09-x.md",
        "# SPEC-09 — X\n\n## 1. R\n\nWrite `**DEVIATION:** see [D001](x)`.\n",
    )
    assert rels(inline, "AMENDS") == []
    indented = parse_spec(
        "docs/specs/SPEC-09-x.md",
        "# SPEC-09 — X\n\n## 1. R\n\n    > **DEVIATION:** see [D001](x)\n",
    )
    assert rels(indented, "AMENDS") == []


def test_bad_file_name_and_headings() -> None:
    bad = parse_spec("docs/specs/notes.md", "# Notes\n")
    assert codes(bad) == ["bad_filename"]
    assert bad.warnings[0].severity == "error"
    assert bad.nodes == []
    result = parse_spec("docs/specs/SPEC-05-x.md", "no heading here\n\n## 1. A\n")
    assert codes(result) == ["missing_h1"]
    assert result.nodes[0].props["title"] == "SPEC-05-x"
    mismatch = parse_spec("docs/specs/SPEC-05-x.md", "# SPEC-06 — X\n")
    assert codes(mismatch) == ["h1_id_mismatch"]
    assert mismatch.nodes[0].id == "SPEC-05"
    assert mismatch.nodes[0].props["title"] == "X"


def test_crlf_gives_same_result() -> None:
    lf = parse_spec("docs/specs/SPEC-05-sample.md", SPEC)
    crlf = parse_spec("docs/specs/SPEC-05-sample.md", SPEC.replace("\n", "\r\n"))
    assert [(n.id, n.props["line_start"]) for n in lf.nodes if n.label == "Section"] == [
        (n.id, n.props["line_start"]) for n in crlf.nodes if n.label == "Section"
    ]
