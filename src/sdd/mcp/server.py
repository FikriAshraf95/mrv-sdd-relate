"""The MCP server (SPEC-05): tools 1–10 and 14, served over streamable HTTP at ``/mcp``.

Each tool validates its input, calls one ``service/`` function and returns its JSON, the same
result the matching HTTP endpoint and CLI command give (SPEC-05 §1 rule 1). Errors come back as
an ``is_error`` result whose text is the one error shape (SPEC-00 §6.4). Tools are plain ``def``
functions, which the SDK runs in a worker thread, so a store call never blocks the event loop.
Tools 11–13 arrive in M04b.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.applications import Starlette

from sdd import __version__
from sdd.errors import SddError
from sdd.service import changes, context, coordination, query_guard
from sdd.service.runtime import Runtime

__all__ = ["INSTRUCTIONS", "TOOLS", "create_server", "streamable_app"]

# The three-line protocol (SPEC-05 §9); the full one is in .claude/skills/sdd/SKILL.md.
INSTRUCTIONS = (
    'Session start: what_changed(since="last_session", agent=<your name>); use the same agent '
    "name every session.\n"
    "Orchestrator: status, then next_tasks; one subagent per task without overlaps; "
    "release_task(force=true) for a failed one; complete_milestone when acceptance holds.\n"
    "Worker: claim_task, then get_context; build and test; log_deviation for every intentional "
    "departure; complete_task with notes, files_touched and commit."
)

# SPEC-05 §2: the tools this server registers (checked against the spec index by the tests).
TOOLS = (
    "status",
    "next_tasks",
    "claim_task",
    "release_task",
    "get_context",
    "read_section",
    "log_deviation",
    "complete_task",
    "complete_milestone",
    "what_changed",
    "query",
)

Agent = Annotated[str, Field(description="Your agent name, the same every session.")]
OptAgent = Annotated[
    str | None, Field(description="Your agent name (marks you as alive for your claims).")
]
TaskId = Annotated[str, Field(description="Task ID, e.g. M02.3.")]


def _result(fn: Callable[[], dict[str, Any]]) -> CallToolResult:
    try:
        payload = fn()
    except SddError as err:
        error = err.to_dict()
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(error, ensure_ascii=False))],
            structured_content=error,
            is_error=True,
        )
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
    )


def create_server(runtime: Runtime) -> MCPServer:
    """An ``MCPServer`` whose tools act on ``runtime``."""
    server: MCPServer = MCPServer(name="sdd", instructions=INSTRUCTIONS, version=__version__)

    @server.tool()
    def status(agent: OptAgent = None) -> CallToolResult:
        """Milestones with task counts, active claims with their age, warning count, synced_at."""
        return _result(lambda: coordination.status(runtime, agent))

    @server.tool()
    def next_tasks(
        milestone: Annotated[str | None, Field(description="Only this milestone.")] = None,
        limit: Annotated[int, Field(ge=1, le=coordination.MAX_LIMIT)] = 10,
        agent: OptAgent = None,
    ) -> CallToolResult:
        """Claimable tasks in order, each with `overlaps`: claimed tasks sharing a governing
        section or file (running both in parallel may conflict)."""
        return _result(lambda: coordination.next_tasks(runtime, milestone, limit, agent))

    @server.tool()
    def claim_task(task_id: TaskId, agent: Agent) -> CallToolResult:
        """Claim a task atomically. Re-claiming your own task succeeds; a claim whose holder has
        not been seen for the TTL is taken over."""
        return _result(lambda: coordination.claim_task(runtime, task_id, agent))

    @server.tool()
    def release_task(
        task_id: TaskId,
        agent: Agent,
        reason: str | None = None,
        force: Annotated[
            bool, Field(description="Free a claim another agent holds (it has stopped).")
        ] = False,
    ) -> CallToolResult:
        """Give a claim back; with force, free another agent's claim."""
        return _result(lambda: coordination.release_task(runtime, task_id, agent, reason, force))

    @server.tool()
    def get_context(
        task_id: TaskId,
        detail: Annotated[
            str,
            Field(
                description='"task" (default): what this task needs; "milestone": every section '
                "the milestone reads.",
                pattern="^(task|milestone)$",
            ),
        ] = "task",
        max_chars: Annotated[int, Field(ge=context.MIN_CHARS, le=context.MAX_CHARS)] = 24000,
        agent: OptAgent = None,
    ) -> CallToolResult:
        """The context packet for a task: governing spec sections in full (with descendants and
        the deviations amending them), an outline of the milestone's other reading, checks,
        upstream task notes and related code. Use it instead of reading spec files."""
        return _result(lambda: context.get_context(runtime, task_id, detail, max_chars, agent))

    @server.tool()
    def read_section(
        refs: Annotated[
            list[str],
            Field(
                description="Spec references, e.g. ['SPEC-03 §4.2', 'SPEC-02 §3–4', "
                "'SPEC-02 `documents`'].",
                min_length=1,
            ),
        ],
        agent: OptAgent = None,
    ) -> CallToolResult:
        """The text of spec sections by reference, each with its subsections. Replaces grep and
        reading the file."""
        return _result(lambda: context.read_section(runtime, refs, agent))

    @server.tool()
    def log_deviation(  # noqa: PLR0917 (an MCP tool takes its arguments by name)
        task_id: TaskId,
        agent: Agent,
        title: Annotated[str, Field(description="One line.")],
        spec_says: str,
        implementation_does: str,
        why: str,
        amends: Annotated[
            list[str], Field(description="Spec references, e.g. ['SPEC-04 §5.1'].", min_length=1)
        ],
        consequences: str | None = None,
        affects: Annotated[
            list[str] | None, Field(description="Project file paths or table names.")
        ] = None,
        status: Annotated[str, Field(pattern="^(open|resolved)$")] = "open",
    ) -> CallToolResult:
        """Log an intentional departure from a spec: writes the deviation file, the index row
        and a note in each amended section, in one atomic change. Returns {id, path}."""
        return _result(
            lambda: coordination.log_deviation(
                runtime,
                task_id,
                agent,
                title=title,
                spec_says=spec_says,
                implementation_does=implementation_does,
                why=why,
                consequences=consequences,
                amends=amends,
                affects=affects,
                status=status,
            )
        )

    @server.tool()
    def complete_task(
        task_id: TaskId,
        agent: Agent,
        notes: str | None = None,
        files_touched: list[str] | None = None,
        commit: Annotated[str | None, Field(description="Git SHA of the work.")] = None,
    ) -> CallToolResult:
        """Tick the task's box, record notes, files and commit, return newly unblocked tasks.
        You must hold the claim."""
        return _result(
            lambda: coordination.complete_task(
                runtime, task_id, agent, notes=notes, files_touched=files_touched, commit=commit
            )
        )

    @server.tool()
    def complete_milestone(
        milestone_id: Annotated[str, Field(description="Milestone ID, e.g. M02.")],
        agent: Agent,
        verification: Annotated[str, Field(description="How acceptance was verified.")],
    ) -> CallToolResult:
        """Write the DONE status line (with the milestone's deviations), move the file to done/
        and fix links to it. Every task must be done."""
        return _result(
            lambda: coordination.complete_milestone(runtime, milestone_id, agent, verification)
        )

    @server.tool()
    def what_changed(
        since: Annotated[
            str, Field(description='An ISO time, an event ID, or "last_session" (needs agent).')
        ],
        agent: OptAgent = None,
    ) -> CallToolResult:
        """What changed since then: sections, specs, deviations, tasks completed and claimed,
        milestones done. Use it instead of re-reading docs at session start."""
        return _result(lambda: changes.what_changed(runtime, since, agent))

    @server.tool()
    def query(
        cypher: Annotated[str, Field(description="One read-only Cypher statement.")],
        params: dict[str, Any] | None = None,
        agent: OptAgent = None,
    ) -> CallToolResult:
        """Read-only Cypher through the guard: no writes or CALL, variable-length patterns at
        most *..4, 100 rows, 5 s. Returns {columns, rows, truncated}."""
        return _result(lambda: query_guard.run_query(runtime, cypher, params, agent))

    return server


def streamable_app(server: MCPServer) -> Starlette:
    """The SDK's streamable HTTP app, route ``/mcp``. Host and Origin are checked by the
    daemon's own middleware (SPEC-09 §2), so the SDK's duplicate check is off."""
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
