"""SPEC-10 §4 invariant 6, MCP and CLI parts: the tool index of SPEC-05 §2 and the command
table of SPEC-08 §2 match what the code registers. Our own specs, parsed with our own parser.

Entries the spec names but a later milestone builds are listed in ``PENDING_*`` with that
milestone; the list must shrink to empty as they land (an entry that is registered fails).
The endpoint part (SPEC-07 §2) is added with the dashboard (M05a).
"""

from __future__ import annotations

import re
from pathlib import Path

import anyio
from mcp import Client
from typer.main import get_command

from sdd.cli import app
from sdd.mcp.server import TOOLS, create_server
from sdd.parse import parse_spec
from sdd.service.runtime import Runtime

SPECS = Path(__file__).resolve().parents[2] / "docs" / "specs"

PENDING_TOOLS: dict[str, str] = {}
PENDING_COMMANDS = {
    "public": "M06b",
    "export": "M06a",
    "snapshot": "M06a",
    "bench": "M07",
    "demo": "M06b",
}


def _section_text(spec_file: str, section_id: str) -> str:
    path = SPECS / spec_file
    result = parse_spec(f"docs/specs/{spec_file}", path.read_text(encoding="utf-8"))
    for node in result.nodes:
        if node.label == "Section" and node.id == section_id:
            return str(node.props["text"])
    raise AssertionError(f"{section_id} not found in {spec_file}")


def _spec_tools() -> set[str]:
    text = _section_text("SPEC-05-agent-tools.md", "SPEC-05#2")
    return set(re.findall(r"^\|\s*\d+\s*\|\s*`([a-z_]+)\(", text, flags=re.M))


def _spec_commands() -> set[str]:
    text = _section_text("SPEC-08-cli-and-exports.md", "SPEC-08#2")
    names: set[str] = set()
    for line in text.splitlines():
        cells = line.split("|")
        if len(cells) < 3:
            continue
        for span in re.findall(r"`sdd ([a-z][a-z-]*)", cells[1]):
            names.add(span)
    return names


def test_inv06_mcp_tools_match_spec05(runtime: Runtime) -> None:
    async def listed() -> set[str]:
        async with Client(create_server(runtime)) as client:
            return {t.name for t in (await client.list_tools()).tools}

    registered = anyio.run(listed)
    spec = _spec_tools()
    assert len(spec) == 14
    assert registered == set(TOOLS)
    assert registered - spec == set(), "registered tools missing from SPEC-05 §2"
    assert spec - registered == set(PENDING_TOOLS), "SPEC-05 §2 tools not registered"


def test_inv06_cli_commands_match_spec08() -> None:
    group = get_command(app)
    registered = set(group.commands)  # type: ignore[attr-defined]
    spec = _spec_commands()
    assert {"init", "context", "section", "query"} <= spec
    assert registered - spec == set(), "registered commands missing from SPEC-08 §2"
    assert spec - registered == set(PENDING_COMMANDS), "SPEC-08 §2 commands not registered"
