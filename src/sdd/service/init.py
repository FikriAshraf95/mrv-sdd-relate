"""``sdd init`` (SPEC-08 §2, SPEC-05 §9): set a project up for SDD Graph and Claude Code.

Writes ``.sdd/config.toml`` (the detected document folders), ``.sdd/.gitignore``, ``.mcp.json``
(the ``sdd`` server merged into any existing file) and ``.claude/skills/sdd/SKILL.md`` (the agent
protocol), and returns the CLAUDE.md snippet for the caller to print. Nothing that exists is
overwritten without ``force``, so a second run changes nothing. The token is never written: the
``.mcp.json`` header names ``${SDD_TOKEN}``, which Claude Code expands from the environment.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from sdd.config import DEFAULT_PATHS, Settings
from sdd.errors import SddError

__all__ = ["MCP_URL", "SKILL", "SNIPPET", "detect_paths", "init_project"]

MCP_URL = "http://localhost:8770/mcp"
_SKIP_DIRS = frozenset({"node_modules", "venv", "__pycache__", "fixtures", "dist", "build"})
_SPEC_FILE = re.compile(r"^SPEC-\d+.*\.md$")
_MILESTONE_FILE = re.compile(r"^M\d+[a-z]?-.+\.md$")
_DEVIATION_FILE = re.compile(r"^D\d{3,}-.+\.md$")
_ARCHIVE_DIRS = frozenset({"done", "archive", "completed"})

GITIGNORE = """\
# SDD Graph: the live store and the daemon's runtime files are never committed (DEC-001).
# Committed stores (`sdd snapshot`) keep their .cypherlite.lock markers, so only root locks go.
/graph/
/daemon.json
/*.lock
.cypherlite.writer
"""

SKILL = """\
---
name: sdd
description: Work this spec-driven repo through the SDD Graph MCP server (server "sdd"). Use at
  the start of every session and for every milestone task, instead of reading spec and milestone
  files: claim tasks, pull context packets, log deviations, complete tasks.
---

# SDD Graph agent protocol

The `sdd` MCP server holds this repo's specs, milestones, tasks, deviations and code as one
graph. Markdown stays the source of truth; the tools read it for you and write it back safely.
Pass `agent` on every call: your own name, **the same one every session** (the main session is
`opus-orch`; subagents get theirs from the orchestrator, e.g. `sonnet-1`).

## Any session start
1. `what_changed(since="last_session", agent=<your name>)`: what moved since your last call
   (sections, deviations, tasks, milestones). Do this instead of re-reading docs.

## Orchestrator
1. `status` for the milestones and live claims, then `next_tasks` for the claimable tasks.
2. Launch one subagent per task that has no `overlaps`; tell each its agent name and task ID.
3. Review the work each one returns. If a subagent failed or died, free its task with
   `release_task(task_id, agent=<your name>, force=true)`.
4. When the milestone's acceptance criteria are verified: `complete_milestone` with how they
   were verified.

## Worker
1. `claim_task(task_id, agent)`. `already_claimed` means someone else has it: report back.
2. `get_context(task_id, agent)`: governing sections in full, deviations, checks, upstream
   notes, related code. `read_section` anything in `outline` you need. Do not read spec files.
3. Build and test.
4. `log_deviation` for **every** intentional departure from a spec (it writes the deviation
   file, the index row and the spec note in one change).
5. `complete_task(task_id, agent, notes, files_touched, commit)`, then report.

## Also
- `read_section(["SPEC-03 §4.2"])` for any section by reference (subsections included).
- `query(cypher)` for read-only Cypher (no writes or CALL, `*..4` at most, 100 rows, 5 s).
- Every result has `synced_at`; if the daemon is down, fall back to reading the Markdown.
"""

SNIPPET = """\
## Agents (SDD Graph)

This repo is served by the SDD Graph daemon (`sdd daemon`, MCP server `sdd` in `.mcp.json`).
Follow `.claude/skills/sdd/SKILL.md`. In short:
- Session start: `what_changed(since="last_session", agent="<your name>")`, the same name
  every session (`opus-orch` for the main session).
- Work a task: `claim_task` → `get_context` → `read_section` for what the outline lists →
  build and test → `log_deviation` for every departure → `complete_task`.
- Fall back to reading the Markdown only if the daemon is down.
"""


def _candidates(root: Path, pattern: re.Pattern[str]) -> list[PurePosixPath]:
    """Project-relative Markdown files whose name matches, skipping hidden and vendored dirs."""
    out: list[PurePosixPath] = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS)
        rel = PurePosixPath(Path(folder).relative_to(root).as_posix())
        out.extend(rel / n for n in sorted(names) if pattern.match(n))
    return out


def _best_dir(files: list[PurePosixPath]) -> PurePosixPath | None:
    """The folder holding the most matching files (the shallowest on a tie)."""
    if not files:
        return None
    counts = Counter(f.parent for f in files)
    return min(counts, key=lambda d: (-counts[d], len(d.parts), str(d)))


def _glob(folder: PurePosixPath, pattern: str) -> str:
    return pattern if str(folder) == "." else f"{folder}/{pattern}"


def detect_paths(root: Path) -> dict[str, tuple[str, ...]]:
    """Document globs for ``.sdd/config.toml``: only the keys whose files were found."""
    out: dict[str, tuple[str, ...]] = {}
    specs = _best_dir(_candidates(root, _SPEC_FILE))
    if specs is not None:
        out["specs"] = (_glob(specs, "SPEC-*.md"),)
    milestones = _best_dir(
        [f for f in _candidates(root, _MILESTONE_FILE) if not f.name.endswith("-plan.md")]
    )
    if milestones is not None:
        if milestones.name in _ARCHIVE_DIRS:
            milestones = milestones.parent
        out["milestones"] = (_glob(milestones, "**/M*.md"),)
        out["plans"] = (_glob(milestones, "**/M*-plan.md"),)
    deviations = _best_dir(_candidates(root, _DEVIATION_FILE))
    if deviations is None and specs is not None and (root / specs.parent / "deviations").is_dir():
        deviations = specs.parent / "deviations"
    if deviations is not None:
        out["deviations"] = (_glob(deviations, "D*.md"),)
        index = deviations.parent / "DEVIATIONS.md"
        if (root / index).is_file():
            out["deviation_index"] = (str(index),)
    return out


