"""SPEC-07 §2 endpoints 5, 12, 17, 18 and 21: the coordination tools over HTTP."""

from __future__ import annotations

from urllib.parse import quote

from starlette.testclient import TestClient

from sdd.service.runtime import Runtime
from sdd.web.errors import HTTP_STATUS
from tests.conftest import FIXTURES
from tests.spec05.helpers import MILESTONE, read

BODY = {
    "task_id": "M01.2",
    "agent": "sonnet-1",
    "title": "Countdown in tenths",
    "spec_says": "Seconds.",
    "implementation_does": "Tenths.",
    "why": "Smoother.",
    "amends": ["SPEC-01 §2"],
}


def test_claim_release_complete_over_http(app: TestClient) -> None:
    claimed = app.post("/api/tasks/M01.1/claim", json={"agent": "sonnet-1"})
    assert claimed.status_code == 200
    assert claimed.json()["agent"] == "sonnet-1"
    clash = app.post("/api/tasks/M01.1/claim", json={"agent": "sonnet-2"})
    assert clash.status_code == HTTP_STATUS["already_claimed"] == 409
    assert clash.json()["error"]["code"] == "already_claimed"
    assert clash.json()["error"]["details"]["claimed_by"] == "sonnet-1"

    board = app.get("/api/board").json()
    assert board["milestone"]["id"] == "M01"
    assert [t["id"] for t in board["columns"]["claimed"]] == ["M01.1"]
    assert board["columns"]["claimed"][0]["claimed_by"] == "sonnet-1"

    done = app.post(
        f"/api/tasks/{quote('M01.1')}/complete",
        json={"agent": "sonnet-1", "notes": "ok", "files_touched": ["src/kettle/brew.py"]},
    )
    assert done.status_code == 200
    assert done.json()["unblocked"][0]["id"] == "M01.2"
    nxt = app.get("/api/next", params={"agent": "opus-orch"}).json()
    assert [t["id"] for t in nxt["tasks"]] == ["M01.2"]

    app.post("/api/tasks/M01.2/claim", json={"agent": "a"})
    forced = app.post("/api/tasks/M01.2/release", json={"agent": "b", "force": True})
    assert forced.json()["forced"] is True
    refused = app.post("/api/tasks/M01.2/release", json={"agent": "b"})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "not_claimed_by_you"


def test_deviation_and_milestone_over_http(app: TestClient) -> None:
    logged = app.post("/api/deviations", json=BODY)
    assert logged.status_code == 200, logged.text
    assert logged.json()["id"] == "D002"
    unknown = app.post("/api/deviations", json={**BODY, "amends": ["SPEC-01 §9"]})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "unknown_section"

    incomplete = app.post("/api/milestones/M01/complete", json={"agent": "o", "verification": "x"})
    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "milestone_incomplete"
    missing = app.post("/api/milestones/M77/complete", json={"agent": "o", "verification": "x"})
    assert missing.status_code == 404

    changed = app.get("/api/changes", params={"since": "last_session", "agent": "o"}).json()
    assert [d["id"] for d in changed["deviations"]] == ["D002"]
    assert changed["first_session"] is True


def test_bad_bodies_are_invalid_input(app: TestClient) -> None:
    for body in (b"not json", b"[1, 2]", b'{"agent": 5}'):
        response = app.post(
            "/api/tasks/M01.1/claim", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_input"
    missing_agent = app.post("/api/tasks/M01.1/claim", json={})
    assert missing_agent.json()["error"]["code"] == "invalid_input"
    bad_since = app.get("/api/changes", params={"since": "soon"})
    assert bad_since.status_code == 400


def test_status_reports_claims_with_age_and_synced_at(app: TestClient) -> None:
    app.post("/api/tasks/M01.1/claim", json={"agent": "sonnet-1"})
    status = app.get("/api/status", params={"agent": "opus-orch"}).json()
    assert status["claims"][0]["task"] == "M01.1"
    assert status["claims"][0]["stale"] is False
    assert isinstance(status["claims"][0]["age_s"], int)
    assert status["synced_at"]
    assert status["warning_count"] == sum(status["warnings"].values())


def test_board_for_a_given_milestone(app: TestClient) -> None:
    board = app.get("/api/board", params={"milestone": "m1"}).json()
    assert [t["id"] for t in board["columns"]["done"]] == ["M01.4"]
    assert app.get("/api/board", params={"milestone": "M42"}).status_code == 404


def test_complete_ticks_the_copy_not_the_fixture(app: TestClient, runtime: Runtime) -> None:
    app.post("/api/tasks/M01.1/claim", json={"agent": "a"})
    app.post("/api/tasks/M01.1/complete", json={"agent": "a"})
    assert "- [x] **M01.1**" in read(runtime, MILESTONE)
    fixture = (FIXTURES / "tool_style" / MILESTONE).read_text(encoding="utf-8")
    assert "- [ ] **M01.1**" in fixture
