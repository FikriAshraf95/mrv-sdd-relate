"""SPEC-05 §1–2: the MCP server, driven by an in-process MCP client (no sockets)."""

from __future__ import annotations

import json
from typing import Any

import anyio
from mcp import Client
from starlette.testclient import TestClient

from sdd.daemon import build_app
from sdd.mcp.server import INSTRUCTIONS, TOOLS, create_server
from sdd.service.runtime import Runtime
from tests.conftest import FAKE_PORT


def _payload(result: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(result.content[0].text)
    assert result.structured_content == data
    return data


def test_mcp_tools_in_process(runtime: Runtime) -> None:
    server = create_server(runtime)

    async def session() -> dict[str, Any]:
        out: dict[str, Any] = {}
        async with Client(server) as client:
            out["tools"] = sorted(t.name for t in (await client.list_tools()).tools)
            out["status"] = await client.call_tool("status", {"agent": "opus-orch"})
            out["next"] = await client.call_tool("next_tasks", {"agent": "opus-orch"})
            out["claim"] = await client.call_tool(
                "claim_task", {"task_id": "M01.1", "agent": "sonnet-1"}
            )
            out["clash"] = await client.call_tool(
                "claim_task", {"task_id": "M01.1", "agent": "sonnet-2"}
            )
            out["deviation"] = await client.call_tool(
                "log_deviation",
                {
                    "task_id": "M01.1",
                    "agent": "sonnet-1",
                    "title": "Steep times live in a table",
                    "spec_says": "Defaults are per tea.",
                    "implementation_does": "Defaults come from a table.",
                    "why": "Easier to edit.",
                    "amends": ["SPEC-01 §2"],
                },
            )
            out["done"] = await client.call_tool(
                "complete_task", {"task_id": "M01.1", "agent": "sonnet-1", "notes": "ok"}
            )
            out["incomplete"] = await client.call_tool(
                "complete_milestone",
                {"milestone_id": "M01", "agent": "opus-orch", "verification": "ok"},
            )
            out["release"] = await client.call_tool(
                "release_task", {"task_id": "M01.2", "agent": "opus-orch", "force": True}
            )
            out["changes"] = await client.call_tool(
                "what_changed", {"since": "last_session", "agent": "opus-orch"}
            )
        return out

    out = anyio.run(session)
    assert out["tools"] == sorted(TOOLS)
    assert "claims" in _payload(out["status"])
    assert [t["id"] for t in _payload(out["next"])["tasks"]] == ["M01.1"]
    assert _payload(out["claim"])["agent"] == "sonnet-1"
    assert out["clash"].is_error is True
    assert _payload(out["clash"])["error"]["code"] == "already_claimed"
    assert _payload(out["deviation"])["id"] == "D003"
    assert _payload(out["done"])["unblocked"][0]["id"] == "M01.2"
    assert _payload(out["incomplete"])["error"]["code"] == "milestone_incomplete"
    assert _payload(out["release"])["released"] is False
    changed = _payload(out["changes"])
    assert changed["first_session"] is True
    assert [d["id"] for d in changed["deviations"]] == ["D003"]
    for name in ("claim", "done", "changes"):
        assert _payload(out[name])["synced_at"]


def test_mcp_instructions_carry_the_protocol(runtime: Runtime) -> None:
    server = create_server(runtime)
    assert server.instructions == INSTRUCTIONS
    assert len(INSTRUCTIONS.splitlines()) == 3
    assert 'what_changed(since="last_session"' in INSTRUCTIONS


def test_mcp_is_mounted_at_slash_mcp(runtime: Runtime) -> None:
    app = build_app(runtime)
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    with TestClient(app, base_url=f"http://localhost:{FAKE_PORT}") as client:
        response = client.post(
            "/mcp", json=init, headers={"Accept": "application/json, text/event-stream"}
        )
        assert response.status_code == 200, response.text
        assert "sdd" in response.text
        # the /api routes are still there
        assert client.get("/api/health").json()["ok"] is True


def test_mcp_context_section_and_query_tools(runtime: Runtime) -> None:
    server = create_server(runtime)

    async def session() -> dict[str, Any]:
        out: dict[str, Any] = {}
        async with Client(server) as client:
            out["context"] = await client.call_tool(
                "get_context", {"task_id": "M01.1", "agent": "sonnet-1"}
            )
            out["section"] = await client.call_tool(
                "read_section", {"refs": ["SPEC-01 §1–2"], "agent": "sonnet-1"}
            )
            out["unknown"] = await client.call_tool("read_section", {"refs": ["SPEC-01 §9"]})
            out["query"] = await client.call_tool(
                "query",
                {
                    "cypher": "MATCH (t:Task {id: $id}) RETURN t.status AS s",
                    "params": {"id": "M01.4"},
                },
            )
            out["rejected"] = await client.call_tool("query", {"cypher": "CREATE (:X)"})
        return out

    out = anyio.run(session)
    packet = _payload(out["context"])
    assert packet["sections"][0]["id"] == "SPEC-01#1"
    assert [d["id"] for d in packet["deviations"]] == ["D001"]
    assert [s["id"] for s in _payload(out["section"])["sections"]] == ["SPEC-01#1", "SPEC-01#2"]
    assert _payload(out["unknown"])["error"]["code"] == "unknown_section"
    assert _payload(out["query"])["rows"] == [["done"]]
    assert _payload(out["rejected"])["error"]["code"] == "query_rejected"