def _toml(paths: dict[str, tuple[str, ...]]) -> str:
    lines = [
        "# SDD Graph configuration (written by `sdd init`). Keys left out use the defaults of",
        "# SPEC-03 §1. Other keys: docs, schema_specs, tests (globs), writeback (bool),",
        '# always_include (spec references every context packet carries, default ["SPEC-00 §6"]).',
    ]
    for key in DEFAULT_PATHS:
        if key in paths:
            lines.append(f"{key} = {json.dumps(list(paths[key]))}")
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _mcp_entry(settings: Settings) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": "http", "url": MCP_URL}
    if settings.token:
        entry["headers"] = {"Authorization": "Bearer ${SDD_TOKEN}"}
    return entry


def _merge_mcp(path: Path, settings: Settings, *, force: bool) -> str:
    entry = _mcp_entry(settings)
    if not path.is_file():
        _write(path, json.dumps({"mcpServers": {"sdd": entry}}, indent=2) + "\n")
        return "created"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise SddError("invalid_input", f"{path.name} is not valid JSON: {exc}. Fix it.") from None
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise SddError("invalid_input", f"{path.name} must hold an object with 'mcpServers'.")
    servers = data.setdefault("mcpServers", {})
    if "sdd" in servers and not force:
        return "kept"
    action = "replaced" if "sdd" in servers else "merged"
    servers["sdd"] = entry
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return action


def init_project(settings: Settings, *, force: bool = False) -> dict[str, Any]:
    """Set up ``settings.project_root``; returns ``{project, paths, files, snippet}``."""
    root = settings.project_root
    paths = detect_paths(root)
    files: list[dict[str, str]] = []

    def put(rel: str, text: str) -> None:
        target = root / rel
        if target.exists() and not force:
            files.append({"path": rel, "action": "kept"})
            return
        action = "replaced" if target.exists() else "created"
        _write(target, text)
        files.append({"path": rel, "action": action})

    put(".sdd/config.toml", _toml(paths))
    put(".sdd/.gitignore", GITIGNORE)
    mcp_action = _merge_mcp(root / ".mcp.json", settings, force=force)
    files.append({"path": ".mcp.json", "action": mcp_action})
    put(".claude/skills/sdd/SKILL.md", SKILL)
    return {
        "project": str(root),
        "paths": {k: list(v) for k, v in paths.items()},
        "files": files,
        "snippet": SNIPPET,
    }
