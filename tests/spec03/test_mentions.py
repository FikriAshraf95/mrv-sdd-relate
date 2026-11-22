"""SPEC-03 §3.2, §5.1 and §7 check 9: MENTIONS and AFFECTS resolved against Tables and Files
(plan M04b §3). Real stores; ``tool_style`` copied into ``tmp_path``."""

from __future__ import annotations

from sdd.graph.store import Store
from sdd.sync import indexer
from tests.conftest import MakeProject
from tests.graph_dump import Sync, dump, write_files


def _pairs(store: Store, type_: str, source: str | None = None) -> set[tuple[str, str]]:
    rows = store.read(f"MATCH (a)-[:{type_}]->(b) RETURN a.id AS a, b.id AS b")
    return {(r["a"], r["b"]) for r in rows if source is None or r["a"] == source}


def test_spec03_ac09_deviation_task_and_affects(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    assert _pairs(store, "RAISED_IN", "D002") == {("D002", "M02"), ("D002", "M02.1")}
    assert _pairs(store, "AFFECTS", "D002") == {
        ("D002", "file:src/ingest/loader.py"),
        ("D002", "table:documents"),
    }
    before = dump(store, drop_props={"last_synced", "last_full_sync"})
    indexer.reset(store)
    sync = Sync(root, store)  # a cold process after `sdd sync --reset --yes`
    report = sync.full()
    assert dump(store, drop_props={"last_synced", "last_full_sync"}) == before
    # D001 has Affects entries too; only `brews` (no such table) is unresolved, and no warning
    assert report.unresolved["D001"] == ["brews"]
    assert [w for w in report.warnings if w.path.endswith("D001-steep-time-default.md")] == []


def test_task_and_section_mention_a_table(project: MakeProject, store: Store) -> None:
    Sync(project("tool_style"), store).full()
    mentions = _pairs(store, "MENTIONS")
    assert ("M02.1", "table:documents") in mentions  # the task line mentions `documents`
    assert ("D002", "table:documents") in mentions  # so does the deviation body


def test_mention_of_a_code_file_follows_it_in_the_same_batch(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style")
    write_files(
        root,
        {
            "docs/specs/SPEC-03-extras.md": (
                "# SPEC-03 — Extras\n\n> **Status:** v1\n\n## 1. Notes\n\n"
                "The helper lives in `src/extra/later.py`.\n"
            )
        },
    )
    sync = Sync(root, store)
    sync.full()
    assert ("SPEC-03#1", "file:src/extra/later.py") not in _pairs(store, "MENTIONS")
    write_files(root, {"src/extra/later.py": "x = 1\n"})
    report = sync.batch("src/extra/later.py")
    assert report.indexed is True
    assert ("SPEC-03#1", "file:src/extra/later.py") in _pairs(store, "MENTIONS")
    write_files(root, {"src/extra/later.py": None})
    sync.batch("src/extra/later.py")
    assert ("SPEC-03#1", "file:src/extra/later.py") not in _pairs(store, "MENTIONS")


def test_affects_entry_resolves_when_the_file_appears(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    path = "docs/deviations/D002-document-title-optional.md"
    text = (root / path).read_text(encoding="utf-8")
    write_files(root, {path: text.replace("`src/ingest/loader.py`", "`src/ingest/late.py`")})
    sync = Sync(root, store)
    report = sync.full()
    assert report.unresolved["D002"] == ["src/ingest/late.py"]
    assert store.read("MATCH (d:Deviation {id: 'D002'}) RETURN d.unresolved AS u") == [
        {"u": ["src/ingest/late.py"]}
    ]
    write_files(root, {"src/ingest/late.py": "x = 1\n"})
    report = sync.batch("src/ingest/late.py")
    assert "D002" not in report.unresolved
    assert ("D002", "file:src/ingest/late.py") in _pairs(store, "AFFECTS")


def test_unchanged_resync_with_mentions_writes_nothing(project: MakeProject, store: Store) -> None:
    sync = Sync(project("tool_style"), store)
    sync.full()
    second = sync.full()
    assert (second.changed, second.removed, second.relinked) == ([], [], 0)
