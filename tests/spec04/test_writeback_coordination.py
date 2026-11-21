"""SPEC-04 §5 write-back through the coordination tools: deviations, hand edits, moves, ticks."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from sdd.errors import SddError
from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from sdd.sync import indexer
from tests.conftest import MakeRuntime
from tests.spec05.helpers import INDEX, M02, MILESTONE, SPEC, claims_on, events, read, task

DEVIATION: dict[str, Any] = {
    "spec_says": "Fixed.",
    "implementation_does": "Configurable.",
    "why": "Testing.",
    "amends": ["SPEC-01 §2"],
}


# ---------------------------------------------------------------- check 7


def test_spec04_ac07_concurrent_deviations_get_consecutive_numbers(runtime: Runtime) -> None:
    barrier = threading.Barrier(2)

    def log(n: int) -> dict[str, Any]:
        barrier.wait()
        return coord.log_deviation(
            runtime, "M01.2", f"agent-{n}", title=f"Parallel change {n}", **DEVIATION
        )

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(log, range(2)))
    ids = sorted(r["id"] for r in results)
    assert ids == ["D003", "D004"]
    root = runtime.settings.project_root
    files = sorted(p.name for p in (root / "docs/deviations").iterdir())
    assert len(files) == 4
    assert files[2].startswith("D003-parallel-change-")
    assert files[3].startswith("D004-parallel-change-")
    index = read(runtime, INDEX).splitlines()
    # newest first: the later job's row went on top of the earlier one's
    assert index[4].startswith("| [D004]")
    assert index[5].startswith("| [D003]")
    assert index[6].startswith("| [D002]")
    assert index[7].startswith("| [D001]")
    spec = read(runtime, SPEC)
    assert spec.count("> **DEVIATION:** see [D003]") == 1
    assert spec.count("> **DEVIATION:** see [D004]") == 1
    # both notes sit in §2's own body, each after a blank line
    teas = spec.split("## 2. Teas", 1)[1].split("## 3.", 1)[0]
    assert "\n\n> **DEVIATION:** see [D003]" in teas or "\n\n> **DEVIATION:** see [D004]" in teas
    report = indexer.sync(runtime.store, runtime.settings, full=False)
    assert report.changed == []  # the jobs re-synced their own edits (loop prevention)
    assert [w for w in report.warnings if w.code == "deviation_index_mismatch"] == []


# ---------------------------------------------------------------- check 10


def test_spec04_ac10_hand_edit_between_claim_and_complete(runtime: Runtime) -> None:
    path = runtime.settings.project_root / MILESTONE
    coord.claim_task(runtime, "M01.1", "a")
    text = path.read_text(encoding="utf-8")
    edited = text.replace("Brew model with default steep times", "Brew model, renamed by hand")
    path.write_text("Intro line added by hand.\n\n" + edited, encoding="utf-8", newline="\n")
    coord.complete_task(runtime, "M01.1", "a")  # no sync in between: the line moved down by 2
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "- [x] **M01.1** Brew model, renamed by hand" in "\n".join(lines)
    assert sum(1 for ln in lines if ln.lstrip().startswith("- [x]")) == 2  # M01.1 and M01.4

    coord.claim_task(runtime, "M01.2", "a")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        "\n".join(ln for ln in text.split("\n") if "**M01.2**" not in ln),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(SddError) as info:
        coord.complete_task(runtime, "M01.2", "a")
    assert info.value.code == "source_changed"
    assert task(runtime, "M01.2")["status"] == "claimed"  # the graph did not change
    assert task(runtime, "M01.2")["claimed_by"] == "a"


# ---------------------------------------------------------------- check 12


def test_spec04_ac12_complete_milestone_moves_and_rewrites_links(runtime: Runtime) -> None:
    root = runtime.settings.project_root
    (root / "docs/milestones/done").mkdir()
    (root / "docs/milestones/M02-brew-log.md").write_text(M02, encoding="utf-8")
    (root / "docs/milestones/M01-plan.md").write_text(
        "# M01 plan\n\nSee [the milestone](M01-timer.md#goal) and "
        "[SPEC-01](../specs/SPEC-01-timer.md).\n",
        encoding="utf-8",
    )
    runtime.sync(full=True)
    for tid in ("M01.1", "M01.2", "M01.3"):
        coord.claim_task(runtime, tid, "a")
        coord.complete_task(runtime, tid, "a")

    result = coord.complete_milestone(runtime, "M01", "opus-orch", "Walkthrough done")
    assert result["moved_from"] == MILESTONE
    assert result["path"] == "docs/milestones/done/M01-timer.md"
    assert not (root / MILESTONE).exists()
    moved = read(runtime, "docs/milestones/done/M01-timer.md")
    assert "[SPEC-01 §1](../../specs/SPEC-01-timer.md#1-brewing)" in moved  # own links re-based
    assert "[M01](done/M01-timer.md)" in read(runtime, "docs/milestones/M02-brew-log.md")
    plan = read(runtime, "docs/milestones/done/M01-plan.md")
    assert "[the milestone](M01-timer.md#goal)" in plan
    assert "[SPEC-01](../../specs/SPEC-01-timer.md)" in plan

    rows = runtime.store.read(
        "MATCH (m:Milestone {id: 'M01'}) RETURN m.source_path AS p, m.status AS s"
    )
    assert rows[0] == {"p": "docs/milestones/done/M01-timer.md", "s": "done"}
    assert not runtime.store.read(
        "MATCH (f:File {id: $id}) RETURN f.id", {"id": f"file:{MILESTONE}"}
    )

    report = runtime.sync(full=True)
    assert report["changed"] == []  # the job re-synced the moved and rewritten files
    # D001's Affects entries wait for code File and Table nodes (M04a/M04b)
    assert set(report["unresolved"]) <= {"D001", "D002"}
    assert [w for w in report["warnings"] if w["code"] == "link_moved"] == []


def test_complete_milestone_keeps_an_active_claim_on_another_milestone(runtime: Runtime) -> None:
    root = runtime.settings.project_root
    (root / "docs/milestones/done").mkdir()
    runtime.sync(full=True)
    for tid in ("M01.1", "M01.2", "M01.3"):
        coord.claim_task(runtime, tid, "a")
        coord.complete_task(runtime, tid, "a")
    (root / "docs/milestones/M02-brew-log.md").write_text(M02, encoding="utf-8")
    runtime.sync(full=True)
    coord.complete_milestone(runtime, "M01", "opus-orch", "ok")
    coord.claim_task(runtime, "M02.1", "b")
    assert task(runtime, "M02.1")["claimed_by"] == "b"


# ---------------------------------------------------------------- check 13


def test_spec04_ac13_hand_tick_clears_the_claim(runtime: Runtime) -> None:
    coord.claim_task(runtime, "M01.1", "a")
    path = runtime.settings.project_root / MILESTONE
    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ] **M01.1**", "- [x] **M01.1**"),
        encoding="utf-8",
        newline="\n",
    )
    runtime.sync(full=False, files=indexer.discover(runtime.settings))
    t = task(runtime, "M01.1")
    assert t["status"] == "done"
    assert t.get("claimed_by") is None
    assert claims_on(runtime, "M01.1") == 0
    assert events(runtime, "task_completed")[-1]["actor"] == "human"


def test_spec04_ac13_writeback_off_completion_survives_resync(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime(toml="writeback = false\n")
    before = read(runtime, MILESTONE)
    coord.claim_task(runtime, "M01.1", "a")
    result = coord.complete_task(runtime, "M01.1", "a")
    assert result["changed_file"] is False
    assert read(runtime, MILESTONE) == before
    path = runtime.settings.project_root / MILESTONE
    path.write_text(before + "\nA note added by hand.\n", encoding="utf-8", newline="\n")
    report = runtime.sync(full=True)
    assert MILESTONE in report["changed"]
    t = task(runtime, "M01.1")
    assert (t["status"], t["checked"], t["completed_by"]) == ("done", False, "a")
    assert "M01.2" in [x["id"] for x in coord.next_tasks(runtime)["tasks"]]
