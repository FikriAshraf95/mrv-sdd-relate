"""SPEC-07 §2 endpoints 7, 8 and 14: sections, context packets and guarded queries."""

from __future__ import annotations

from urllib.parse import quote

from starlette.testclient import TestClient

from sdd.service.runtime import Runtime


def test_sections_endpoint_takes_an_encoded_reference(app: TestClient) -> None:
    ok = app.get(f"/api/sections/{quote('SPEC-01 §1–2', safe='')}", params={"agent": "web"})
    assert ok.status_code == 200
    assert [s["id"] for s in ok.json()["sections"]] == ["SPEC-01#1", "SPEC-01#2"]
    by_id = app.get(f"/api/sections/{quote('SPEC-01#2', safe='')}")
    assert [s["id"] for s in by_id.json()["sections"]] == ["SPEC-01#2"]
    missing = app.get(f"/api/sections/{quote('SPEC-01 §9', safe='')}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "unknown_section"


def test_context_endpoint(app: TestClient, runtime: Runtime) -> None:
    packet = app.get("/api/tasks/M01.1/context", params={"agent": "sonnet-1"}).json()
    assert packet["task"]["id"] == "M01.1"
    assert packet["sections"][0]["amended_by"] == ["D001"]
    full = app.get("/api/tasks/M01.1/context", params={"detail": "milestone"}).json()
    assert [s["id"] for s in full["sections"]] == ["SPEC-01#1", "SPEC-01#2"]
    assert app.get("/api/tasks/M01.99/context").status_code == 404
    bad = app.get("/api/tasks/M01.1/context", params={"max_chars": "lots"})
    assert bad.status_code == 400
    assert runtime.store.read("MATCH (a:Agent {id: 'agent:sonnet-1'}) RETURN a.id AS id")


def test_query_endpoint(app: TestClient) -> None:
    ok = app.post("/api/query", json={"cypher": "MATCH (s:Spec) RETURN s.id AS id"})
    assert ok.status_code == 200
    assert ok.json() == {
        "columns": ["id"],
        "rows": [["SPEC-01"]],
        "truncated": False,
        "synced_at": ok.json()["synced_at"],
    }
    rejected = app.post("/api/query", json={"cypher": "MATCH (n) DETACH DELETE n"})
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "query_rejected"
    bad = app.post("/api/query", json={"cypher": "RETURN 1", "params": [1]})
    assert bad.status_code == 400
    # a write-free POST still follows the Origin rule for non-GET requests (SPEC-09 §2 rule 4)
    evil = app.post(
        "/api/query", json={"cypher": "RETURN 1"}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403
