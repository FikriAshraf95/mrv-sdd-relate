# HTTP API reference

> Every endpoint the daemon (`:8770`) and the public server (`:8780`) serve. The source of truth is [SPEC-07 §2](../../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index).

## Rules

- **JSON in, JSON out**, `snake_case` fields, UTC timestamps ending in `Z`. Results equal the matching MCP tool's.
- **Percent-encode IDs and references in URLs** (`encodeURIComponent`), because they contain `#`, `/`, `:`, spaces and `§`:
  `GET /api/nodes/SPEC-02%232` · `GET /api/nodes/file%3Asrc%2Fbooking%2Foverlap.py` · `GET /api/sections/SPEC-03%20%C2%A74.2`.
- **`agent`** goes in the query string on reads that mirror a tool (`?agent=sonnet-1`) and in the JSON body on writes. Public mode ignores it.
- **Errors** use `{"error": {"code", "message", "retryable", "details"}}` with these statuses:

| Status | Codes |
|---|---|
| 400 | `invalid_input`, `query_rejected`, `ambiguous_target` |
| 401 | `unauthorized` |
| 403 | `read_only`, `forbidden_origin`, `forbidden_host`, `writeback_disabled` |
| 404 | `task_not_found`, `milestone_not_found`, `node_not_found`, `file_not_found`, `unknown_section` |
| 409 | `already_claimed`, `task_done`, `task_blocked`, `not_claimed_by_you`, `milestone_incomplete`, `source_changed`, `daemon_running` |
| 429 | `rate_limited` (with `Retry-After`) |
| 503 | `write_conflict`, `query_timeout` |

- **Auth and checks (daemon only):** with `SDD_TOKEN` set, every `/api` and `/mcp` request needs `Authorization: Bearer <token>`. The `Host` must be loopback or listed in `SDD_ALLOWED_HOSTS`. Writes and `/mcp` reject a foreign `Origin`. See [Token and remote access](../how-to/token-and-remote-access.md).

## Endpoints

"Public" = also served by `sdd public`. Write endpoints answer 403 `read_only` there; `/mcp` answers 404.

| # | Method and path | Public | Returns |
|---|---|---|---|
| 1 | `GET /api/health` | ✓ | `{ok, mode: "daemon"\|"public", synced_at, schema_version, instance, project, public_query: "guarded"\|"presets", base_url}` |
| 2 | `GET /api/status?agent=` | ✓ | as MCP `status` |
| 3 | `GET /api/graph?labels=&focus=&depth=1&limit=300` | ✓ | `{nodes: [{id, label, title, props}], edges: [{source, target, type}]}`. `labels` is comma-separated; `focus` expands around one node |
| 4 | `GET /api/nodes/{id}` | ✓ | one node with all properties and its relationships grouped by type |
| 5 | `GET /api/board?milestone=` | ✓ | tasks in columns `todo`, `claimed`, `done`, with claimer and times. Default milestone: the first not done |
| 6 | `GET /api/milestones` | ✓ | milestones in order with counts and status |
| 7 | `GET /api/sections/{ref}` | ✓ | as MCP `read_section` |
| 8 | `GET /api/tasks/{id}/context?detail=&max_chars=` | ✓ | as MCP `get_context` |
| 9 | `GET /api/impact?target=&depth=` | ✓ | as MCP `impact` |
| 10 | `GET /api/explain?path=` | ✓ | as MCP `explain` |
| 11 | `GET /api/find?feature=&domain=&table=&spec=&text=` | ✓ | as MCP `find_code` |
| 12 | `GET /api/changes?since=&agent=` | ✓ | as MCP `what_changed` |
| 13 | `GET /api/presets` · `GET /api/presets/{name}` | ✓ | the preset list `[{name, params, description}]`; one preset as graph JSON (`name` encoded, e.g. `impact%3Abookings`) |
| 14 | `POST /api/query` | ✓ guarded, or presets only | body `{cypher, params}` → `{columns, rows, truncated}` |
| 15 | `GET /api/mermaid?preset=` | ✓ | `text/plain` Mermaid of one preset (never Cypher) |
| 16 | `GET /api/events` | ✓ | Server-Sent Events ([below](#live-events-sse)) |
| 17 | `POST /api/tasks/{id}/claim` · `/release` · `/complete` | ✗ | as the MCP write tools |
| 18 | `POST /api/deviations` · `POST /api/milestones/{id}/complete` | ✗ | as the MCP write tools |
| 19 | `POST /api/sync` | ✗ | runs a full scan (code, Markdown, git); returns the `sdd sync` JSON |
| 20 | `/mcp` | ✗ | MCP streamable HTTP |
| 21 | `GET /api/next?milestone=&limit=&agent=` | ✓ | as MCP `next_tasks` |

### Write bodies

| Endpoint | JSON body |
|---|---|
| `POST /api/tasks/{id}/claim` | `{"agent"}` |
| `POST /api/tasks/{id}/release` | `{"agent", "reason"?, "force"?}` |
| `POST /api/tasks/{id}/complete` | `{"agent", "notes"?, "files_touched"?: [...], "commit"?}` |
| `POST /api/deviations` | `{"task_id", "agent", "title", "spec_says", "implementation_does", "why", "amends": [...], "consequences"?, "affects"?: [...], "status"?}` |
| `POST /api/milestones/{id}/complete` | `{"agent", "verification"}` |
| `POST /api/sync` | none |

### Examples

```bash
curl http://127.0.0.1:8770/api/health
curl "http://127.0.0.1:8770/api/impact?target=bookings&depth=2"
curl "http://127.0.0.1:8770/api/sections/SPEC-03%20%C2%A72"
curl -X POST http://127.0.0.1:8770/api/query -H 'Content-Type: application/json' \
     -d '{"cypher": "MATCH (m:Milestone) RETURN m.id, m.status ORDER BY m.order"}'
curl -X POST http://127.0.0.1:8770/api/tasks/M05a.1/claim -H 'Content-Type: application/json' \
     -d '{"agent": "me"}'
```

Add `-H "Authorization: Bearer $SDD_TOKEN"` when a token is set.

## Live events (SSE)

`GET /api/events` is a Server-Sent Events stream with a keep-alive comment every 15 s.

| Event | Data |
|---|---|
| `task` | `{id, status, claimed_by, milestone_id}` |
| `deviation` | `{id, title}` (daemon only) |
| `graph_changed` | `{ids: [...], kinds: [...]}` |
| `milestone` | `{id, status}` |

The daemon publishes after each committed write job. The public server compares each re-opened snapshot with the previous one and publishes `task`, `milestone` and `graph_changed`. The dashboard falls back to polling `/api/board` every 5 s if SSE fails, or always when a token is set (browsers can't add headers to an `EventSource`).

```bash
curl -N http://127.0.0.1:8770/api/events
```

## Dashboard deep links

The URL hash keeps the tab and selection, percent-encoded: `#board/M05a`, `#impact/table%3Abookings`, `#explain/src%2Fbooking%2Foverlap.py`, `#graph`, `#query`.
