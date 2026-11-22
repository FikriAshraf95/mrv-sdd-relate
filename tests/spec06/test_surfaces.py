"""SPEC-06 over MCP tools 11-13, endpoints 9-11 and 13, and the CLI (plan M04b §7)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import anyio
from mcp import Client
from starlette.testclient import TestClient
from typer.testing import CliRunner

from sdd.cli import app
from sdd.mcp.server import create_server
from sdd.service.runtime import Runtime
from tests.conftest import FakeDaemon, MakeProject

runner = CliRunner()


def _payload(result: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(result.content[0].text)
    assert result.structured_content == data
    return data


def test_mcp_impact_explain_find_code(runtime: Runtime) -> None:
    server = create_server(runtime)

    async def session() -> dict[str, Any]:
        out: dict[str, Any] = {}
        async with Client(server) as client:
            out["impact"] = await client.call_tool(
                "impact", {"target": "documents", "agent": "opus-orch"}
            )
            out["shallow"] = await client.call_tool("impact", {"target": "documents", "depth": 1})
            out["bad_depth"] = await client.call_tool("impact", {"target": "documents", "depth": 9})
            out["ambiguous"] = await client.call_tool("impact", {"target": "id"})
            out["explain"] = await client.call_tool("explain", {"path": "src/ingest/loader.py"})
            out["missing"] = await client.call_tool("explain", {"path": "src/none.py"})
            out["find"] = await client.call_tool(
                "find_code", {"table": "documents", "feature": "ingestion"}
            )
            out["find_none"] = await client.call_tool("find_code", {})
        return out

    out = anyio.run(session)
    impact = _payload(out["impact"])
    assert impact["target"]["id"] == "table:documents"
    assert [i["id"] for i in impact["groups"]["tasks_open"]] == ["M02.1"]
    assert _payload(out["shallow"])["counts"]["files"] == 0
    assert out["bad_depth"].is_error  # the schema bounds depth to 1..5
    ambiguous = _payload(out["ambiguous"])
    assert ambiguous["error"]["code"] == "ambiguous_target"
    assert ambiguous["error"]["details"]["candidates"] == [
        "column:chunks.id",
        "column:documents.id",
    ]
    assert _payload(out["explain"])["features"][0]["id"] == "feature:ingestion"
    assert _payload(out["missing"])["error"]["code"] == "file_not_found"
    assert [f["path"] for f in _payload(out["find"])["files"]][-1] == "src/ingest/loader.py"
    assert _payload(out["find_none"])["error"]["code"] == "invalid_input"
    assert runtime.store.read("MATCH (a:Agent {id: 'agent:opus-orch'}) RETURN a.id AS id")


def test_endpoints_9_to_11_and_13(app: TestClient) -> None:
    r = app.get("/api/impact", params={"target": "documents", "depth": 2})
    assert r.status_code == 200
    assert r.json()["target"]["id"] == "table:documents"
    assert app.get("/api/impact", params={"target": "documents", "depth": "x"}).status_code == 400
    assert app.get("/api/impact", params={"target": "nothing-here"}).status_code == 404
    assert app.get("/api/impact", params={"target": "id"}).status_code == 400
    ambiguous = app.get("/api/impact", params={"target": "id"}).json()["error"]
    assert ambiguous["code"] == "ambiguous_target"
    assert app.get("/api/impact").status_code == 400  # no target

    e = app.get("/api/explain", params={"path": "src/ingest/loader.py"})
    assert e.status_code == 200
    assert e.json()["file"]["path"] == "src/ingest/loader.py"
    assert app.get("/api/explain", params={"path": "src/none.py"}).status_code == 404

    f = app.get("/api/find", params={"table": "documents", "text": "chunk"})
    assert [x["path"] for x in f.json()["files"]] == ["src/ingest/chunker.py"]
    assert app.get("/api/find").status_code == 400

    listed = app.get("/api/presets").json()
    assert listed[0]["name"] == "schema"
    schema = app.get("/api/presets/schema").json()
    assert {"nodes", "edges"} == set(schema)
    graph = app.get(f"/api/presets/{quote('impact:documents', safe='')}")
    assert graph.status_code == 200
    assert any(n["id"] == "table:chunks" for n in graph.json()["nodes"])
    lineage = app.get(f"/api/presets/{quote('lineage:SPEC-02 §2', safe='')}")
    assert lineage.status_code == 200
    assert app.get("/api/presets/nope").status_code == 404


def _run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.stdout


def test_cli_impact_explain_find_text(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)
    code, out = _run("impact", "documents", "--project", root)
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == "table:documents (Table) documents"
    assert "tables (4)" in lines
    assert "  table:chunks  chunks" in lines
    assert (
        "      via table:documents <-REFERENCES column:chunks.document_id <-HAS_COLUMN table:chunks"
        in lines
    )
    assert "  M02.1  Loader that stores `documents` (SPEC-02 §2) [todo]" in lines
    assert "GET /api/impact" in fake_daemon.seen

    code, out = _run("impact", "documents", "--depth", "1", "--project", root)
    assert "files (" not in out  # three hops away: out of depth

    code, out = _run("explain", "src/ingest/loader.py", "--project", root)
    assert code == 0, out
    assert out.startswith("src/ingest/loader.py implements feature Ingestion (Library)")
    assert "features (1)" in out
    assert "      via file:src/ingest/loader.py <-IMPLEMENTED_IN feature:ingestion" in out

    code, out = _run("find", "--table", "documents", "--feature", "ingestion", "--project", root)
    assert code == 0, out
    assert out.splitlines() == [
        "src/ingest/__init__.py  (python)",
        "src/ingest/chunker.py  (python)",
        "src/ingest/loader.py  (python)",
        "3 files",
    ]

    code, out = _run("--json", "find", "--text", "kettle", "--project", root)
    assert code == 0
    assert json.loads(out)["counts"] == {"files": 2}
    code, out = _run("--json", "impact", "id", "--project", root)
    assert code == 2  # ambiguous_target
    assert json.loads(out)["error"]["details"]["candidates"] == [
        "column:chunks.id",
        "column:documents.id",
    ]
    code, out = _run("--json", "explain", "src/none.py", "--project", root)
    assert code == 3
    assert json.loads(out)["error"]["code"] == "file_not_found"
    code, out = _run("--json", "find", "--project", root)
    assert code == 2


def test_cli_without_a_daemon_reads_a_snapshot(project: MakeProject) -> None:
    root = str(project("tool_style"))
    code, out = _run("--json", "impact", "documents", "--project", root, "--store", ":memory:")
    assert code == 0, out
    assert json.loads(out)["counts"]["files"] == 3
    code, out = _run("explain", "src/util/misc.py", "--project", root, "--store", ":memory:")
    assert code == 0, out
    assert "orphan code" in out
