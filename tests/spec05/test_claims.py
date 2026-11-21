"""SPEC-05 §3 claims: next_tasks, claim_task, release_task, stale and forced releases."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from sdd.errors import SddError
from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from tests.spec05.helpers import (
    M02,
    M03,
    Clock,
    claims_on,
    events,
    task,
    use_clock,
    write_file,
)

TTL = 2 * 3600


def _ids(result: dict[str, object]) -> list[str]:
    return [t["id"] for t in result["tasks"]]  # type: ignore[attr-defined]


def _code(call: object) -> str:
    with pytest.raises(SddError) as info:
        call()  # type: ignore[operator]
    return info.value.code


# ---------------------------------------------------------------- check 1


def test_spec05_ac01_next_tasks_respects_blockers_and_milestone_deps(runtime: Runtime) -> None:
    write_file(runtime, "docs/milestones/M02-brew-log.md", M02)
    first = coord.next_tasks(runtime)
    # M01.2 waits for M01.1, M01.3 for M01.2, M02.1 for milestone M01; M01.4 is done
    assert _ids(first) == ["M01.1"]
    assert first["synced_at"]

    coord.claim_task(runtime, "M01.1", "sonnet-1")
    coord.complete_task(runtime, "M01.1", "sonnet-1")
    assert _ids(coord.next_tasks(runtime)) == ["M01.2"]

    for tid in ("M01.2", "M01.3"):
        coord.claim_task(runtime, tid, "sonnet-1")
        coord.complete_task(runtime, tid, "sonnet-1")
    assert _ids(coord.next_tasks(runtime)) == []  # M01 has all tasks done but is not DONE yet
    coord.complete_milestone(runtime, "M01", "opus-orch", "All checks pass")
    assert _ids(coord.next_tasks(runtime)) == ["M02.1"]


def test_next_tasks_lists_overlaps_with_claimed_tasks(runtime: Runtime) -> None:
    write_file(runtime, "docs/milestones/M03-kettle-sounds.md", M03)
    coord.claim_task(runtime, "M01.1", "sonnet-1")
    result = coord.next_tasks(runtime)
    item = next(t for t in result["tasks"] if t["id"] == "M03.1")
    assert item["governed_by"] == ["SPEC-01#1"]
    assert item["overlaps"] == [{"id": "M01.1", "claimed_by": "sonnet-1", "shared": ["SPEC-01#1"]}]
    assert _ids(coord.next_tasks(runtime, milestone="M03")) == ["M03.1"]


def test_next_tasks_input_errors(runtime: Runtime) -> None:
    assert _code(lambda: coord.next_tasks(runtime, limit=0)) == "invalid_input"
    assert _code(lambda: coord.next_tasks(runtime, milestone="M99")) == "milestone_not_found"
    assert _code(lambda: coord.next_tasks(runtime, agent="bad name")) == "invalid_input"


# ---------------------------------------------------------------- check 2


def test_spec05_ac02_reclaim_by_same_agent_is_idempotent(runtime: Runtime) -> None:
    first = coord.claim_task(runtime, "M01.1", "sonnet-1")
    second = coord.claim_task(runtime, "M01.1", "sonnet-1")
    assert first["already_held"] is False
    assert second["already_held"] is True
    assert second["claimed_at"] == first["claimed_at"]
    assert claims_on(runtime, "M01.1") == 1
    assert len(events(runtime, "task_claimed")) == 1
    assert task(runtime, "M01.1")["status"] == "claimed"


# ---------------------------------------------------------------- check 3


def test_spec05_ac03_double_claim_one_winner(runtime: Runtime) -> None:
    barrier = threading.Barrier(10)

    def attempt(n: int) -> str:
        barrier.wait()
        try:
            coord.claim_task(runtime, "M01.1", f"agent-{n}")
        except SddError as err:
            return err.code
        return "ok"

    with ThreadPoolExecutor(10) as pool:
        outcomes = list(pool.map(attempt, range(10)))
    assert outcomes.count("ok") == 1
    assert outcomes.count("already_claimed") == 9
    assert claims_on(runtime, "M01.1") == 1


def test_claim_errors(runtime: Runtime) -> None:
    assert _code(lambda: coord.claim_task(runtime, "M01.4", "a")) == "task_done"
    assert _code(lambda: coord.claim_task(runtime, "M01.2", "a")) == "task_blocked"
    assert _code(lambda: coord.claim_task(runtime, "M01.99", "a")) == "task_not_found"
    assert _code(lambda: coord.claim_task(runtime, "M01.1", None)) == "invalid_input"
    assert _code(lambda: coord.claim_task(runtime, "SPEC-01", "a")) == "invalid_input"
    with pytest.raises(SddError) as info:
        coord.claim_task(runtime, "M01.2", "a")
    assert info.value.details["blockers"] == [{"id": "M01.1", "kind": "task", "status": "todo"}]


def test_already_claimed_details_and_agent_still_seen(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    coord.claim_task(runtime, "M01.1", "a")
    clock.advance(60)
    with pytest.raises(SddError) as info:
        coord.claim_task(runtime, "M01.1", "b")
    assert info.value.code == "already_claimed"
    assert info.value.details["claimed_by"] == "a"
    seen = runtime.store.read("MATCH (a:Agent {id: 'agent:b'}) RETURN a.last_seen AS at")
    assert seen[0]["at"] == "2026-12-01T09:01:00Z"  # the failed call still counts as seen


# ---------------------------------------------------------------- check 4


def test_spec05_ac04_stale_claim_can_be_taken(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    coord.claim_task(runtime, "M01.1", "a")
    clock.advance(TTL + 1)
    result = coord.claim_task(runtime, "M01.1", "b")
    assert result["released_stale_claim_of"] == "a"
    assert task(runtime, "M01.1")["claimed_by"] == "b"
    assert claims_on(runtime, "M01.1") == 1
    released = events(runtime, "task_released")
    assert len(released) == 1
    assert released[0]["actor"] == "sync"
    assert released[0]["data"]["claimed_by"] == "a"
    # the new holder was just seen
    assert coord.status(runtime)["claims"][0]["stale"] is False


def test_stale_claim_shows_in_next_tasks_and_status(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    coord.claim_task(runtime, "M01.1", "a")
    assert _ids(coord.next_tasks(runtime)) == []
    clock.advance(TTL + 1)
    assert _ids(coord.next_tasks(runtime)) == ["M01.1"]
    claim = coord.status(runtime)["claims"][0]
    assert claim["stale"] is True
    assert claim["age_s"] == TTL + 1


# ---------------------------------------------------------------- check 11


def test_spec05_ac11_forced_release(runtime: Runtime) -> None:
    coord.claim_task(runtime, "M01.1", "a")
    assert _code(lambda: coord.release_task(runtime, "M01.1", "b")) == "not_claimed_by_you"
    result = coord.release_task(runtime, "M01.1", "b", reason="a crashed", force=True)
    assert result == {
        "task": "M01.1",
        "released": True,
        "claimed_by": "a",
        "forced": True,
        "synced_at": result["synced_at"],
    }
    released = events(runtime, "task_released")
    assert released[-1]["actor"] == "a"
    assert released[-1]["data"] == {"reason": "a crashed", "forced_by": "b"}
    assert claims_on(runtime, "M01.1") == 0
    assert coord.claim_task(runtime, "M01.1", "c")["agent"] == "c"


def test_release_own_claim_and_unclaimed(runtime: Runtime) -> None:
    coord.claim_task(runtime, "M01.1", "a")
    assert coord.release_task(runtime, "M01.1", "a")["forced"] is False
    assert task(runtime, "M01.1")["status"] == "todo"
    assert "forced_by" not in events(runtime, "task_released")[-1]["data"]
    assert _code(lambda: coord.release_task(runtime, "M01.1", "a")) == "not_claimed_by_you"
    assert coord.release_task(runtime, "M01.1", "a", force=True)["released"] is False


# ---------------------------------------------------------------- check 12


def test_spec05_ac12_read_tools_keep_a_claim_alive(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    coord.claim_task(runtime, "M01.1", "a")
    for _ in range(3):  # 3 h in total, a read call with `agent` every hour
        clock.advance(3600)
        coord.next_tasks(runtime, agent="a")
    assert _code(lambda: coord.claim_task(runtime, "M01.1", "b")) == "already_claimed"
    coord.status(runtime, agent="a")
    clock.advance(TTL - 10)
    assert _code(lambda: coord.claim_task(runtime, "M01.1", "b")) == "already_claimed"
