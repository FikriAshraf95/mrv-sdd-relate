"""SPEC-05 §7 what_changed: ``last_session`` per agent, ISO times and event IDs."""

from __future__ import annotations

import pytest

from sdd.errors import SddError
from sdd.service import changes
from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from tests.spec05.helpers import SPEC, Clock, events, read, use_clock, write_file


def _edit(runtime: Runtime, old: str, new: str) -> None:
    write_file(runtime, SPEC, read(runtime, SPEC).replace(old, new))


def _sections(result: dict[str, object]) -> list[str]:
    return [s["id"] for s in result["sections_changed"]]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- check 9


def test_spec05_ac09_last_session_is_since_the_previous_call(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    clock.advance(-25 * 3600)
    _edit(runtime, "1. A green tea", "1. A green tea brew")  # §3, 25 h before the first call
    clock.advance(24 * 3600)
    _edit(runtime, "Each tea has", "Every tea has")  # §2, 1 h before the first call
    clock.advance(3600)

    first = changes.what_changed(runtime, "last_session", "opus-orch")
    assert first["first_session"] is True
    assert _sections(first) == ["SPEC-01#2"]  # the last 24 h only
    assert first["sections_changed"][0]["title"] == "Teas"

    clock.advance(10)
    _edit(runtime, "A brew has a tea", "A brew has one tea")  # §1, after the first call
    clock.advance(10)
    second = changes.what_changed(runtime, "last_session", "opus-orch")
    assert second["first_session"] is False
    assert second["since"] == first["until"]
    assert _sections(second) == ["SPEC-01#1"]

    clock.advance(10)
    assert _sections(changes.what_changed(runtime, "last_session", "opus-orch")) == []
    # another agent has its own last session
    assert changes.what_changed(runtime, "last_session", "sonnet-1")["first_session"] is True


def test_what_changed_groups_tool_events(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    start = "2026-12-01T09:00:00Z"
    coord.claim_task(runtime, "M01.1", "sonnet-1")
    clock.advance(5)
    coord.complete_task(runtime, "M01.1", "sonnet-1", notes="ok", files_touched=["a.py"])
    result = changes.what_changed(runtime, start)
    assert [t["id"] for t in result["tasks_claimed"]] == ["M01.1"]
    done = result["tasks_completed"][0]
    assert (done["id"], done["actor"], done["notes"], done["files_touched"]) == (
        "M01.1",
        "sonnet-1",
        "ok",
        ["a.py"],
    )
    assert result["first_session"] is False
    assert result["synced_at"]


def test_what_changed_since_an_event(runtime: Runtime) -> None:
    clock = use_clock(runtime, Clock())
    coord.claim_task(runtime, "M01.1", "a")
    clock.advance(5)
    coord.release_task(runtime, "M01.1", "a")
    clock.advance(5)
    coord.claim_task(runtime, "M01.1", "b")
    first_claim = events(runtime, "task_claimed")[0]["id"]
    result = changes.what_changed(runtime, first_claim)
    assert [(t["id"], t["actor"]) for t in result["tasks_claimed"]] == [("M01.1", "b")]


def test_what_changed_input_errors(runtime: Runtime) -> None:
    for since, agent, code in (
        ("last_session", None, "invalid_input"),
        ("yesterday", None, "invalid_input"),
        ("2026-12-01T09:00:00", None, "invalid_input"),  # no time zone
        ("", None, "invalid_input"),
        ("event:01J00000000000000000000000", None, "node_not_found"),
    ):
        with pytest.raises(SddError) as info:
            changes.what_changed(runtime, since, agent)
        assert info.value.code == code, since
