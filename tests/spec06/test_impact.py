"""SPEC-06 §6 checks 1, 2, 5, 6 and 7, and the named-query rules (plan M04b §4–5).

Real stores; ``tool_style`` (with its scripted git history) copied into ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sdd.errors import SddError
from sdd.graph import queries
from sdd.service import impact
from sdd.service.impact import hops
from sdd.service.runtime import Runtime
from tests.graph_dump import write_files
from tests.spec06.conftest import MakeHistory

LIBRARY_FILES = [
    "src/ingest/__init__.py",
    "src/ingest/chunker.py",
    "src/ingest/loader.py",
]


def _items(result: dict[str, Any], group: str) -> dict[str, list[str]]:
    return {i["id"]: i["via"] for i in result["groups"][group]}


def test_spec06_ac01_impact_documents(hist: Runtime) -> None:
    r = impact.impact(hist, "documents")
    assert r["target"] == {"id": "table:documents", "label": "Table", "title": "documents"}
    assert set(r["groups"]) == set(impact.GROUPS)
    assert _items(r, "sections") == {
        "SPEC-02#2": ["table:documents", "<-DEFINES_TABLE", "SPEC-02#2"]
    }
    assert _items(r, "specs") == {
        "SPEC-02": [
            "table:documents",
            "<-DEFINES_TABLE",
            "SPEC-02#2",
            "<-HAS_SECTION",
            "SPEC-02",
        ]
    }
    chunks = _items(r, "tables")["table:chunks"]
    assert chunks == [
        "table:documents",
        "<-REFERENCES",
        "column:chunks.document_id",
        "<-HAS_COLUMN",
        "table:chunks",
    ]
    assert {"column:documents.id", "column:documents.title"} <= set(_items(r, "tables"))
    assert _items(r, "features") == {
        "feature:ingestion": ["table:documents", "<-USES_TABLE", "feature:ingestion"]
    }
    files = _items(r, "files")
    assert set(files) == {f"file:{p}" for p in LIBRARY_FILES}
    assert files["file:src/ingest/loader.py"] == [
        "table:documents",
        "<-USES_TABLE",
        "feature:ingestion",
        "->IMPLEMENTED_IN",
        "file:src/ingest/loader.py",
    ]
    assert _items(r, "tasks_open")["M02.1"] == ["table:documents", "<-MENTIONS", "M02.1"]
    # both routes reach D002; the one-hop AFFECTS beats the AMENDS chain
    assert _items(r, "deviations") == {"D002": ["table:documents", "<-AFFECTS", "D002"]}
    assert r["groups"]["deviations"][0]["status"] == "open"
    assert r["counts"]["files"] == 3
    assert r["counts"]["tables"] == len(r["groups"]["tables"])
    assert r["synced_at"]


def test_spec06_ac02_impact_section(history_runtime: MakeHistory) -> None:
    """tool_style has no SPEC-03 §5.2; ``SPEC-02 §2`` has the same shape: M02 reads it, M02.1
    is governed by it, D002 amends it. M02.1 is ticked and M02.4 added, so both task groups
    are exercised."""
    link = "[SPEC-02 §2](../specs/SPEC-02-ingest-schema.md#2-documents)"

    def edit(root: Path) -> None:
        path = "docs/milestones/M02-ingestion.md"
        text = (root / path).read_text(encoding="utf-8")
        text = text.replace("- [ ] **M02.1**", "- [x] **M02.1**")
        text = text.replace("### Tests", f"- [ ] **M02.4** Audit the loader ({link})\n### Tests")
        write_files(root, {path: text})

    r = impact.impact(history_runtime(before=edit), "SPEC-02 §2")
    assert r["target"]["id"] == "SPEC-02#2"
    assert _items(r, "milestones") == {"M02": ["SPEC-02#2", "<-READS", "M02"]}
    assert _items(r, "tasks_done") == {"M02.1": ["SPEC-02#2", "<-GOVERNED_BY", "M02.1"]}
    assert _items(r, "tasks_open") == {"M02.4": ["SPEC-02#2", "<-GOVERNED_BY", "M02.4"]}
    assert _items(r, "deviations") == {"D002": ["SPEC-02#2", "<-AMENDS", "D002"]}
    assert _items(r, "tables") == {
        "table:documents": ["SPEC-02#2", "->DEFINES_TABLE", "table:documents"]
    }
    assert "feature:ingestion" in _items(r, "features")
    assert "file:tests/test_ingest.py" in _items(r, "tests")


def test_spec_target_walks_every_section(hist: Runtime) -> None:
    r = impact.impact(hist, "SPEC-02")
    assert _items(r, "sections")["SPEC-02#2"] == ["SPEC-02", "->HAS_SECTION", "SPEC-02#2"]
    assert _items(r, "deviations")["D002"] == [
        "SPEC-02",
        "->HAS_SECTION",
        "SPEC-02#2",
        "<-AMENDS",
        "D002",
    ]
    assert _items(r, "milestones")["M02"] == [
        "SPEC-02",
        "->HAS_SECTION",
        "SPEC-02#2",
        "<-READS",
        "M02",
    ]
    assert _items(r, "features") == {
        "feature:ingestion": ["SPEC-02", "<-SPECIFIED_BY", "feature:ingestion"]
    }


def test_column_feature_task_and_milestone_targets(hist: Runtime) -> None:
    col = impact.impact(hist, "column:chunks.document_id")
    assert _items(col, "tables")["table:documents"] == [
        "column:chunks.document_id",
        "->REFERENCES",
        "table:documents",
    ]
    assert _items(col, "tables")["table:chunks"] == [
        "column:chunks.document_id",
        "<-HAS_COLUMN",
        "table:chunks",
    ]
    feat = impact.impact(hist, "feature:ingestion")
    assert set(_items(feat, "tables")) == {"table:documents", "table:chunks"}
    assert _items(feat, "specs")["SPEC-02"] == ["feature:ingestion", "->SPECIFIED_BY", "SPEC-02"]
    assert _items(feat, "sections")["SPEC-02#2"] == [
        "feature:ingestion",
        "->SPECIFIED_BY",
        "SPEC-02",
        "->HAS_SECTION",
        "SPEC-02#2",
    ]
    assert _items(feat, "features") == {
        "domain:library": ["feature:ingestion", "->BELONGS_TO", "domain:library"]
    }
    task = impact.impact(hist, "M02.1")
    assert _items(task, "milestones")["M02"] == ["M02.1", "<-INCLUDES", "M02"]
    assert _items(task, "sections")["SPEC-02#2"] == ["M02.1", "->GOVERNED_BY", "SPEC-02#2"]
    assert _items(task, "files")["file:src/ingest/loader.py"] == [
        "M02.1",
        "->TOUCHES",
        "file:src/ingest/loader.py",
    ]
    assert _items(task, "deviations")["D002"] == ["M02.1", "<-RAISED_IN", "D002"]
    assert len(task["groups"]["commits"]) == 1
    ms = impact.impact(hist, "M02")
    assert set(_items(ms, "tasks_open")) == {"M02.1", "M02.2", "M02.3"}
    assert _items(ms, "milestones") == {"M01": ["M02", "->DEPENDS_ON", "M01"]}
    assert "SPEC-02#2" in _items(ms, "sections")


def test_spec06_ac05_find_code_intersection(hist: Runtime) -> None:
    both = impact.find_code(hist, table="documents", feature="ingestion")
    assert [f["path"] for f in both["files"]] == LIBRARY_FILES
    assert both["counts"] == {"files": 3}
    # the via comes from the first argument in the order feature, domain, table, spec, text
    assert both["files"][2]["via"] == [
        "feature:ingestion",
        "->IMPLEMENTED_IN",
        "file:src/ingest/loader.py",
    ]
    only_table = impact.find_code(hist, table="documents")
    assert {f["path"] for f in only_table["files"]} == set(LIBRARY_FILES)
    assert impact.find_code(hist, table="documents", text="chunker")["counts"] == {"files": 1}
    assert [f["path"] for f in impact.find_code(hist, spec="SPEC-02")["files"]] == LIBRARY_FILES
    assert impact.find_code(hist, domain="Library")["counts"] == {"files": 3}
    assert impact.find_code(hist, text="KETTLE")["counts"]["files"] == 2
    assert impact.find_code(hist, feature="ingestion", text="kettle")["files"] == []
    with pytest.raises(SddError) as none:
        impact.find_code(hist)
    assert none.value.code == "invalid_input"
    with pytest.raises(SddError) as missing:
        impact.find_code(hist, table="nope")
    assert missing.value.code == "node_not_found"


def test_find_code_table_reads_mentions_and_migration_paths(
    history_runtime: MakeHistory,
) -> None:
    runtime = history_runtime(
        before=lambda root: write_files(
            root,
            {
                "db/migrations/001_chunks.sql": "create table chunks();\n",
                "db/other/chunks.sql": "x\n",
            },
        )
    )
    files = {f["path"]: f["via"] for f in impact.find_code(runtime, table="chunks")["files"]}
    assert files["db/migrations/001_chunks.sql"] == [
        "table:chunks",
        "~PATH",
        "file:db/migrations/001_chunks.sql",
    ]
    assert "db/other/chunks.sql" not in files
    assert "src/ingest/chunker.py" in files  # the feature uses chunks
    docs = impact.find_code(runtime, table="documents")
    assert "src/ingest/loader.py" in {f["path"] for f in docs["files"]}


def test_spec06_ac06_ambiguous_target(hist: Runtime) -> None:
    with pytest.raises(SddError) as err:
        impact.impact(hist, "id")
    assert err.value.code == "ambiguous_target"
    assert err.value.details["candidates"] == ["column:chunks.id", "column:documents.id"]
    assert impact.impact(hist, "column:chunks.id")["target"]["id"] == "column:chunks.id"
    assert impact.impact(hist, "chunks.id")["target"]["id"] == "column:chunks.id"


def test_ambiguous_table_and_feature_with_one_name(history_runtime: MakeHistory) -> None:
    def rename(root: Path) -> None:
        path = "docs/specs/SPEC-02-ingest-schema.md"
        text = (root / path).read_text(encoding="utf-8")
        write_files(root, {path: text.replace("Feature:** Ingestion", "Feature:** Chunks")})

    runtime = history_runtime(before=rename)
    with pytest.raises(SddError) as err:
        impact.impact(runtime, "chunks")
    assert err.value.code == "ambiguous_target"
    assert "feature:chunks" in err.value.details["candidates"]
    assert "table:chunks" in err.value.details["candidates"]


def test_target_forms_and_errors(hist: Runtime) -> None:
    store = hist.store
    assert impact.resolve_target(store, "SPEC-02 §2") == ("SPEC-02#2", "Section")
    assert impact.resolve_target(store, "spec-2") == ("SPEC-02", "Spec")
    assert impact.resolve_target(store, "m2.1") == ("M02.1", "Task")
    assert impact.resolve_target(store, "Ingestion") == ("feature:ingestion", "Feature")
    assert impact.resolve_target(store, "src/ingest/loader.py") == (
        "file:src/ingest/loader.py",
        "File",
    )
    assert impact.resolve_target(store, "SPEC-02 `chunks`") == ("SPEC-02#3", "Section")
    for raw, code in (
        ("nothing-here", "node_not_found"),
        ("table:nope", "node_not_found"),
        ("SPEC-09", "node_not_found"),
        ("", "invalid_input"),
    ):
        with pytest.raises(SddError) as err:
            impact.resolve_target(store, raw)
        assert err.value.code == code
    for depth in (0, 6, True, "3"):
        with pytest.raises(SddError) as bad:
            impact.impact(hist, "documents", depth=depth)  # type: ignore[arg-type]
        assert bad.value.code == "invalid_input"


def test_depth_cuts_the_chains(hist: Runtime) -> None:
    deep = impact.impact(hist, "documents", depth=3)
    shallow = impact.impact(hist, "documents", depth=1)
    one = {i["id"] for items in shallow["groups"].values() for i in items}
    assert "table:chunks" in one  # REFERENCES plus containment: one hop
    assert "feature:ingestion" in one
    assert "file:src/ingest/loader.py" not in one  # USES_TABLE then IMPLEMENTED_IN: two hops
    assert shallow["counts"]["files"] == 0
    assert deep["counts"]["files"] == 3
    assert all(hops(i["via"]) <= 1 for items in shallow["groups"].values() for i in items)


def test_hops_do_not_count_containment() -> None:
    assert hops(["table:documents", "->HAS_COLUMN", "column:documents.id"]) == 0
    assert hops(["SPEC-02", "->HAS_SECTION", "SPEC-02#2", "<-AMENDS", "D002"]) == 1
    assert hops(["a", "<-REFERENCES", "b", "<-HAS_COLUMN", "c"]) == 1


def test_spec06_ac07_group_limit(history_runtime: MakeHistory) -> None:
    runtime = history_runtime(
        before=lambda root: write_files(
            root, {f"src/ingest/gen/g{i:03}.py": f"x = {i}\n" for i in range(120)}
        )
    )
    r = impact.impact(runtime, "feature:ingestion")
    assert len(r["groups"]["files"]) == 50
    assert r["counts"]["files"] == 123  # 120 generated plus __init__, chunker and loader
    ids = [i["id"] for i in r["groups"]["files"]]
    assert ids == sorted(ids)
    for group in impact.GROUPS:
        assert group in r["counts"]


def test_named_queries_load_and_cover_the_service() -> None:
    loaded = queries.load()
    assert set(loaded) >= impact.QUERY_NAMES
    for name in ("resolve.node", "explain.file", "find.text", "presets.nodes"):
        assert name in loaded
    assert queries.get("resolve.node").startswith("MATCH")
    with pytest.raises(KeyError):
        queries.get("no.such.query")


def test_named_query_files_reject_duplicates() -> None:
    text = "// name: a.b\nMATCH (n) RETURN n\n// name: a.b\nMATCH (m) RETURN m\n"
    with pytest.raises(ValueError, match="duplicate"):
        queries._parse(text, "x.cypher")
