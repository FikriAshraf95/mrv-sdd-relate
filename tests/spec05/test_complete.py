"""SPEC-05 §2 tools 7–9: complete_task, log_deviation, complete_milestone (SPEC-05 §5–6)."""

from __future__ import annotations

import pytest

from sdd.errors import SddError
from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from tests.conftest import MakeRuntime
from tests.spec05.helpers import INDEX, MILESTONE, SPEC, Clock, events, read, task, use_clock

DEVIATION = {
    "title": "Countdown ticks every 100 ms",
    "spec_says": "The countdown updates every second.",
    "implementation_does": "It updates every 100 ms.",
    "why": "A smoother display.",
    "amends": ["SPEC-01 §2"],
}


def _code(call: object) -> str:
    with pytest.raises(SddError) as info:
        call()  # type: ignore[operator]
    return info.value.code


def _finish(runtime: Runtime, *task_ids: str, agent: str = "sonnet-1") -> None:
    for tid in task_ids:
        coord.claim_task(runtime, tid, agent)
        coord.complete_task(runtime, tid, agent)


# ---------------------------------------------------------------- check 7


def test_spec05_ac07_complete_task_ticks_records_and_unblocks(runtime: Runtime) -> None:
    coord.claim_task(runtime, "M01.1", "sonnet-1")
    result = coord.complete_task(
        runtime,
        "M01.1",
        "sonnet-1",
        notes="Brew model done",
        files_touched=["src/kettle/brew.py", "./src/kettle/brew.py"],
        commit="A1B2C3D",
    )
    assert result["status"] == "done"
    assert result["changed_file"] is True
    assert result["unblocked"] == [
        {"id": "M01.2", "title": "Countdown endpoint", "milestone_id": "M01"}
    ]
    assert "- [x] **M01.1** Brew model" in read(runtime, MILESTONE)
    t = task(runtime, "M01.1")
    assert (t["status"], t["completed_by"], t["notes"]) == ("done", "sonnet-1", "Brew model done")
    assert t.get("claimed_by") is None
    event = events(runtime, "task_completed")[-1]
    assert event["actor"] == "sonnet-1"
    assert event["data"] == {
        "notes": "Brew model done",
        "files_touched": ["src/kettle/brew.py"],
        "commit": "a1b2c3d",
    }


def test_complete_task_needs_the_claim(runtime: Runtime) -> None:
    assert _code(lambda: coord.complete_task(runtime, "M01.1", "a")) == "not_claimed_by_you"
    coord.claim_task(runtime, "M01.1", "a")
    assert _code(lambda: coord.complete_task(runtime, "M01.1", "b")) == "not_claimed_by_you"
    assert _code(lambda: coord.complete_task(runtime, "M01.1", "a", commit="xyz")) == (
        "invalid_input"
    )
    bad_path = ["../outside.py"]
    assert _code(lambda: coord.complete_task(runtime, "M01.1", "a", files_touched=bad_path)) == (
        "invalid_input"
    )
    assert task(runtime, "M01.1")["status"] == "claimed"


# ---------------------------------------------------------------- check 8


def test_spec05_ac08_complete_milestone(runtime: Runtime) -> None:
    use_clock(runtime, Clock())
    with pytest.raises(SddError) as info:
        coord.complete_milestone(runtime, "M01", "opus-orch", "Tests green")
    assert info.value.code == "milestone_incomplete"
    assert info.value.details["open"] == ["M01.1", "M01.2", "M01.3"]

    coord.claim_task(runtime, "M01.1", "sonnet-1")
    dev = coord.log_deviation(runtime, "M01.1", "sonnet-1", **DEVIATION)
    coord.complete_task(runtime, "M01.1", "sonnet-1")
    _finish(runtime, "M01.2", "M01.3")
    result = coord.complete_milestone(runtime, "M01", "opus-orch", "Tests green")

    line = f"**Status:** DONE (2026-12-01). Tests green. Deviations: D001, {dev['id']}."
    assert result["status_line"] == line
    assert result["deviations"] == ["D001", dev["id"]]
    assert result["moved_from"] is None  # the fixture has no done/ folder
    assert read(runtime, MILESTONE).rstrip("\n").endswith(line)
    rows = runtime.store.read("MATCH (m:Milestone {id: 'M01'}) RETURN m.status AS s")
    assert rows[0]["s"] == "done"
    assert events(runtime, "milestone_done")[-1]["actor"] == "opus-orch"


