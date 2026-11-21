"""SPEC-03 §7 checks 1 and 2, whole-fixture parsing, and robustness."""

from __future__ import annotations

import pytest

from sdd.parse import (
    Catalog,
    parse_deviation,
    parse_deviation_index,
    parse_doc,
    parse_milestone,
    parse_plan,
    parse_spec,
    resolve,
)
from tests.spec03.helpers import parse_style, rel_targets, rels

STYLES = ["rag_style", "suite_style", "tool_style"]


def test_spec03_ac01_rag_fixture() -> None:
    results = parse_style("rag_style")
    errors = [w for r in results.values() for w in r.warnings if w.severity == "error"]
    assert errors == []
    m02 = results["docs/milestones/M02-catalog-import.md"]
    reads = rels(m02, "READS", "M02")
    assert {r.to.target for r in reads} == {
        "SPEC-03",
        "SPEC-02#3",
        "SPEC-02#4",
        "SPEC-06#2",
        "SPEC-06#4",
        "SPEC-06#5",
        "SPEC-06#6",
        "SPEC-08#4.6",
        "SPEC-08#4.7",
        "SPEC-11#2",
    }
    assert [r.props for r in reads if r.to.target == "SPEC-03"] == [{"whole": True}]
    assert all(not r.props.get("whole") for r in reads if r.to.target != "SPEC-03")


def test_spec03_ac02_suite_fixture() -> None:
    results = parse_style("suite_style")
    errors = [w for r in results.values() for w in r.warnings if w.severity == "error"]
    assert errors == []
    m17 = results["docs/milestones/M17-photo-attachments.md"]
    assert m17.nodes[0].props["status"] == "done"
    assert m17.nodes[0].props["done_date"] == "2026-11-01"
    assert [(r.from_id, r.to.target) for r in rels(m17, "RAISED_IN")] == [("D021", "M17")]
    d021 = results["docs/deviations/D021-photo-thumbnails.md"]
    assert ("D021", "M17") in [(r.from_id, r.to.target) for r in rels(d021, "RAISED_IN")]


@pytest.mark.parametrize("style", STYLES)
def test_every_fixture_file_parses_without_errors(style: str) -> None:
    results = parse_style(style)
    assert results
    for path, result in results.items():
        assert [w for w in result.warnings if w.severity == "error"] == [], path


@pytest.mark.parametrize("style", STYLES)
def test_fixture_references_resolve(style: str) -> None:
    results = parse_style(style)
    catalog = Catalog.from_results(results.values())
    unresolved: list[tuple[str, str, str]] = []
    for path, result in results.items():
        for rel in result.rels:
            if rel.type not in ("READS", "GOVERNED_BY", "AMENDS", "VERIFIES", "HAS_SECTION"):
                continue
            res = resolve(rel.to, catalog, path=path)
            unresolved += [(path, rel.type, u) for u in res.unresolved]
            assert res.targets or res.unresolved
    assert unresolved == []


def test_fixture_resolution_hits_expected_nodes() -> None:
    results = parse_style("rag_style")
    catalog = Catalog.from_results(results.values())
    m02 = results["docs/milestones/M02-catalog-import.md"]
    resolved = {t for r in rels(m02, "READS") for t in resolve(r.to, catalog).targets}
    assert "SPEC-08#4.6" in resolved
    assert "SPEC-03" in resolved
    # the project's own docs resolve by path
    claude = results["CLAUDE.md"]
    hits = [t for r in claude.rels for t in resolve(r.to, catalog).targets]
    assert "doc:backend/CLAUDE.md" in hits
    assert "M00" in hits


def test_tool_style_headers_and_sections() -> None:
    results = parse_style("tool_style")
    spec = results["docs/specs/SPEC-01-timer.md"]
    assert rel_targets(spec, "MENTIONS", "SPEC-01#2") == ["src/kettle/brew.py"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# \n",
        "\x00\x01\xff garbage \ud800   **[**](",
        "```\nunclosed fence\n# H1\n- [ ] **M02.1** in code\n",
        "> > > > > **DEVIATION:** see [D001](x) SPEC-02 §3–\n",
        "[](",
        "SPEC-99 §§§ `",
        "- [ ] **M02.1** (after\n- [ ] (after M02.1,\n",
        "| a |\n|---|\n| D001 |\n",
    ],
)
def test_parsers_never_raise(text: str) -> None:
    parse_spec("docs/specs/SPEC-05-x.md", text)
    parse_milestone("docs/milestones/M02-x.md", text)
    parse_deviation("docs/deviations/D001-x.md", text)
    parse_deviation_index("docs/DEVIATIONS.md", text)
    parse_doc("README.md", text)
    parse_plan("docs/milestones/M02-plan.md", text)


def test_fenced_code_hides_headings_and_tasks() -> None:
    text = "# M02 — X\n\n```\n- [ ] **M02.1** shown\n```\n\n- [ ] **M02.2** real\n"
    r = parse_milestone("docs/milestones/M02-x.md", text)
    assert [n.id for n in r.nodes if n.label == "Task"] == ["M02.2"]
