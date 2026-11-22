"""Our own specs, read with our own parser: the endpoint index of SPEC-07 §2 (SPEC-10 §4 item 6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sdd.parse import parse_spec

SPECS = Path(__file__).resolve().parents[1] / "docs" / "specs"


@dataclass(frozen=True)
class Endpoint:
    method: str  # GET, POST, or MCP for the /mcp mount
    path: str  # with `{id}`-style parameters
    public: bool


def section_text(spec_file: str, section_id: str) -> str:
    path = SPECS / spec_file
    result = parse_spec(f"docs/specs/{spec_file}", path.read_text(encoding="utf-8"))
    for node in result.nodes:
        if node.label == "Section" and node.id == section_id:
            return str(node.props["text"])
    raise AssertionError(f"{section_id} not found in {spec_file}")


def spec07_endpoints() -> list[Endpoint]:
    """Every ``(method, path)`` of SPEC-07 §2, with the short forms expanded
    (``POST /api/tasks/{id}/claim`` · ``/release`` · ``/complete``)."""
    text = section_text("SPEC-07-dashboard-and-api.md", "SPEC-07#2")
    out: list[Endpoint] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        public = cells[2].startswith("✓")
        last = ""
        for span in re.findall(r"`([^`]+)`", cells[1]):
            head = span.split(" ", 1)
            if head[0] in ("GET", "POST"):
                method, path = head[0], head[1].split("?", 1)[0]
                last = path
            elif span == "/mcp":
                method, path = "MCP", "/mcp"
            elif span.startswith("/"):
                method = out[-1].method
                path = last.rsplit("/", 1)[0] + span
            else:
                continue  # a body shape such as `{cypher, params}`
            out.append(Endpoint(method, path, public))
    return out
