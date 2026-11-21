"""SPEC-03 §7 checks 1–6, graph side: the fixture repos synced into a real store."""

from __future__ import annotations

from sdd.graph.store import Store
from tests.conftest import MakeProject
from tests.graph_dump import sync_project


def _rels(
    store: Store, type_: str, source: str | None = None
) -> list[tuple[str, str, dict[str, object]]]:
    rows = store.read(
        f"MATCH (a)-[r:{type_}]->(b) RETURN a.id AS a, b.id AS b, properties(r) AS p ORDER BY a, b"
    )
    return [
        (r["a"], r["b"], {k: v for k, v in r["p"].items() if k != "src"})
        for r in rows
        if source is None or r["a"] == source
    ]


def test_spec03_ac01_rag_fixture(project: MakeProject, store: Store) -> None:
    report = sync_project(project("rag_style"), store)
    assert [w for w in report.warnings if w.severity == "error"] == []
    reads = _rels(store, "READS", "M02")
    assert {b for _, b, _ in reads} == {
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
    assert [p for _, b, p in reads if b == "SPEC-03"] == [{"whole": True}]
    assert report.unresolved == {"M02": ["M03"]}  # M03 is not in the fixture


def test_spec03_ac02_suite_fixture(project: MakeProject, store: Store) -> None:
    report = sync_project(project("suite_style"), store)
    assert [w for w in report.warnings if w.severity == "error"] == []
    row = store.read("MATCH (m:Milestone {id: 'M17'}) RETURN m.status AS s, m.done_date AS d")
    assert row == [{"s": "done", "d": "2026-11-01"}]
    assert ("D021", "M17", {}) in _rels(store, "RAISED_IN")
    assert report.unresolved == {}


def test_spec03_ac03_grammar_results_land_in_the_graph(project: MakeProject, store: Store) -> None:
    sync_project(project("suite_style"), store)
    m17 = _rels(store, "READS", "M17")
    assert ("M17", "SPEC-02#file_shares", {}) in m17  # a backticked slug
    assert ("M17", "SPEC-18#2.4", {"note": "streaming"}) in m17
    assert ("D012", "SPEC-06#7", {"note": "step 1"}) in _rels(store, "AMENDS")


def test_spec03_ac04_link_text_beats_anchor(project: MakeProject, store: Store) -> None:
    sync_project(project("rag_style"), store)
    reads = {b for _, b, _ in _rels(store, "READS", "M02")}
    assert {"SPEC-02#3", "SPEC-02#4"} <= reads  # [SPEC-02 §3–4](…#3-loans)


def test_spec03_ac05_stable_and_legacy_task_nodes(project: MakeProject, store: Store) -> None:
    sync_project(project("tool_style"), store)
    stable = store.read("MATCH (t:Task) RETURN t.id AS id, t.stable_id AS s ORDER BY id")
    assert stable == [{"id": f"M01.{n}", "s": True} for n in (1, 2, 3, 4)]
    assert {(a, b) for a, b, _ in _rels(store, "BLOCKED_BY")} == {
        ("M01.2", "M01.1"),
        ("M01.3", "M01.2"),
    }
    assert _rels(store, "INCLUDES", "M01")[0][1] == "M01.1"

    sync_project(project("suite_style"), store)
    legacy = store.read("MATCH (t:Task {stable_id: false}) RETURN t.id AS id ORDER BY id")
    assert [r["id"] for r in legacy if r["id"].startswith("M17.")] == ["M17.p1", "M17.p2", "M17.p3"]
    assert ("M20f.2", "M20f.1", {}) in _rels(store, "BLOCKED_BY")


def test_spec03_ac06_deviation_note_amends_a_section(project: MakeProject, store: Store) -> None:
    sync_project(project("suite_style"), store)
    d018 = {b for a, b, _ in _rels(store, "AMENDS") if a == "D018"}
    assert {"SPEC-02#2", "SPEC-02#attachments"} <= d018
    sections = store.read("MATCH (s:Section {id: 'SPEC-02#attachments'}) RETURN s.spec_id AS id")
    assert sections == [{"id": "SPEC-02"}]
