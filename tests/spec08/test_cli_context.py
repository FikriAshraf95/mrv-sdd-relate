"""SPEC-08 §2 ``sdd context``, ``sdd section``, ``sdd query`` and ``sdd init`` (check 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sdd.cli import app
from sdd.service import init as init_service
from sdd.service.runtime import Runtime
from tests.conftest import FakeDaemon, MakeProject

runner = CliRunner()


def _json(args: list[str], **kwargs: Any) -> tuple[int, dict[str, Any]]:
    result = runner.invoke(app, [*args, "--json"], **kwargs)
    return result.exit_code, json.loads(result.stdout)


# ---------------------------------------------------------------- context, section, query


def test_reads_through_the_daemon(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)
    code, packet = _json(["context", "M01.1", "--agent", "sonnet-1", "--project", root])
    assert code == 0
    assert packet["sections"][0]["id"] == "SPEC-01#1"
    code, sections = _json(["section", "SPEC-01 §1", "SPEC-01#2", "--project", root])
    assert code == 0
    assert [s["id"] for s in sections["sections"]] == ["SPEC-01#1", "SPEC-01#2"]
    code, rows = _json(
        ["query", "MATCH (t:Task {id: $id}) RETURN t.status AS s", "--params", '{"id": "M01.4"}',
         "--project", root]
    )  # fmt: skip
    assert code == 0
    assert rows["rows"] == [["done"]]
    assert "GET /api/tasks/M01.1/context" in fake_daemon.seen
    assert "GET /api/sections/SPEC-01%20%C2%A71" in fake_daemon.seen  # encoded (SPEC-07 §1)
    assert "POST /api/query" in fake_daemon.seen


def test_reads_without_a_daemon(project: MakeProject) -> None:
    root = str(project("tool_style"))
    store = [":memory:"]
    code, packet = _json(["context", "M01.4", "--project", root, "--store", *store])
    assert code == 0
    assert [c["id"] for c in packet["checks"]] == ["SPEC-01#ac1", "SPEC-01#ac2", "SPEC-01#ac3"]
    text = runner.invoke(app, ["section", "SPEC-01 §2", "--project", root, "--store", *store])
    assert text.exit_code == 0
    assert "## SPEC-01#2 Teas" in text.stdout
    code, err = _json(["section", "SPEC-01 §7", "--project", root, "--store", *store])
    assert code == 3
    assert err["error"]["code"] == "unknown_section"
    code, err = _json(["query", "MATCH (n) DELETE n", "--project", root, "--store", *store])
    assert code == 1
    assert err["error"]["code"] == "query_rejected"
    out = runner.invoke(
        app, ["query", "MATCH (s:Spec) RETURN s.id AS id", "--project", root, "--store", *store]
    )
    assert out.stdout.splitlines() == ["id", '"SPEC-01"', '"SPEC-02"']


# ---------------------------------------------------------------- init


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    }


def test_spec08_ac01_init_detects_folders_and_is_idempotent(project: MakeProject) -> None:
    root = project("tool_style")
    assert not (root / ".sdd").exists()
    code, result = _json(["init", "--project", str(root)])
    assert code == 0
    assert result["paths"] == {
        "specs": ["docs/specs/SPEC-*.md"],
        "milestones": ["docs/milestones/**/M*.md"],
        "plans": ["docs/milestones/**/M*-plan.md"],
        "deviations": ["docs/deviations/D*.md"],
        "deviation_index": ["docs/DEVIATIONS.md"],
    }
    assert {f["path"]: f["action"] for f in result["files"]} == {
        ".sdd/config.toml": "created",
        ".sdd/.gitignore": "created",
        ".mcp.json": "created",
        ".claude/skills/sdd/SKILL.md": "created",
    }
    config = (root / ".sdd/config.toml").read_text(encoding="utf-8")
    assert 'specs = ["docs/specs/SPEC-*.md"]' in config
    assert "/graph/" in (root / ".sdd/.gitignore").read_text(encoding="utf-8")
    mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp == {"mcpServers": {"sdd": {"type": "http", "url": "http://localhost:8770/mcp"}}}
    skill = (root / ".claude/skills/sdd/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: sdd\n")
    assert 'what_changed(since="last_session"' in skill
    assert "claim_task" in result["snippet"]
    # the written config loads, and the project now syncs with it
    code, status = _json(["status", "--project", str(root), "--store", ":memory:"])
    assert code == 0, status

    before = _snapshot(root)
    code, again = _json(["init", "--project", str(root)])
    assert code == 0
    assert {f["action"] for f in again["files"]} == {"kept"}
    assert _snapshot(root) == before


def test_init_merges_mcp_json_and_force_replaces(project: MakeProject) -> None:
    root = project("tool_style")
    other = {"command": "npx", "args": ["-y", "some-server"]}
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": other}}), encoding="utf-8")
    code, result = _json(["init", "--project", str(root)])
    assert code == 0
    assert {f["path"]: f["action"] for f in result["files"]}[".mcp.json"] == "merged"
    servers = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers["other"] == other
    assert servers["sdd"]["url"] == init_service.MCP_URL

    servers["sdd"]["url"] = "http://localhost:9999/mcp"
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    _json(["init", "--project", str(root)])
    kept = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert kept["sdd"]["url"] == "http://localhost:9999/mcp"
    code, forced = _json(["init", "--force", "--project", str(root)])
    assert code == 0
    assert {f["action"] for f in forced["files"]} == {"replaced"}
    replaced = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert replaced["sdd"]["url"] == init_service.MCP_URL
    assert replaced["other"] == other


def test_init_never_writes_the_token(project: MakeProject, monkeypatch: pytest.MonkeyPatch) -> None:
    root = project("tool_style")
    monkeypatch.setenv("SDD_TOKEN", "s3cret-value")
    code, _ = _json(["init", "--project", str(root)])
    assert code == 0
    text = (root / ".mcp.json").read_text(encoding="utf-8")
    assert "s3cret-value" not in text
    headers = json.loads(text)["mcpServers"]["sdd"]["headers"]
    assert headers == {"Authorization": "Bearer ${SDD_TOKEN}"}
    for path in _snapshot(root).values():
        assert b"s3cret-value" not in path


def test_init_bad_mcp_json(project: MakeProject) -> None:
    root = project("tool_style")
    (root / ".mcp.json").write_text("{not json", encoding="utf-8")
    code, err = _json(["init", "--project", str(root)])
    assert code == 2
    assert err["error"]["code"] == "invalid_input"
