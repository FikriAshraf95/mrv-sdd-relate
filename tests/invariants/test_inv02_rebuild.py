"""SPEC-10 §4 invariant 2: ``sdd sync --reset`` reproduces everything except graph-only state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sdd import config
from sdd.graph import schema
from sdd.graph.store import Store, Tx
from sdd.service import indexing
from sdd.sync import indexer
from tests.conftest import MakeProject
from tests.graph_dump import Clock, claim, dump, write_files

GRAPH_ONLY_PROPS = {
    "last_synced",
    "changed_at",
    "claimed_by",
    "claimed_at",
    "completed_by",
    "done_at",
    "notes",
    "last_full_sync",
}


def _settings(root: Path, store_path: Path, clock: Clock) -> config.Settings:
    return config.load(root, str(store_path), env={}, clock=clock)


def _comparable(
    store: Store, claimed: set[str], milestones: set[str]
) -> tuple[dict[str, tuple[str, dict[str, Any]]], Any]:
    nodes, rels = dump(
        store,
        drop_labels={"Agent", "Event"},
        drop_props=GRAPH_ONLY_PROPS,
        drop_rel_types={"CLAIMED", "ABOUT"},
        drop_rel_srcs={"tool"},
    )
    for node_id in claimed | milestones:  # status derived from a claim is graph-only too
        label, props = nodes[node_id]
        nodes[node_id] = (label, {k: v for k, v in props.items() if k != "status"})
    return nodes, rels


@pytest.mark.parametrize("style", ["tool_style", "suite_style"])
def test_inv02_reset_reproduces_everything_but_graph_only_state(
    project: MakeProject, tmp_path: Path, style: str
) -> None:
    root = project(style)
    store_path = tmp_path / "graph"
    clock = Clock()
    settings = _settings(root, store_path, clock)

    with Store.open(store_path) as store:
        schema.ensure(store)
        indexer.full_sync(store, settings)
        todo = store.read(
            "MATCH (t:Task {checked: false}) RETURN t.id AS id, t.source_path AS p, "
            "t.source_line AS line, t.milestone_id AS m ORDER BY t.id"
        )
        assert len(todo) >= 2
        clock.tick()
        # a section edit
        spec = sorted((root / "docs/specs").glob("SPEC-*.md"))[0]
        write_files(
            root, {spec.relative_to(root).as_posix(): spec.read_text("utf-8") + "\nMore.\n"}
        )
        # a hand tick
        ticked = todo[0]
        lines = (root / ticked["p"]).read_text("utf-8").split("\n")
        lines[ticked["line"] - 1] = lines[ticked["line"] - 1].replace("[ ]", "[x]", 1)
        write_files(root, {ticked["p"]: "\n".join(lines)})
        # graph-only state: a claim, an Agent, an Event and a tool-owned TOUCHES
        claimed = todo[1]["id"]
        claim(store, claimed, "sonnet-1")

        def tool_state(tx: Tx) -> None:
            tx.run(
                "CREATE (:Event {id: 'event:01JTESTTESTTESTTESTTESTTES', kind: 'sync', "
                "actor: 'sync', at: 'x', target_id: $t, summary: 's'})",
                {"t": claimed},
            )
            tx.run(
                "MATCH (t:Task {id: $t}) MATCH (f:File) WHERE f.path = $p "
                "CREATE (t)-[:TOUCHES {src: 'tool'}]->(f)",
                {"t": claimed, "p": spec.relative_to(root).as_posix()},
            )

        store.write(tool_state)
        clock.tick()
        indexer.full_sync(store, settings)
        milestones = {todo[1]["m"], ticked["m"]}
        before = _comparable(store, {claimed}, milestones)
        assert store.read("MATCH (e:Event) RETURN count(e) AS n")[0]["n"] >= 2  # edit + tick
        assert store.read("MATCH ()-[r {src: 'tool'}]->() RETURN count(r) AS n")[0]["n"] >= 2

    clock.tick()
    result = indexing.sync(_settings(root, store_path, clock), reset=True)
    assert result["initial"] is True
    assert result["events"] == 0

    with Store.open(store_path, read_only=True) as store:
        after = _comparable(store, {claimed}, milestones)
        assert store.read("MATCH (e:Event) RETURN count(e) AS n") == [{"n": 0}]
    assert after[0] == before[0]
    assert after[1] == before[1]