def test_complete_milestone_without_deviations_says_none(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime()
    for path in (runtime.settings.project_root / "docs/deviations").iterdir():
        path.unlink()
    (runtime.settings.project_root / INDEX).unlink()
    runtime.sync(full=True)
    _finish(runtime, "M01.1", "M01.2", "M01.3")
    result = coord.complete_milestone(runtime, "M01", "opus-orch", "ok")
    assert result["status_line"].endswith("ok. Deviations: none.")
    again = coord.complete_milestone(runtime, "M01", "opus-orch", "ok")
    assert again["files"] == []  # already DONE: nothing written twice


# ---------------------------------------------------------------- log_deviation (§5)


def test_log_deviation_writes_file_row_note_and_links(runtime: Runtime) -> None:
    result = coord.log_deviation(
        runtime, "M01.2", "sonnet-1", affects=["src/kettle/brew.py"], **DEVIATION
    )
    assert result["id"] == "D002"
    assert result["path"] == "docs/deviations/D002-countdown-ticks-every-100-ms.md"
    assert result["amends"] == ["SPEC-01#2"]
    text = read(runtime, result["path"])
    assert text.startswith("# D002 — Countdown ticks every 100 ms\n")
    assert "- **Date / milestone:** " in text
    assert " · M01 · M01.2\n" in text
    assert "- **Spec:** [SPEC-01 §2](../specs/SPEC-01-timer.md#2-teas)\n" in text
    assert "- **Affects:** `src/kettle/brew.py`\n" in text
    assert "## Consequences\nNone.\n" in text
    index = read(runtime, INDEX).splitlines()
    assert index[4].startswith("| [D002](deviations/D002-countdown-ticks-every-100-ms.md) |")
    assert index[5].startswith("| [D001]")
    assert (
        "> **DEVIATION:** see [D002](../deviations/D002-countdown-ticks-every-100-ms.md) — "
        "Countdown ticks every 100 ms"
    ) in read(runtime, SPEC)
    rels = runtime.store.read(
        "MATCH (d:Deviation {id: 'D002'})-[r]->(n) RETURN type(r) AS t, n.id AS id ORDER BY t, id"
    )
    pairs = {(r["t"], r["id"]) for r in rels}
    assert {("AMENDS", "SPEC-01#2"), ("RAISED_IN", "M01"), ("RAISED_IN", "M01.2")} <= pairs
    assert events(runtime, "deviation_logged")[-1]["target_id"] == "D002"


def test_log_deviation_on_a_whole_spec(runtime: Runtime) -> None:
    result = coord.log_deviation(runtime, "M01.2", "a", **{**DEVIATION, "amends": ["SPEC-01"]})
    lines = read(runtime, SPEC).splitlines()
    assert lines[2].startswith("> **Status:**")
    assert lines[3].startswith("> **Feature:**")
    assert lines[4] == ">"
    assert lines[5].startswith(f"> **DEVIATION:** see [{result['id']}]")


def test_log_deviation_errors_change_nothing(runtime: Runtime) -> None:
    before = {p: read(runtime, p) for p in (SPEC, INDEX)}

    def log(**overrides: object) -> str:
        return _code(
            lambda: coord.log_deviation(runtime, "M01.2", "a", **{**DEVIATION, **overrides})
        )

    assert log(amends=["SPEC-01 §9"]) == "unknown_section"
    assert log(amends=["nothing here"]) == "unknown_section"
    assert log(amends=[]) == "invalid_input"
    assert log(affects=["src/kettle/missing.py"]) == "invalid_input"
    assert log(title="") == "invalid_input"
    assert log(status="maybe") == "invalid_input"
    assert _code(lambda: coord.log_deviation(runtime, "M09.1", "a", **DEVIATION)) == (
        "task_not_found"
    )
    assert {p: read(runtime, p) for p in before} == before
    assert sorted(
        p.name for p in (runtime.settings.project_root / "docs/deviations").iterdir()
    ) == ["D001-steep-time-default.md"]


def test_writeback_off_refuses_deviations_and_milestones(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime(toml="writeback = false\n")
    assert _code(lambda: coord.log_deviation(runtime, "M01.2", "a", **DEVIATION)) == (
        "writeback_disabled"
    )
    assert _code(lambda: coord.complete_milestone(runtime, "M01", "a", "ok")) == (
        "writeback_disabled"
    )
