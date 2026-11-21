# SPEC-05 — Agent tools (MCP)

> **Status:** v1 (2026-11-21) · **Owner of:** every MCP tool, claim rules, the context packet, error codes, Claude Code integration
> Server: `mcp` 2.x `MCPServer`, mounted at `/mcp` on the daemon ([SPEC-01 §5](SPEC-01-architecture.md#5-daemon-lifecycle)) · Code-context tools: [SPEC-06](SPEC-06-code-context.md)

## 1. Rules

1. Tools validate input, call one `service/` function, and return JSON. Every tool's result is also what the matching HTTP endpoint ([SPEC-07](SPEC-07-dashboard-and-api.md)) and CLI command return.
2. **Every tool takes `agent`** (a free name such as `opus-orch`, `sonnet-2`): required on write tools, optional on read tools. Claude Code subagents share their parent's MCP connection, so identity cannot come from the connection. Any tool call with `agent` updates `Agent.last_seen`, which is how the daemon knows an agent is alive ([§3](#3-claims)). Agents keep the **same name across sessions** (the orchestrator is `opus-orch`), so `what_changed` and claims follow them.
3. Writes run as one job in the write queue: check, change the graph, write back Markdown, emit an Event, all or nothing.
4. Results are compact: IDs, titles and text, never whole files. Every result carries `synced_at` (the last sync time) so an agent can tell if context may be stale.

## 2. Tool index

| # | Tool | Writes | Summary |
|---|---|---|---|
| 1 | `status(agent?)` | | Milestones with task counts, active claims with their age, warning count, `synced_at` |
| 2 | `next_tasks(milestone?, limit=10, agent?)` | | Claimable tasks, in order ([§3](#3-claims)) |
| 3 | `claim_task(task_id, agent)` | ✓ | Atomic claim |
| 4 | `release_task(task_id, agent, reason?, force=false)` | ✓ | Give a claim back; `force` frees another agent's claim ([§3](#3-claims)) |
| 5 | `get_context(task_id, detail="task", max_chars=24000, agent?)` | | The context packet ([§4](#4-get_context)) |
| 6 | `read_section(refs, agent?)` | | Text of one or more sections by reference (`"SPEC-03 §4.2"`, `` "SPEC-02 `documents`" ``); replaces grep + Read |
| 7 | `log_deviation(task_id, agent, title, spec_says, implementation_does, why, consequences?, amends, affects?, status="open")` | ✓ | Logs a deviation the way the manual ritual does ([SPEC-04 §5.1](SPEC-04-sync.md#51-edits)) |
| 8 | `complete_task(task_id, agent, notes?, files_touched?, commit?)` | ✓ | Ticks the box, records the outcome, returns newly unblocked tasks |
| 9 | `complete_milestone(milestone_id, agent, verification)` | ✓ | Writes the DONE status line ([§6](#6-complete_milestone)) |
| 10 | `what_changed(since, agent?)` | | Changes since a time, an event or `"last_session"` ([§7](#7-what_changed)) |
| 11 | `impact(target, depth=3, agent?)` | | [SPEC-06 §2](SPEC-06-code-context.md#2-impact) |
| 12 | `explain(path, agent?)` | | [SPEC-06 §3](SPEC-06-code-context.md#3-explain) |
| 13 | `find_code(feature?, domain?, table?, spec?, text?, agent?)` | | [SPEC-06 §4](SPEC-06-code-context.md#4-find_code) |
| 14 | `query(cypher, params?, agent?)` | | Read-only Cypher through the guard ([SPEC-09 §3](SPEC-09-security.md#3-query-guard)), 100-row cap |

## 3. Claims

- **Claimable** = `status = todo`, no live claim, every `BLOCKED_BY` task `done`, and every `DEPENDS_ON` milestone `done`.
- `next_tasks` returns claimable tasks ordered by milestone `order`, then task `order`. Each item: `id`, `title`, `milestone_id`, `group`, `governed_by` (IDs), and `overlaps`: tasks claimed right now that share a governing section or a mentioned file, as a hint that running them in parallel may conflict.
- `claim_task` checks and sets in **one write job**, so of two simultaneous claims exactly one wins. Re-claiming your own task succeeds (idempotent).
- **Stale claims** ([DEC-003](../decisions/DEC-003-claim-liveness.md)): a claim is stale when the claiming agent's `last_seen` is older than `SDD_CLAIM_TTL` (default **2 h**, long enough that a working agent, which may go quiet during a long build or test run, never looks dead). A claim on a stale task succeeds and emits `task_released` (actor `sync`) before `task_claimed`. There is no heartbeat tool: an agent blocked in one long command could not call it anyway.
- **Forced release:** `release_task(task_id, agent, force=true)` frees a claim held by someone else, for when the orchestrator or a human knows the holder has died and should not wait for the TTL. It emits `task_released` with `actor` = the claim holder and `data.forced_by` = the caller. Without `force`, `complete_task` and `release_task` require the caller to hold the claim (`not_claimed_by_you`).
- A task ticked by hand in Markdown is done whoever held it; the claim is cleared.

## 4. `get_context`

The minimum an agent needs to build one task, so it does not read whole files.

```json
{
  "task": {"id": "M02.3", "title": "…", "group": "Sync", "status": "claimed", "blocked_by": []},
  "milestone": {"id": "M02", "title": "…", "goal": "…", "acceptance": ["…"], "model": "Opusplan"},
  "sections": [{"id": "SPEC-04#2", "title": "Incremental sync", "text": "…", "why": "governs task",
                "amended_by": ["D004"]}],
  "outline": [{"id": "SPEC-04#5", "title": "Write-back", "why": "milestone reads", "chars": 3120}],
  "checks": [{"id": "SPEC-04#ac2", "text": "…"}],
  "deviations": [{"id": "D004", "title": "…", "status": "open", "implementation_does": "…", "amends": ["SPEC-04#2"]}],
  "upstream": [{"id": "M02.1", "title": "…", "notes": "…", "files_touched": ["src/sdd/sync/watcher.py"]}],
  "code": {"features": ["sync"], "files": ["src/sdd/sync/indexer.py"], "tables": [],
           "recent_commits": [{"short": "a1b2c3d", "message": "…"}]},
  "size": {"chars": 9120, "tokens_est": 2280, "truncated": []},
  "synced_at": "2026-11-25T03:12:00Z"
}
```

Every section named below is included **with its descendants** ([SPEC-03 §2.2](SPEC-03-markdown-parsing.md#22-spec-reference-grammar)): `SPEC-00#6` brings §6.1–6.7 along. Each descendant is its own item in `sections` (so `amended_by` stays per section), in document order, with `why` naming the reference that pulled it in.

What goes where, with `detail = "task"` (default):
1. **`sections` (full text):** the task's `GOVERNED_BY` sections; the sections of its `VERIFIES` checks' spec named in the task line; every section in `always_include` (config, default `SPEC-00#6` when it exists). If the task governs nothing, the milestone's `READS` sections are used instead.
2. **`outline`:** the milestone's other `READS` targets as `id`, `title`, `chars`. A `whole: true` spec appears as its section list. The agent fetches what it needs with `read_section`.
3. **`deviations`:** every deviation that `AMENDS` an included section. Open ones carry `implementation_does`; resolved ones carry the title only, since the spec already says it.
4. **`upstream`:** `BLOCKED_BY` tasks and done tasks of the same milestone, with completion notes and files touched from their Events.
5. **`code`:** features of the governing specs, their files (max 50 paths), tables mentioned by the task or its sections, and the 5 latest commits touching those files.

`detail = "milestone"` puts every `READS` section in `sections` (the Markdown-equivalent view, used by the benchmark). Above `max_chars`, parts are dropped in this order (code, upstream, outline, then the longest non-governing sections) and listed in `truncated`. Spec text is never cut mid-section.

## 5. `log_deviation`

- `amends`: one or more spec references (grammar in [SPEC-03 §2.2](SPEC-03-markdown-parsing.md#22-spec-reference-grammar)), at least one, each must resolve (`unknown_section`).
- Creates the file, index row and spec notes ([SPEC-04 §5.1](SPEC-04-sync.md#51-edits)), the Deviation node with `RAISED_IN` the task and its milestone, `AMENDS`, and `AFFECTS` for `affects` entries that resolve to a File or Table (an entry that resolves to neither is `invalid_input`). The task and the affects list are written into the file, so these links are owned by it (`src` = its path) and survive a rebuild.
- Returns `{id, path}`. Every agent whose current claim's context includes an amended section sees the deviation on its next `get_context` or `what_changed`.

## 6. `complete_milestone`

Fails with `milestone_incomplete` (listing the open tasks) unless every task is done. Writes the status line with today's date, the given verification text and the deviations `RAISED_IN` the milestone (or "Deviations: none"); moves the file per [SPEC-04 §5.1](SPEC-04-sync.md#51-edits); emits `milestone_done`.

## 7. `what_changed`

`since` is an ISO time, an event ID, or `"last_session"` (needs `agent`). **`"last_session"` means "since this agent last called `what_changed`"** ([DEC-003](../decisions/DEC-003-claim-liveness.md)): every call stores `Agent.last_changes_at`, and the next `last_session` call returns everything after the previous value. No session boundaries are guessed. An agent's first call returns the last 24 h with `first_session: true`. Returns grouped lists: `sections_changed` (id, title, changed_at), `specs_added`, `specs_removed`, `deviations` (logged or status changed), `tasks_completed`, `tasks_claimed`, `milestones_done`, each item with actor and time. This replaces re-reading files to see what moved.

## 8. Error codes

The complete list for MCP, HTTP and CLI. A new code is added here in the same change as the code that raises it.

| Code | Raised by |
|---|---|
| `invalid_input` | any tool, endpoint or command, on bad arguments |
| `task_not_found`, `milestone_not_found`, `node_not_found`, `file_not_found` | lookups by ID or path (`file_not_found`: `explain` on a path with no File node) |
| `unknown_section` | `read_section`, `log_deviation(amends)` |
| `ambiguous_target` (details: `candidates`) | `impact`, `explain` target resolution ([SPEC-06 §2](SPEC-06-code-context.md#2-impact)) |
| `already_claimed` (details: `claimed_by`, `claimed_at`), `task_done`, `task_blocked` (details: blockers) | `claim_task` |
| `not_claimed_by_you` | `complete_task`, `release_task` |
| `milestone_incomplete` | `complete_milestone` |
| `source_changed` | write tools whose Markdown target is gone ([SPEC-04 §5.2](SPEC-04-sync.md#52-safety)) |
| `writeback_disabled` | `log_deviation`, `complete_milestone` when `writeback = false` |
| `write_conflict` (retryable) | any write, after retries |
| `query_rejected`, `query_timeout` | the query guard |
| `daemon_running` | `sdd daemon`, `sdd sync`, `sdd ids --write` |
| `read_only` | write endpoints in public mode |
| `unauthorized` | requests without the bearer token when `SDD_TOKEN` is set |
| `forbidden_origin`, `forbidden_host` | the Origin and Host checks ([SPEC-09 §2](SPEC-09-security.md#2-local-daemon)) |
| `rate_limited` (retryable) | public mode rate limits |

## 9. Claude Code integration

- `sdd init` writes `.mcp.json`: `{"mcpServers": {"sdd": {"type": "http", "url": "http://localhost:8770/mcp"}}}` (plus a bearer header when `SDD_TOKEN` is set). An existing `.mcp.json` is **merged**: the `sdd` entry is added and other servers are kept; only an existing `sdd` entry needs `--force` to replace.
- It also writes `.claude/skills/sdd/SKILL.md` with the **agent protocol**, and offers a CLAUDE.md snippet:
  - **Orchestrator:** `status` → `next_tasks` → launch one subagent per task that has no `overlaps`, telling each its agent name and task ID → review returned work; if a subagent failed, `release_task(…, force=true)` its task → `complete_milestone` when the acceptance criteria are verified.
  - **Worker:** `claim_task` → `get_context` → `read_section` for anything in `outline` it needs → build and test → `log_deviation` for every intentional departure → `complete_task` with notes, files and commit → report.
  - **Any session start:** `what_changed(since="last_session", agent=<own name>)` instead of re-reading docs.
- The server's MCP `instructions` field carries a three-line version of the protocol.

## 10. Acceptance checks

1. `next_tasks` never returns a task whose milestone depends on an unfinished milestone, or whose `BLOCKED_BY` task is open.
2. `claim_task` by the same agent twice succeeds both times; the graph has one CLAIMED relationship.
3. Ten threads claiming the same task: exactly one succeeds, nine get `already_claimed`.
4. A claim whose agent has not been seen for longer than the TTL can be claimed by another agent, and a `task_released` event is recorded.
5. `get_context` for a task with a governing section amended by an open deviation includes that section's full text and the deviation's `implementation_does`.
6. `get_context` output above `max_chars` drops parts in the documented order and never cuts a section.
7. `complete_task` ticks the line, records notes and files in the event, and returns the tasks it unblocked.
8. `complete_milestone` with an open task fails with `milestone_incomplete`; with all done, it writes the status line listing the milestone's deviations.
9. `what_changed(since="last_session", agent=A)` returns a section edited by a human after A's previous `what_changed` call, and not one edited before it; A's first call ever returns the last 24 h with `first_session: true`.
10. `read_section("SPEC-02 §3–4")` returns two sections.
11. `release_task(T, agent=B, force=true)` on a task claimed by A frees it, records `task_released` with `data.forced_by = B`, and a third agent can then claim it; without `force`, B gets `not_claimed_by_you`.
12. A claim whose agent keeps calling read tools with `agent` (and no write tool) for longer than the TTL is not stale.
