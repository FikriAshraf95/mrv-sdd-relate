"""SPEC-10 §4 invariant 3: upserts change the graph-only Task properties only in the cases of
SPEC-04 §2.1, and never delete a relationship with ``src = "tool"`` (the one exception is the
``CLAIMED`` relationship a hand tick clears, SPEC-04 §2.1)."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from sdd.graph.store import Store, Tx
from tests.conftest import MakeProject
from tests.graph_dump import Clock, claim, sync_project

PROPS = ("claimed_by", "claimed_at", "completed_by", "done_at", "notes")
MILESTONE = "docs/milestones/M01-timer.md"


def _graph_only(store: Store) -> dict[str, dict[str, Any]]:
    rows = store.read(
        "MATCH (t:Task) RETURN t.id AS id, t.claimed_by AS claimed_by, t.claimed_at AS claimed_at, "
        "t.completed_by AS completed_by, t.done_at AS done_at, t.notes AS notes"
    )
    return {r["id"]: {k: r[k] for k in PROPS} for r in rows}


def _tool_rels(store: Store) -> Counter[tuple[str, str, str]]:
    rows = store.read(
        "MATCH (a)-[r {src: 'tool'}]->(b) WHERE type(r) <> 'ABOUT' "
        "RETURN type(r) AS t, a.id AS a, b.id AS b"
    )
    return Counter((r["t"], r["a"], r["b"]) for r in rows)


def _edit(root: Path, old: str, new: str) -> None:
    path = root / MILESTONE
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def test_inv03_graph_only_state_changes_only_in_the_listed_cases(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style")
    clock = Clock()
    sync_project(root, store, clock)
    claim(store, "M01.2", "sonnet-1")

    def seed(tx: Tx) -> None:
        tx.run("MATCH (t:Task {id: 'M01.2'}) SET t.notes = 'n', t.completed_by = 'sonnet-1'")
        tx.run(
            "MATCH (t:Task {id: 'M01.2'}) MATCH (f:File {id: 'file:docs/specs/SPEC-01-timer.md'}) "
            "CREATE (t)-[:TOUCHES {src: 'tool'}]->(f)"
        )

    store.write(seed)
    base = _graph_only(store)
    tools = _tool_rels(store)
    assert base["M01.2"]["claimed_by"] == "sonnet-1"
    assert len(tools) == 2  # CLAIMED + TOUCHES

    # re-sync unchanged
    clock.tick()
    sync_project(root, store, clock)
    assert (_graph_only(store), _tool_rels(store)) == (base, tools)

    # edit a title (the claimed task, and another)
    clock.tick()
    _edit(root, "Countdown endpoint", "Countdown route")
    _edit(root, "Pause and resume", "Pause or resume")
    sync_project(root, store, clock)
    assert (_graph_only(store), _tool_rels(store)) == (base, tools)

    # hand tick of an unclaimed task: only that task's done_at appears
    now = clock.tick()
    _edit(root, "- [ ] **M01.3**", "- [x] **M01.3**")
    sync_project(root, store, clock)
    ticked = _graph_only(store)
    assert ticked == {**base, "M01.3": {**base["M01.3"], "done_at": now}}
    assert _tool_rels(store) == tools

    # untick: done_at goes, nothing else moves
    clock.tick()
    _edit(root, "- [x] **M01.3**", "- [ ] **M01.3**")
    sync_project(root, store, clock)
    assert (_graph_only(store), _tool_rels(store)) == (base, tools)

    # move the file: nothing changes
    clock.tick()
    (root / "docs/milestones/done").mkdir()
    shutil.move(root / MILESTONE, root / "docs/milestones/done/M01-timer.md")
    sync_project(root, store, clock)
    assert (_graph_only(store), _tool_rels(store)) == (base, tools)

    # hand tick of the claimed task: claim and CLAIMED go (the listed case), TOUCHES stays
    now = clock.tick()
    path = root / "docs/milestones/done/M01-timer.md"
    path.write_text(
        path.read_text("utf-8").replace("- [ ] **M01.2**", "- [x] **M01.2**"),
        encoding="utf-8",
        newline="\n",
    )
    sync_project(root, store, clock)
    final = _graph_only(store)
    assert final["M01.2"]["claimed_by"] is None
    assert final["M01.2"]["claimed_at"] is None
    assert final["M01.2"]["done_at"] == now
    assert (final["M01.2"]["notes"], final["M01.2"]["completed_by"]) == ("n", "sonnet-1")
    assert {k: v for k, v in final.items() if k != "M01.2"} == {
        k: v for k, v in base.items() if k != "M01.2"
    }
    assert _tool_rels(store) == Counter({k: v for k, v in tools.items() if k[0] == "TOUCHES"})
