"""SPEC-04 §7 checks 2–5 and 11 (through the full sync), plus the Task and Section rules of §2.1
and the delete/duplicate rules of §3. Real stores; fixtures copied into ``tmp_path``."""

from __future__ import annotations

import shutil
from pathlib import Path

from sdd.graph import upsert
from sdd.graph.store import Store
from sdd.graph.upsert import FileIn, NodeIn
from sdd.sync import indexer
from tests.conftest import MakeProject
from tests.graph_dump import (
    Clock,
    claim,
    counts,
    dump,
    events,
    mini_project,
    settings_for,
    sync_project,
    write_files,
)


def _edit(root: Path, rel: str, old: str, new: str) -> None:
    text = (root / rel).read_text(encoding="utf-8")
    assert old in text
    write_files(root, {rel: text.replace(old, new)})


def _prop(store: Store, label: str, node_id: str, prop: str) -> object:
    rows = store.read(f"MATCH (n:{label} {{id: $id}}) RETURN n.{prop} AS v", {"id": node_id})
    assert rows, f"no {label} {node_id}"
    return rows[0]["v"]


# ---------------------------------------------------------------- check 11: the initial sync


def test_spec04_ac11_initial_sync_resolves_forward_links_and_records_no_history(
    tmp_path: Path, store: Store
) -> None:
    root = mini_project(tmp_path)
    _edit(root, "docs/milestones/M01-first.md", "nothing\n", "[M02](M02-second.md)\n")
    _edit(root, "docs/milestones/M01-first.md", "**Depends on:**", "**Blocks:**")
    _edit(root, "docs/milestones/M01-first.md", "- [ ] **M01.1**", "- [x] **M01.1**")
    write_files(
        root,
        {
            "docs/milestones/M02-second.md": "# M02 — Second\n\n> **Depends on:** nothing\n\n"
            "## Tasks\n- [ ] **M02.1** Only task\n"
        },
    )
    report = sync_project(root, store)
    assert report.initial
    assert report.events == 0
    assert events(store) == []
    # a spec linking to a later spec, and a Blocks: to a later milestone, both resolve
    assert store.read("MATCH (a)-[:LINKS_TO]->(b) RETURN a.id AS a, b.id AS b") == [
        {"a": "SPEC-01#1", "b": "SPEC-02#1"}
    ]
    assert store.read("MATCH (a:Milestone)-[:DEPENDS_ON]->(b) RETURN a.id AS a, b.id AS b") == [
        {"a": "M02", "b": "M01"}
    ]
    assert store.read("MATCH (n) WHERE n.unresolved IS NOT NULL RETURN n.id AS id") == []
    assert store.read("MATCH (s:Section) WHERE s.changed_at IS NOT NULL RETURN s.id AS id") == []
    assert _prop(store, "Task", "M01.1", "status") == "done"
    assert _prop(store, "Task", "M01.1", "done_at") is None
    assert _prop(store, "Milestone", "M01", "status") == "in_progress"


# ---------------------------------------------------------------- check 2: nothing changed


