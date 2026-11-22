"""SPEC-06 §6 checks 3 and 4 (explain) and §5 (presets)."""

from __future__ import annotations

from typing import Any

import pytest

from sdd.errors import SddError
from sdd.service import impact
from sdd.service.runtime import Runtime
from tests.spec06.conftest import MakeHistory


def test_spec06_ac03_explain_feature_file(hist: Runtime) -> None:
    r = impact.explain(hist, "src/ingest/loader.py")
    assert r["file"] == {
        "id": "file:src/ingest/loader.py",
        "path": "src/ingest/loader.py",
        "language": "python",
        "is_test": False,
    }
    [feature] = r["features"]
    assert (feature["id"], feature["name"], feature["domain"], feature["specs"]) == (
        "feature:ingestion",
        "Ingestion",
        "Library",
        ["SPEC-02"],
    )
    assert feature["via"] == ["file:src/ingest/loader.py", "<-IMPLEMENTED_IN", "feature:ingestion"]
    [task] = r["tasks"]
    assert (task["id"], task["milestone"], task["status"]) == ("M02.1", "M02", "todo")
    assert task["via"] == ["file:src/ingest/loader.py", "<-TOUCHES", "M02.1"]
    commit = next(c for c in r["commits"] if c["message"] == "feat: loader [M02.1]")
    assert commit["tasks"] == ["M02.1"]
    assert commit["via"] == ["file:src/ingest/loader.py", "<-CHANGED", f"commit:{commit['sha']}"]
    assert [c["message"] for c in r["commits"]] == ["feat: loader [M02.1]", "chore: import fixture"]
    [dev] = r["deviations"]
    assert (dev["id"], dev["status"]) == ("D002", "open")
    assert dev["via"] == ["file:src/ingest/loader.py", "<-AFFECTS", "D002"]
    assert r["summary"] == (
        "src/ingest/loader.py implements feature Ingestion (Library), specified by SPEC-02. "
        f"Built by M02.1 (commits {commit['short']}). "
        "Shaped by D002 (open): Document titles may be empty."
    )
    assert r["synced_at"]


def test_explain_a_test_file_and_path_forms(hist: Runtime) -> None:
    r = impact.explain(hist, "./tests\\test_ingest.py")
    assert r["file"]["is_test"] is True
    assert [c["id"] for c in r["checks"]] == ["SPEC-02#ac1"]
    assert r["checks"][0]["spec_id"] == "SPEC-02"
    assert r["summary"].endswith("Tests SPEC-02#ac1.")
    # a unique tail of a path is enough; an unknown path is file_not_found
    assert impact.explain(hist, "loader.py")["file"]["path"] == "src/ingest/loader.py"
    with pytest.raises(SddError) as missing:
        impact.explain(hist, "src/none.py")
    assert missing.value.code == "file_not_found"
    with pytest.raises(SddError) as ambiguous:
        impact.explain(hist, "__init__.py")
    assert ambiguous.value.code == "ambiguous_target"
    assert "file:src/ingest/__init__.py" in ambiguous.value.details["candidates"]


def test_spec06_ac04_explain_orphan(history_runtime: MakeHistory) -> None:
    """Without git history, so no commit connects ``src/util/misc.py`` to anything."""
    runtime = history_runtime(history=False)
    r = impact.explain(runtime, "src/util/misc.py")
    for key in ("features", "sections", "tasks", "commits", "deviations", "checks"):
        assert r[key] == []
    assert r["summary"] == (
        "src/util/misc.py has no recorded connections: no feature, spec, task, commit, "
        "deviation or check names it (orphan code)."
    )


def test_presets_list_and_schema(hist: Runtime) -> None:
    listed = impact.presets()
    assert [p["name"] for p in listed] == [
        "schema",
        "milestone:<id>",
        "impact:<target>",
        "explain:<path>",
        "lineage:<section>",
        "feature:<slug>",
    ]
    assert all(set(p) == {"name", "params", "description"} for p in listed)
    schema = impact.preset(hist, "schema")
    table = next(n for n in schema["nodes"] if n["id"] == "Table")
    assert table == {"id": "Table", "label": "Label", "title": "Table (2)", "props": {"count": 2}}
    edge = next(
        e
        for e in schema["edges"]
        if (e["source"], e["type"], e["target"]) == ("Table", "HAS_COLUMN", "Column")
    )
    assert edge["count"] == 6  # an edge per (from label, type, to label), with a count


def test_preset_graphs_follow_the_via_chains(hist: Runtime) -> None:
    def edges(graph: dict[str, Any]) -> set[tuple[str, str, str]]:
        return {(e["source"], e["type"], e["target"]) for e in graph["edges"]}

    shape = {"id", "label", "title", "props"}
    ms = impact.preset(hist, "milestone:M02")
    assert all(set(n) == shape for n in ms["nodes"])
    assert ("M02", "INCLUDES", "M02.1") in edges(ms)
    assert ("M02", "READS", "SPEC-02#2") in edges(ms)
    assert ("D002", "RAISED_IN", "M02") in edges(ms)
    imp = impact.preset(hist, "impact:documents")
    assert ("column:chunks.document_id", "REFERENCES", "table:documents") in edges(imp)
    assert ("column:chunks.document_id", "HAS_COLUMN", "table:chunks") not in edges(
        imp
    )  # reversed below
    assert ("table:chunks", "HAS_COLUMN", "column:chunks.document_id") in edges(imp)
    assert ("feature:ingestion", "USES_TABLE", "table:documents") in edges(imp)
    exp = impact.preset(hist, "explain:src/ingest/loader.py")
    assert ("feature:ingestion", "IMPLEMENTED_IN", "file:src/ingest/loader.py") in edges(exp)
    assert ("feature:ingestion", "SPECIFIED_BY", "SPEC-02") in edges(exp)
    assert ("M02.1", "TOUCHES", "file:src/ingest/loader.py") in edges(exp)
    lin = impact.preset(hist, "lineage:SPEC-02 §2")
    assert ("D002", "AMENDS", "SPEC-02#2") in edges(lin)
    assert ("D002", "RAISED_IN", "M02.1") in edges(lin)
    assert ("M02.1", "TOUCHES", "file:src/ingest/loader.py") in edges(lin)
    feat = impact.preset(hist, "feature:ingestion")
    assert edges(feat) >= {
        ("feature:ingestion", "SPECIFIED_BY", "SPEC-02"),
        ("feature:ingestion", "USES_TABLE", "table:documents"),
        ("feature:ingestion", "IMPLEMENTED_IN", "file:src/ingest/loader.py"),
    }
    for bad in ("nope", "milestone:", "milestone:M99", "lineage:M02", "milestone:SPEC-02"):
        with pytest.raises(SddError) as err:
            impact.preset(hist, bad)
        assert err.value.code == "node_not_found"
