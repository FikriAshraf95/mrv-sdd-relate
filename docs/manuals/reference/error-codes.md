# Error codes

> One error shape everywhere: `{"error": {"code", "message", "retryable", "details"}}`. Codes are stable; match on `code`, never on the message. The source of truth is [SPEC-05 §8](../../specs/SPEC-05-agent-tools.md#8-error-codes).

| Code | HTTP | CLI exit | Raised by | What to do |
|---|---|---|---|---|
| `invalid_input` | 400 | 2 | any tool, endpoint or command, on bad arguments; bad `.sdd/config.toml`; engine syntax errors in `query` | read the message; it names the argument |
| `ambiguous_target` | 400 | 2 | `impact`, `explain` | repeat with one of `details.candidates` (e.g. `table:payments`) |
| `task_not_found` | 404 | 3 | lookups by task ID | check the ID with `sdd status`; IDs are case-insensitive and zero-padded (`m5a.3` = `M05a.3`) |
| `milestone_not_found` | 404 | 3 | lookups by milestone ID | as above |
| `node_not_found` | 404 | 3 | `impact`, presets, `/api/nodes` | the target doesn't exist in the graph; check spelling or sync |
| `file_not_found` | 404 | 3 | `explain` on a path with no File node | the path is wrong, ignored (`.gitignore`, `.sddignore`), or not synced yet |
| `unknown_section` | 404 | 3 | `read_section`, `log_deviation(amends)` | the reference doesn't resolve; try `sdd section "<ref>"` |
| `already_claimed` | 409 | 4 | `claim_task` | `details.claimed_by` has it; pick another from `next_tasks` |
| `task_done` | 409 | 4 | `claim_task` | already done; pick another |
| `task_blocked` | 409 | 4 | `claim_task` | `details` lists blockers (`(after …)` tasks or unfinished milestones) |
| `not_claimed_by_you` | 409 | 4 | `complete_task`, `release_task` | claim it first, or use `force` on release if the holder died |
| `milestone_incomplete` | 409 | 4 | `complete_milestone` | the message lists the open tasks |
| `source_changed` | 409 | 4 | write tools whose Markdown target is gone | someone edited the line or section away; re-read and retry |
| `daemon_running` | 409 | 4 | `sdd daemon`, `sdd sync`, `sdd ids --write`, `sdd snapshot` without the relate CLI | another process owns the store; see [Troubleshooting](../troubleshooting.md#store-is-locked--daemon_running) |
| `write_conflict` | 503 | 5 | any write, after 3 retries (50/200/800 ms) | retryable; try again |
| `writeback_disabled` | 403 | 1 | `log_deviation`, `complete_milestone` when `writeback = false` | turn write-back on, or edit the Markdown by hand |
| `query_rejected` | 400 | 1 | the query guard; public presets-only mode | remove the write clause, `CALL`, unbounded `*`, or the second statement |
| `query_timeout` | 503 | 1 | the query guard (5 s, or memory cap) | add `LIMIT`, bound patterns, narrow the `MATCH` |
| `read_only` | 403 | 1 | write endpoints in public mode | use the daemon for writes |
| `unauthorized` | 401 | 1 | requests without the bearer token when `SDD_TOKEN` is set | send `Authorization: Bearer <token>` |
| `forbidden_origin` | 403 | 1 | writes and `/mcp` with a foreign `Origin` | call from a tool (no `Origin`) or the daemon's own page |
| `forbidden_host` | 403 | 1 | a `Host` header that isn't loopback or in `SDD_ALLOWED_HOSTS` | add the host to `SDD_ALLOWED_HOSTS` |
| `rate_limited` | 429 | 1 | public mode rate limits | wait `Retry-After` seconds |

`retryable` is always `true` for `write_conflict` and `rate_limited`. Some `query_timeout` errors are also marked retryable, for example when another guarded query held the single query slot or the worker didn't start. Trust the flag on the error you got.