def test_spec04_ac02_unchanged_resync_writes_nothing(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    clock = Clock()
    sync_project(root, store, clock)
    clock.tick()
    _edit(root, "docs/specs/SPEC-02-beta.md", "Text of two.", "Text of two, edited.")
    sync_project(root, store, clock)
    assert events(store) == [("section_changed", "sync", "SPEC-02#2")]
    before = counts(store), dump(store, drop_labels={"Meta"})
    clock.tick(30)
    report = sync_project(root, store, clock)
    assert report.changed == []
    assert report.removed == []
    assert report.relinked == 0
    assert report.events == 0
    assert (counts(store), dump(store, drop_labels={"Meta"})) == before
    assert events(store) == [("section_changed", "sync", "SPEC-02#2")]


def test_edited_section_gets_changed_at_and_one_event(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    clock = Clock()
    sync_project(root, store, clock)
    now = clock.tick()
    _edit(root, "docs/specs/SPEC-02-beta.md", "Text of two.", "Text of two, edited.")
    sync_project(root, store, clock)
    changed = store.read("MATCH (s:Section) WHERE s.changed_at IS NOT NULL RETURN s.id AS id")
    assert changed == [{"id": "SPEC-02#2"}]
    assert _prop(store, "Section", "SPEC-02#2", "changed_at") == now
    assert events(store) == [("section_changed", "sync", "SPEC-02#2")]
    about = store.read("MATCH (:Event)-[r:ABOUT]->(t) RETURN t.id AS id, r.src AS src")
    assert about == [{"id": "SPEC-02#2", "src": "tool"}]


def test_new_section_in_an_existing_spec_is_a_change_new_spec_is_not(
    tmp_path: Path, store: Store
) -> None:
    root = mini_project(tmp_path)
    clock = Clock()
    sync_project(root, store, clock)
    clock.tick()
    spec = (root / "docs/specs/SPEC-02-beta.md").read_text(encoding="utf-8")
    write_files(
        root,
        {
            "docs/specs/SPEC-02-beta.md": spec + "\n## 3. Three\n\nNew.\n",
            "docs/specs/SPEC-03-gamma.md": "# SPEC-03 — Gamma\n\n## 1. Only\n\nx\n",
        },
    )
    sync_project(root, store, clock)
    assert _prop(store, "Section", "SPEC-02#3", "changed_at") is not None
    assert _prop(store, "Section", "SPEC-03#1", "changed_at") is None
    assert events(store) == [
        ("section_changed", "sync", "SPEC-02#3"),
        ("spec_added", "sync", "SPEC-03"),
    ]


# ---------------------------------------------------------------- hand ticks (SPEC-04 §2.1)


def test_hand_tick_and_untick(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    clock = Clock()
    sync_project(root, store, clock)
    claim(store, "M01.1", "sonnet-1")
    store.write(lambda tx: tx.run("MATCH (t:Task {id: 'M01.1'}) SET t.notes = 'kept'"))
    now = clock.tick()
    _edit(root, "docs/milestones/M01-timer.md", "- [ ] **M01.1**", "- [x] **M01.1**")
    sync_project(root, store, clock)
    assert _prop(store, "Task", "M01.1", "done_at") == now
    assert _prop(store, "Task", "M01.1", "claimed_by") is None
    assert _prop(store, "Task", "M01.1", "status") == "done"
    assert store.read("MATCH ()-[r:CLAIMED]->(:Task {id: 'M01.1'}) RETURN r") == []
    assert store.read("MATCH (a:Agent) RETURN a.id AS id") == [{"id": "agent:sonnet-1"}]
    assert events(store) == [("task_completed", "human", "M01.1")]

    clock.tick()
    _edit(root, "docs/milestones/M01-timer.md", "- [x] **M01.1**", "- [ ] **M01.1**")
    sync_project(root, store, clock)
    assert _prop(store, "Task", "M01.1", "done_at") is None
    assert _prop(store, "Task", "M01.1", "notes") == "kept"
    assert _prop(store, "Task", "M01.1", "status") == "todo"
    assert events(store) == [("task_completed", "human", "M01.1")]


def test_writeback_off_keeps_a_tool_completion_done(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync_project(root, store, writeback=False)
    store.write(
        lambda tx: tx.run("MATCH (t:Task {id: 'M01.1'}) SET t.completed_by = 'a', t.done_at = 'x'")
    )
    _edit(root, "docs/milestones/M01-timer.md", "Brew model", "The brew model")
    sync_project(root, store, writeback=False)
    assert _prop(store, "Task", "M01.1", "status") == "done"
    assert _prop(store, "Task", "M01.1", "checked") is False


# ---------------------------------------------------------------- check 3: moves


def test_spec04_ac03_moving_a_milestone_keeps_its_claim(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    sync_project(root, store)
    claim(store, "M01.1", "opus-1")
    store.write(
        lambda tx: tx.run(
            "MATCH (t:Task {id: 'M01.1'}) MATCH (f:File {id: 'file:docs/specs/SPEC-01-alpha.md'}) "
            "CREATE (t)-[:TOUCHES {src: 'tool'}]->(f)"
        )
    )
    before_nodes, before_rels = dump(store, drop_props={"last_synced", "path", "source_path"})
    (root / "docs/milestones/done").mkdir()
    shutil.move(root / "docs/milestones/M01-first.md", root / "docs/milestones/done/M01-first.md")
    clock = Clock()
    clock.tick(5)
    report = sync_project(root, store, clock)
    assert report.removed == ["docs/milestones/M01-first.md"]
    assert report.changed == ["docs/milestones/done/M01-first.md"]
    assert _prop(store, "Task", "M01.1", "claimed_by") == "opus-1"
    assert _prop(store, "Milestone", "M01", "path") == "docs/milestones/done/M01-first.md"
    assert _prop(store, "Milestone", "M01", "source_path") == "docs/milestones/done/M01-first.md"
    assert _prop(store, "Task", "M01.2", "source_path") == "docs/milestones/done/M01-first.md"
    assert store.read("MATCH (:Agent)-[:CLAIMED]->(t:Task) RETURN t.id AS id") == [{"id": "M01.1"}]
    assert store.read("MATCH (:Task)-[r:TOUCHES]->(f:File) RETURN r.src AS s") == [{"s": "tool"}]
    after_nodes, after_rels = dump(store, drop_props={"last_synced", "path", "source_path"})
    # only the File node of the moved file differs; the planning graph is identical
    gone = {k for k in before_nodes if k not in after_nodes}
    new = {k for k in after_nodes if k not in before_nodes}
    assert gone == {"file:docs/milestones/M01-first.md"}
    assert new == {"file:docs/milestones/done/M01-first.md"}
    assert events(store) == []
    assert sum(after_rels.values()) == sum(before_rels.values())


# ---------------------------------------------------------------- check 4: deleted spec


def test_spec04_ac04_deleting_a_spec_unresolves_its_links(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    sync_project(root, store)
    write_files(root, {"docs/specs/SPEC-02-beta.md": None})
    sync_project(root, store, Clock())
    assert store.read("MATCH (n) WHERE n.spec_id = 'SPEC-02' OR n.id = 'SPEC-02' RETURN n") == []
    assert store.read("MATCH (:Milestone)-[r:READS]->(t) RETURN t.id AS id") == [
        {"id": "SPEC-01#1"}
    ]
    assert store.read("MATCH ()-[r:LINKS_TO]->() RETURN r") == []
    assert _prop(store, "Milestone", "M01", "unresolved") == ["SPEC-02#2"]
    assert _prop(store, "Section", "SPEC-01#1", "unresolved") == ["SPEC-02#1"]
    assert store.read("MATCH (f:File {id: 'file:docs/specs/SPEC-02-beta.md'}) RETURN f") == []
    assert ("spec_removed", "sync", "SPEC-02") in events(store)


# ---------------------------------------------------------------- check 5: added spec


def test_spec04_ac05_adding_a_spec_resolves_existing_links(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    clock = Clock()
    spec_b = root / "docs/specs/SPEC-02-beta.md"
    text = spec_b.read_text(encoding="utf-8")
    spec_b.unlink()
    sync_project(root, store, clock)
    assert _prop(store, "Milestone", "M01", "unresolved") == ["SPEC-02#2"]
    clock.tick()
    write_files(root, {"docs/specs/SPEC-02-beta.md": text})
    sync_project(root, store, clock)
    assert _prop(store, "Milestone", "M01", "unresolved") is None
    assert _prop(store, "Section", "SPEC-01#1", "unresolved") is None
    reads = store.read("MATCH (:Milestone)-[:READS]->(t) RETURN t.id AS id ORDER BY id")
    assert reads == [{"id": "SPEC-01#1"}, {"id": "SPEC-02#2"}]
    assert store.read("MATCH (a)-[:LINKS_TO]->(b) RETURN a.id AS a, b.id AS b") == [
        {"a": "SPEC-01#1", "b": "SPEC-02#1"}
    ]


def test_renamed_section_relinks_files_that_did_not_change(tmp_path: Path, store: Store) -> None:
    """D003: a link in an unchanged file resolves as soon as its target appears."""
    root = mini_project(tmp_path)
    sync_project(root, store)
    _edit(root, "docs/specs/SPEC-02-beta.md", "## 2. Two", "## 2. Deux")
    _edit(root, "docs/milestones/M01-first.md", "#2-two", "#2-deux")
    sync_project(root, store, Clock())
    assert _prop(store, "Milestone", "M01", "unresolved") is None


# ---------------------------------------------------------------- deletes of claimed tasks


def test_deleting_a_claimed_task_releases_it(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    clock = Clock()
    sync_project(root, store, clock)
    claim(store, "M01.2", "haiku-1")
    clock.tick()
    _edit(
        root,
        "docs/milestones/M01-timer.md",
        "- [ ] **M01.2** Countdown endpoint (after M01.1)\n",
        "",
    )
    sync_project(root, store, clock)
    assert store.read("MATCH (t:Task {id: 'M01.2'}) RETURN t") == []
    assert ("task_released", "sync", "M01.2") in events(store)


# ---------------------------------------------------------------- duplicates


def test_duplicate_id_first_path_wins(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    copy = (root / "docs/specs/SPEC-02-beta.md").read_text(encoding="utf-8")
    write_files(root, {"docs/specs/SPEC-02-copy.md": copy.replace("Text of two.", "Other.")})
    report = sync_project(root, store)
    dupes = [w for w in report.warnings if w.code == "duplicate_id"]
    assert dupes
    assert {w.path for w in dupes} == {"docs/specs/SPEC-02-copy.md"}
    assert all(w.severity == "warning" for w in dupes)
    assert _prop(store, "Spec", "SPEC-02", "source_path") == "docs/specs/SPEC-02-beta.md"
    assert _prop(store, "Section", "SPEC-02#2", "text") == "Text of two."
    # the losing file still has a File node
    assert store.read("MATCH (f:File {id: 'file:docs/specs/SPEC-02-copy.md'}) RETURN f.path AS p")


# ---------------------------------------------------------------- deviation index


def test_index_mismatch_is_reported(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    write_files(root, {"docs/deviations/D002-extra.md": "# D002 — Extra\n\n- **Status:** Open\n"})
    report = sync_project(root, store)
    assert any(w.code == "deviation_index_mismatch" for w in report.warnings)


def test_sync_stopped_after_phase_1_redoes_the_file(tmp_path: Path, store: Store) -> None:
    root = mini_project(tmp_path)
    clock = Clock()
    sync_project(root, store, clock)
    clock.tick()
    _edit(root, "docs/specs/SPEC-02-beta.md", "Text of two.", "Text of two, edited.")
    analysis = indexer.analyse(settings_for(root, clock))
    beta = next(f for f in analysis.files if f.path == "docs/specs/SPEC-02-beta.md")
    nodes = [NodeIn(n.label, n.id, dict(n.props)) for n in beta.result.nodes]
    store.write(
        lambda tx: upsert.upsert_file_nodes(
            tx,
            FileIn(beta.path, beta.content_hash),
            nodes,
            keep_ids=analysis.keep_ids,
            now=clock.tick(),
            initial=False,
            writeback=True,
        )
    )
    # phase 2 never ran: the stored hash is still the old one, so the next sync redoes the file
    assert upsert.read_state(store).files[beta.path] != beta.content_hash
    report = sync_project(root, store, clock)
    assert beta.path in report.changed
    assert upsert.read_state(store).files[beta.path] == beta.content_hash
