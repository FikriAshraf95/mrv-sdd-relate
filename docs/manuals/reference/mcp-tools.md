# MCP tools reference

> The 14 tools the daemon serves at `http://localhost:8770/mcp` (MCP streamable HTTP, server name `sdd`). The source of truth is [SPEC-05 §2](../../specs/SPEC-05-agent-tools.md#2-tool-index).

## Common rules

- **`agent`** is your own name (`opus-orch`, `sonnet-2`), **the same every session**. It's required on write tools and optional on reads. Any call that passes it updates your `last_seen`, which keeps your claims alive ([claims](../03-concepts.md#34-claims)).
- **Every result carries `synced_at`**, the last sync time, so you can tell when context may be stale.
- **Errors** come back as a tool error whose content is `{"error": {"code", "message", "retryable", "details"}}`. Codes are stable ([Error codes](error-codes.md)). The message says what to do next. Check `code`, not the message text.
- **Writes are atomic.** Each write tool runs as one job on the single writer: check, change the graph, write back Markdown, emit an event, all or nothing.
- **IDs are forgiving.** `m5a.3`, `M05a.3`, `SPEC-3 §2`, `spec-03#2` and `SPEC-03§2` are all normalised.
- The same results are available over HTTP ([HTTP API](http-api.md)) and the CLI ([CLI](cli.md)).

| # | Tool | Writes |
|---|---|---|
| 1 | [`status`](#status) | |
| 2 | [`next_tasks`](#next_tasks) | |
| 3 | [`claim_task`](#claim_task) | ✓ |
| 4 | [`release_task`](#release_task) | ✓ |
| 5 | [`get_context`](#get_context) | |
| 6 | [`read_section`](#read_section) | |
| 7 | [`log_deviation`](#log_deviation) | ✓ |
| 8 | [`complete_task`](#complete_task) | ✓ |
| 9 | [`complete_milestone`](#complete_milestone) | ✓ |
| 10 | [`what_changed`](#what_changed) | |
| 11 | [`impact`](#impact) | |
| 12 | [`explain`](#explain) | |
| 13 | [`find_code`](#find_code) | |
| 14 | [`query`](#query) | |

---

## `status`

| Parameter | Type | Default |
|---|---|---|
| `agent` | string | none |

Milestones with task counts and status, active claims with their age, warning counts, `synced_at`.

```json
status({"agent": "opus-orch"})
```

## `next_tasks`

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `milestone` | string | all | only this milestone |
| `limit` | int | 10 | 1 to 100 |
| `agent` | string | none | |

Claimable tasks: status `todo`, no live claim, every `(after …)` task done, every `Depends on` milestone done. Ordered by milestone, then task position.

Returns `{tasks: [{id, title, milestone_id, group, governed_by: [section ids], overlaps: [{id, claimed_by, …}]}], total, synced_at}`. **`overlaps`** lists tasks claimed right now that share a governing section or a mentioned file: running both at once may conflict.

```json
next_tasks({"milestone": "M05a", "limit": 5, "agent": "opus-orch"})
```

## `claim_task`

| Parameter | Type | Required |
|---|---|---|
| `task_id` | string | ✓ |
| `agent` | string | ✓ |

Claims a task atomically: of two simultaneous claims exactly one wins. Re-claiming your own task succeeds (`already_held: true`). A claim whose holder hasn't been seen for `SDD_CLAIM_TTL` (2 h) is taken over, and `released_stale_claim_of` names the old holder.

Returns `{task, agent, status: "claimed", claimed_at, already_held, released_stale_claim_of, synced_at}`.

Errors: `already_claimed` (details `claimed_by`, `claimed_at`), `task_done`, `task_blocked` (details: the blockers), `task_not_found`.

```json
claim_task({"task_id": "M05a.3", "agent": "sonnet-1"})
```

## `release_task`

| Parameter | Type | Default |
|---|---|---|
| `task_id` | string | required |
| `agent` | string | required |
| `reason` | string | none |
| `force` | bool | `false` |

Gives a claim back. With `force: true`, frees a claim another agent holds (the event records `data.forced_by`). Without `force`, you must hold it.

Returns `{task, released, claimed_by: <old holder>, forced, synced_at}`.

Errors: `not_claimed_by_you`, `task_not_found`.

```json
release_task({"task_id": "M05a.3", "agent": "opus-orch", "reason": "sonnet-1 crashed", "force": true})
```

## `get_context`

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `task_id` | string | required | |
| `detail` | `"task"` \| `"milestone"` | `"task"` | `milestone` puts every *Read first* section in `sections` |
| `max_chars` | int | 24000 | 1 000 to 1 000 000 |
| `agent` | string | none | |

The context packet: the minimum needed to build one task.

```json
{
  "task": {"id": "M05a.3", "title": "…", "group": "Backend", "status": "claimed", "blocked_by": ["M05a.2"]},
  "milestone": {"id": "M05a", "title": "Waitlist", "goal": "…", "acceptance": ["…"], "model": "Opusplan"},
  "sections": [{"id": "SPEC-05#2", "title": "Promotion", "text": "…", "why": "governs task", "amended_by": ["D006"]}],
  "outline": [{"id": "SPEC-05#1", "title": "Joining the waitlist", "why": "milestone reads", "chars": 640}],
  "checks": [{"id": "SPEC-05#ac1", "text": "…"}],
  "deviations": [{"id": "D006", "title": "…", "status": "open", "implementation_does": "…", "amends": ["SPEC-05#2"]}],
  "upstream": [{"id": "M05a.2", "title": "…", "notes": "…", "files_touched": ["src/waitlist/promote.py"]}],
  "code": {"features": ["waitlist"], "files": ["src/waitlist/promote.py"], "tables": ["bookings"],
           "recent_commits": [{"short": "0d47c9d", "message": "feat: promote the oldest waiting entry [M05a.2]"}]},
  "size": {"chars": 3122, "tokens_est": 781, "truncated": []},
  "synced_at": "2026-11-22T08:28:59Z"
}
```

- **`sections`** (full text, each subsection its own item): the sections the task line links, the *Acceptance checks* of any spec whose checks it verifies, and every `always_include` section. If the task links nothing, the milestone's *Read first* sections are used instead.
- **`outline`**: the milestone's other *Read first* targets, by ID, title and size. Fetch them with `read_section`.
- **`deviations`**: every deviation amending an included section. Open ones carry `implementation_does`; resolved ones only their title.
- **`upstream`**: the tasks it waits on, and done tasks of the same milestone, with notes and files touched.
- **`code`**: features of the governing specs, their files (up to 50), tables mentioned, the 5 latest commits touching those files.
- Above `max_chars`, parts are dropped in this order: code, upstream, outline, then the longest non-governing sections. Each drop is listed in `size.truncated`. A section is never cut in the middle.

Errors: `task_not_found`, `invalid_input`.

## `read_section`

| Parameter | Type | Required |
|---|---|---|
| `refs` | list of strings | ✓ (at least one) |
| `agent` | string | |

Text of spec sections by reference, each with its descendants. Reference forms: `"SPEC-03 §4.2"`, `"SPEC-02 §3–4"`, ``"SPEC-02 `bookings`"``, `"SPEC-03#4.2"`, `"SPEC-03"` (whole spec).

Returns `{sections: [{id, spec_id, number, title, level, text, amended_by: [deviation ids]}], synced_at}`.

Errors: `unknown_section`.

```json
read_section({"refs": ["SPEC-05 §1", "SPEC-02 `waitlist_entries`"], "agent": "sonnet-1"})
```

## `log_deviation`

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `task_id` | string | ✓ | the task the deviation is raised in |
| `agent` | string | ✓ | |
| `title` | string | ✓ | one line |
| `spec_says` | string | ✓ | |
| `implementation_does` | string | ✓ | |
| `why` | string | ✓ | |
| `amends` | list of strings | ✓ | spec references; each must resolve |
| `consequences` | string | | |
| `affects` | list of strings | | project file paths and table names |
| `status` | `"open"` \| `"resolved"` | | default `"open"` |

Writes the deviation file (next free D-number), the index row at the top of `DEVIATIONS.md`, and a `> **DEVIATION:**` note at the end of each amended section, in one atomic job. Creates `AMENDS`, `RAISED_IN` (milestone and task) and `AFFECTS` links, all rebuildable from the file. See [Log a deviation](../how-to/log-a-deviation.md).

Returns `{id, path, amends: [section ids], files: [paths written], synced_at}`.

Errors: `unknown_section`, `invalid_input` (an `affects` entry naming no file or table, a multi-line title), `task_not_found`, `writeback_disabled`, `source_changed`.

## `complete_task`

| Parameter | Type | Required |
|---|---|---|
| `task_id` | string | ✓ |
| `agent` | string | ✓ (must hold the claim) |
| `notes` | string | |
| `files_touched` | list of strings | |
| `commit` | string (git SHA) | |

Ticks the task's box (`[ ]` → `[x]`, nothing else on the line changes), records `notes` and `files_touched` in the event (shown to later tasks as `upstream`), links `TOUCHES` to the files and `COMPLETES` from the commit, and returns the tasks this unblocked. With `writeback = false`, completion is recorded in the graph only.

Returns `{task, status: "done", path, changed_file, unblocked: [...], synced_at}`.

Errors: `not_claimed_by_you`, `task_not_found`, `source_changed` (the line is gone from the file).

```json
complete_task({"task_id": "M05a.3", "agent": "sonnet-1",
  "notes": "One message with a confirm link; reuses the held booking.",
  "files_touched": ["src/waitlist/promote.py"], "commit": "a1b2c3d"})
```

## `complete_milestone`

| Parameter | Type | Required |
|---|---|---|
| `milestone_id` | string | ✓ |
| `agent` | string | ✓ |
| `verification` | string | ✓ how acceptance was verified |

Replaces the milestone's `**Status:**` paragraph with `**Status:** DONE (<today>). <verification> Deviations: <list or none>.`, moves the file and its plan file to `done/` if that folder exists, and rewrites every relative link to the moved files.

Returns `{milestone, status: "done", status_line, deviations, path, moved_from, files, synced_at}`.

Errors: `milestone_incomplete` (lists the open tasks), `milestone_not_found`, `writeback_disabled`, `source_changed`.

## `what_changed`

| Parameter | Type | Required |
|---|---|---|
| `since` | string | ✓ an ISO time, an event ID, or `"last_session"` |
| `agent` | string | needed for `"last_session"` |

`"last_session"` means "since this agent's previous `what_changed` call". An agent's first call returns the last 24 h with `first_session: true`. Bounds are inclusive.

Returns `{since, first_session, sections_changed, specs_added, specs_removed, deviations, tasks_completed, tasks_claimed, milestones_done, synced_at}`. Each item has `id`, `title` where it applies, `actor` and `at`.

```json
what_changed({"since": "last_session", "agent": "opus-orch"})
```

## `impact`

| Parameter | Type | Default |
|---|---|---|
| `target` | string | required: table, `table.column`, spec reference, task, milestone, deviation, file path, feature, or prefixed ID (`table:x`, `column:t.c`, `file:p`, `feature:s`, `domain:s`) |
| `depth` | int | 3 (1 to 5) |
| `agent` | string | |

"If this changes, what else is affected?"

```json
{
  "target": {"id": "table:bookings", "label": "Table", "title": "bookings"},
  "groups": {"specs": [], "sections": [], "milestones": [], "tables": [], "features": [], "files": [],
             "tasks_open": [], "tasks_done": [], "deviations": [], "tests": [], "commits": []},
  "counts": {"specs": 5, "files": 16, "…": 0},
  "synced_at": "…"
}
```

Each item is `{id, label, title, via: ["table:bookings", "<-USES_TABLE", "feature:booking", "->SPECIFIED_BY", "SPEC-03"]}`, plus `status` for tasks and deviations. Up to 50 items per group; `counts` has the totals. Errors: `ambiguous_target` (details `candidates`), `node_not_found`.

## `explain`

| Parameter | Type |
|---|---|
| `path` | string: a project file path; a unique tail is enough |
| `agent` | string |

"Why does this file exist, and what shaped it?" Returns `{file: {id, path, language, is_test}, features: [{id, name, domain, specs, via}], sections: [{id, title, via}], tasks: [{id, title, status, milestone, notes, via}], commits: [{sha, short, message, at, tasks, via}], deviations: [{id, title, status, via}], checks: [{id, spec_id, text, via}], summary, synced_at}`.

Errors: `file_not_found`, `ambiguous_target`.

## `find_code`

| Parameter | Type |
|---|---|
| `feature`, `domain`, `table`, `spec`, `text` | string; at least one; several intersect |
| `agent` | string |

Files by feature, domain, table, spec or path substring. Returns `{files: [{path, language, via}] (sorted, up to 50), counts: {files}, synced_at}`.

## `query`

| Parameter | Type |
|---|---|
| `cypher` | string: one read-only statement |
| `params` | object |
| `agent` | string |

Read-only Cypher through the query guard: no `CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `LOAD`, `FOREACH`, `CALL`, `USE`, `IN TRANSACTIONS`, or second statement; variable-length patterns at most `*..4`; 100 rows; 5 s; always rolled back.

Returns `{columns: [...], rows: [[...], ...], truncated}`. Each row is a list in column order. Nodes and relationships come back as their property maps.

Errors: `query_rejected`, `query_timeout`, `invalid_input` (syntax errors).

```json
query({"cypher": "MATCH (t:Task {status: $s}) RETURN t.id, t.title ORDER BY t.id", "params": {"s": "todo"}})
```

More in [Example Cypher queries](cypher-examples.md).
