"""SPEC-02 §8 checks 2–5 (graph side), the Task upsert rules of SPEC-04 §2.1 as pure tests, and
the relationship-type table drift guard."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sdd.graph import schema
from sdd.graph.store import Store
from sdd.graph.upsert import MergeFlags, merge_props, task_status
from sdd.ids import new_ulid
from tests.conftest import MakeProject
from tests.graph_dump import Clock, counts, dump, mini_project, sync_project, write_files

SPEC_02 = Path(__file__).resolve().parents[2] / "docs" / "specs" / "SPEC-02-graph-schema.md"
NOW = "2026-11-22T10:00:00Z"
LATER = "2026-11-22T11:00:00Z"


# ---------------------------------------------------------------- schema drift


def test_rel_types_match_the_spec_table() -> None:
    text = SPEC_02.read_text(encoding="utf-8")
    start = text.index("## 4. Relationships")
    table = text[start : text.index("## 5. Unresolved links")]
    types = re.findall(r"^\| `([A-Z_]+)` \|", table, re.MULTILINE)
    assert tuple(types) == schema.REL_TYPES


def test_new_ulid_is_crockford_and_sortable() -> None:
    t = datetime(2026, 11, 22, tzinfo=UTC)
    a, b = new_ulid(t), new_ulid(t + timedelta(milliseconds=5))
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", a)
    assert a[:10] < b[:10]
    assert new_ulid(t, bytes(10)) == new_ulid(t, bytes(10))


# ---------------------------------------------------------------- merge_props (SPEC-04 §2.1)


def _task(checked: bool, **extra: object) -> dict[str, object]:
    return {"checked": checked, "title": "t", "milestone_id": "M01", **extra}


def _merge(
    existing: dict[str, object] | None,
    parsed: dict[str, object],
    *,
    initial: bool = False,
    writeback: bool = True,
) -> tuple[dict[str, object], MergeFlags]:
    return merge_props(
        "Task", existing, parsed, now=LATER, initial=initial, writeback=writeback, spec_existed=True
    )


def test_task_new_has_no_graph_only_state_even_when_ticked() -> None:
    props, flags = _merge(None, _task(True))
    assert props["status"] == "done"
    assert "done_at" not in props
    assert not flags.ticked


def test_task_unchanged_checked_keeps_graph_only_state() -> None:
    existing = _task(False, claimed_by="a", claimed_at=NOW, notes="n", id="M01.1")
    props, flags = _merge(existing, _task(False, title="renamed"))
    assert (props["claimed_by"], props["claimed_at"], props["notes"]) == ("a", NOW, "n")
    assert props["title"] == "renamed"
    assert props["status"] == "claimed"
    assert not flags.ticked
    assert not flags.unticked


def test_task_ticked_by_hand_sets_done_at_and_clears_claim() -> None:
    existing = _task(False, claimed_by="a", claimed_at=NOW, notes="n")
    props, flags = _merge(existing, _task(True))
    assert props["done_at"] == LATER
    assert "claimed_by" not in props
    assert "claimed_at" not in props
    assert props["notes"] == "n"
    assert props["status"] == "done"
    assert flags.ticked


def test_task_ticked_keeps_an_existing_done_at() -> None:
    props, _ = _merge(_task(False, done_at=NOW), _task(True))
    assert props["done_at"] == NOW


def test_task_ticked_in_initial_sync_sets_no_done_at() -> None:
    props, flags = _merge(_task(False), _task(True), initial=True)
    assert "done_at" not in props
    assert not flags.ticked


def test_task_unticked_clears_done_at_and_completed_by_keeps_notes() -> None:
    existing = _task(True, done_at=NOW, completed_by="a", notes="n")
    props, flags = _merge(existing, _task(False))
    assert "done_at" not in props
    assert "completed_by" not in props
    assert props["notes"] == "n"
    assert props["status"] == "todo"
    assert flags.unticked


def test_task_status_derivation() -> None:
    assert task_status({"checked": True}, True) == "done"
    assert task_status({"checked": False, "claimed_by": "a"}, True) == "claimed"
    assert task_status({"checked": False}, True) == "todo"
    assert task_status({"checked": False, "completed_by": "a"}, True) == "todo"
    assert task_status({"checked": False, "completed_by": "a"}, False) == "done"


def test_section_changed_at_rules() -> None:
    def merge(existing: dict[str, object] | None, h: str, *, initial: bool, spec: bool) -> object:
        props, _ = merge_props(
            "Section",
            existing,
            {"content_hash": h},
            now=LATER,
            initial=initial,
            writeback=True,
            spec_existed=spec,
        )
        return props.get("changed_at")

    assert merge(None, "h", initial=True, spec=False) is None
    assert merge(None, "h", initial=False, spec=False) is None  # new spec
    assert merge(None, "h", initial=False, spec=True) == LATER  # new section in an old spec
    assert merge({"content_hash": "h", "changed_at": NOW}, "h", initial=False, spec=True) == NOW
    assert merge({"content_hash": "old", "changed_at": NOW}, "h", initial=False, spec=True) == LATER
    assert merge({"content_hash": "old"}, "h", initial=True, spec=True) is None


# ---------------------------------------------------------------- SPEC-02 §8 checks 2–5


def test_spec02_ac02_resync_idempotent(project: MakeProject, store: Store) -> None:
    root = project("suite_style")
    clock = Clock()
    sync_project(root, store, clock)
    first = counts(store), dump(store, drop_props={"last_synced"}, drop_labels={"Meta"})
    clock.tick()
    report = sync_project(root, store, clock)
    assert report.changed == []
    assert report.created == 0
    assert (counts(store), dump(store, drop_props={"last_synced"}, drop_labels={"Meta"})) == first


def test_spec02_ac03_removed_link_removes_exactly_that_rel(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    sync_project(root, store)
    before = store.read("MATCH (a)-[:LINKS_TO]->(b) RETURN a.id AS a, b.id AS b")
    assert before == [{"a": "SPEC-01#1", "b": "SPEC-02#1"}]
    rels_before = dump(store, drop_props={"last_synced"}, drop_labels={"Event"})[1]
    spec = (root / "docs/specs/SPEC-01-alpha.md").read_text(encoding="utf-8")
    link = "See [SPEC-02 §1](SPEC-02-beta.md#1-one) for details."
    write_files(root, {"docs/specs/SPEC-01-alpha.md": spec.replace(link, "See nothing.")})
    sync_project(root, store)
    rels_after = dump(store, drop_props={"last_synced"}, drop_labels={"Event"})[1]
    removed = rels_before - rels_after
    assert [k[:3] for k in removed] == [("LINKS_TO", "SPEC-01#1", "SPEC-02#1")]
    assert rels_after - rels_before == {}


def test_spec02_ac04_missing_section_is_unresolved(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    ms = (root / "docs/milestones/M01-first.md").read_text(encoding="utf-8")
    write_files(
        root,
        {
            "docs/milestones/M01-first.md": ms.replace(
                "[SPEC-02 §2](../specs/SPEC-02-beta.md#2-two)",
                "[SPEC-02 §9](../specs/SPEC-02-beta.md#9-gone)",
            )
        },
    )
    sync_project(root, store)
    rows = store.read("MATCH (m:Milestone {id: 'M01'}) RETURN m.unresolved AS u")
    assert rows == [{"u": ["SPEC-02#9"]}]
    targets = store.read("MATCH (:Milestone {id: 'M01'})-[:READS]->(s) RETURN s.id AS id")
    assert [r["id"] for r in targets] == ["SPEC-01#1"]


def test_spec02_ac05_file_nodes_hold_no_contents(project: MakeProject, store: Store) -> None:
    sync_project(project("tool_style"), store)
    files = store.read("MATCH (f:File) RETURN properties(f) AS p")
    assert files
    for row in files:
        assert set(row["p"]) == {"id", "path", "name", "content_hash", "last_synced"}
        assert row["p"]["id"] == f"file:{row['p']['path']}"


def test_every_sdd_file_has_a_file_node(project: MakeProject, store: Store) -> None:
    report = sync_project(project("rag_style"), store)
    n = store.read("MATCH (f:File) RETURN count(f) AS n")[0]["n"]
    assert n == report.scanned


def test_meta_node(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync_project(root, store, Clock())
    meta = store.read("MATCH (m:Meta) RETURN properties(m) AS p")[0]["p"]
    assert meta["schema_version"] == schema.SCHEMA_VERSION
    assert meta["project_name"] == root.name
    assert meta["last_full_sync"] == "2026-11-22T10:00:00Z"
