"""SPEC-07 §2 endpoint 15: ``GET /api/mermaid?preset=`` (M06a.3)."""

from __future__ import annotations

from starlette.testclient import TestClient


def test_mermaid_endpoint_returns_text_plain(app: TestClient) -> None:
    response = app.get("/api/mermaid", params={"preset": "schema"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("flowchart LR\n")
    impact = app.get("/api/mermaid", params={"preset": "impact:documents"})
    assert impact.status_code == 200
    assert "table:documents" in impact.text


def test_mermaid_endpoint_errors(app: TestClient) -> None:
    missing = app.get("/api/mermaid")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_input"
    unknown = app.get("/api/mermaid", params={"preset": "milestone:M99"})
    assert unknown.status_code == 404
    # presets only: a Cypher query is not a preset name, so it cannot read anything
    cypher = app.get("/api/mermaid", params={"preset": "MATCH (n) RETURN n"})
    assert cypher.status_code == 404
    assert cypher.json()["error"]["code"] == "node_not_found"
