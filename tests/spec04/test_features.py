"""SPEC-03 §3.3 and SPEC-04 §4: Feature and Domain nodes, shared across specs, and the glob
expansion of ``IMPLEMENTED_IN`` (plan M04b §2). Real stores; ``tool_style`` copied into
``tmp_path``."""

from __future__ import annotations

from sdd.graph.store import Store
from tests.conftest import MakeProject
from tests.graph_dump import Sync, dump, write_files

SPEC_03 = """# SPEC-03 — Ingest extras

> **Status:** v1
> **Feature:** Ingestion · **Domain:** Library · **Implements:** `src/extra/**` · **Tables:** chunks

## 1. Overview

Nothing.
"""


def _pairs(store: Store, type_: str) -> set[tuple[str, str]]:
    rows = store.read(f"MATCH (a)-[:{type_}]->(b) RETURN a.id AS a, b.id AS b")
    return {(r["a"], r["b"]) for r in rows}


def test_spec03_ac08_feature_line_graph(project: MakeProject, store: Store) -> None:
    Sync(project("tool_style"), store).full()
    features = store.read(
        "MATCH (f:Feature) RETURN f.id AS id, f.name AS n, f.globs AS g ORDER BY id"
    )
    assert features == [
        {"id": "feature:brewing", "n": "Brewing", "g": ["src/kettle/**"]},
        {"id": "feature:ingestion", "n": "Ingestion", "g": ["src/ingest/**"]},
    ]
    assert [r["id"] for r in store.read("MATCH (d:Domain) RETURN d.id AS id ORDER BY id")] == [
        "domain:library",
        "domain:tea",
    ]
    assert _pairs(store, "SPECIFIED_BY") == {
        ("feature:brewing", "SPEC-01"),
        ("feature:ingestion", "SPEC-02"),
    }
    assert _pairs(store, "BELONGS_TO") == {
        ("feature:brewing", "domain:tea"),
        ("feature:ingestion", "domain:library"),
    }
    assert _pairs(store, "USES_TABLE") == {
        ("feature:ingestion", "table:documents"),
        ("feature:ingestion", "table:chunks"),
    }
    # brews and teas are defined nowhere: listed on the declaring Spec
    spec = store.read("MATCH (s:Spec {id: 'SPEC-01'}) RETURN s.unresolved AS u")
    assert spec == [{"u": ["table:brews", "table:teas"]}]
    assert {f for _, f in _pairs(store, "IMPLEMENTED_IN") if f.startswith("file:src/ingest/")} == {
        "file:src/ingest/__init__.py",
        "file:src/ingest/chunker.py",
        "file:src/ingest/loader.py",
    }
    # Feature and Domain carry no source_path
    assert (
        store.read(
            "MATCH (n) WHERE (n:Feature OR n:Domain) AND n.source_path IS NOT NULL RETURN n.id"
        )
        == []
    )


def test_feature_declared_in_two_specs_is_one_node(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    write_files(
        root,
        {
            "docs/specs/SPEC-03-extras.md": SPEC_03,
            "src/extra/a.py": "x = 1\n",
        },
    )
    sync = Sync(root, store)
    sync.full()
    assert store.read("MATCH (f:Feature {id: 'feature:ingestion'}) RETURN f.globs AS g") == [
        {"g": ["src/extra/**", "src/ingest/**"]}
    ]
    assert {s for f, s in _pairs(store, "SPECIFIED_BY") if f == "feature:ingestion"} == {
        "SPEC-02",
        "SPEC-03",
    }
    assert "file:src/extra/a.py" in {b for a, b in _pairs(store, "IMPLEMENTED_IN")}
    # removing one spec keeps the node, with its remaining declaration
    write_files(root, {"docs/specs/SPEC-03-extras.md": None})
    sync.batch("docs/specs/SPEC-03-extras.md")
    assert store.read("MATCH (f:Feature {id: 'feature:ingestion'}) RETURN f.globs AS g") == [
        {"g": ["src/ingest/**"]}
    ]
    assert {s for f, s in _pairs(store, "SPECIFIED_BY") if f == "feature:ingestion"} == {"SPEC-02"}
    assert "file:src/extra/a.py" not in {b for a, b in _pairs(store, "IMPLEMENTED_IN")}


def test_feature_and_domain_go_when_no_spec_declares_them(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    write_files(root, {"docs/specs/SPEC-01-timer.md": None})
    sync.batch("docs/specs/SPEC-01-timer.md")
    assert [r["id"] for r in store.read("MATCH (f:Feature) RETURN f.id AS id")] == [
        "feature:ingestion"
    ]
    assert [r["id"] for r in store.read("MATCH (d:Domain) RETURN d.id AS id")] == ["domain:library"]


def test_glob_expansion_follows_file_add_and_remove(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    write_files(root, {"src/ingest/new.py": "y = 2\n"})
    sync.batch("src/ingest/new.py")
    assert ("feature:ingestion", "file:src/ingest/new.py") in _pairs(store, "IMPLEMENTED_IN")
    write_files(root, {"src/ingest/loader.py": None})
    sync.batch("src/ingest/loader.py")
    implemented = _pairs(store, "IMPLEMENTED_IN")
    assert ("feature:ingestion", "file:src/ingest/loader.py") not in implemented
    assert ("feature:ingestion", "file:src/ingest/new.py") in implemented
    srcs = store.read("MATCH (:Feature)-[r:IMPLEMENTED_IN]->() RETURN DISTINCT r.src AS s")
    assert srcs == [{"s": "walker"}]


def test_feature_glob_empty_warning(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    write_files(
        root,
        {"docs/specs/SPEC-03-extras.md": SPEC_03.replace("Ingestion", "Extras")},
    )
    sync = Sync(root, store)
    report = sync.full()  # src/extra has no file
    empty = [w for w in report.warnings if w.code == "feature_glob_empty"]
    assert [(w.path, w.line, w.severity) for w in empty] == [
        ("docs/specs/SPEC-03-extras.md", 4, "warning")
    ]
    assert "src/extra/**" in empty[0].message
    write_files(root, {"src/extra/a.py": "x = 1\n"})
    sync.batch("src/extra/a.py")
    again = sync.batch("docs/specs/SPEC-03-extras.md")  # an indexer run, now matching
    assert [w for w in again.warnings if w.code == "feature_glob_empty"] == []


def test_resync_of_features_writes_nothing(project: MakeProject, store: Store) -> None:
    sync = Sync(project("tool_style"), store)
    sync.full()
    before = dump(store, drop_props={"last_synced", "last_full_sync"})
    second = sync.full()
    assert dump(store, drop_props={"last_synced", "last_full_sync"}) == before
    assert second.created == second.updated == second.deleted == 0
