# SPEC-07 — Dashboard and HTTP API

> **Status:** v1 (2026-11-21) · **Owner of:** every HTTP endpoint, SSE events, the dashboard views
> Served by the daemon (private, all endpoints) and by `sdd public` (read-only subset, [SPEC-09 §4](SPEC-09-security.md#4-public-mode))

## 1. Rules

1. Starlette routes in `web/api.py` validate, call one `service/` function, and return its JSON. Same results as the MCP tools.
2. Errors use the one shape ([SPEC-00 §6.4](SPEC-00-overview.md#64-errors)) with the codes of [SPEC-05 §8](SPEC-05-agent-tools.md#8-error-codes) and these HTTP statuses: 400 (`invalid_input`, `query_rejected`, `ambiguous_target`), 401 (`unauthorized`), 403 (`read_only`, `forbidden_origin`, `forbidden_host`, `writeback_disabled`), 404 (`*_not_found`, `unknown_section`), 409 (`already_claimed`, `task_done`, `task_blocked`, `not_claimed_by_you`, `milestone_incomplete`, `source_changed`, `daemon_running`), 429 (`rate_limited`, with `Retry-After`), 503 (`write_conflict`, `query_timeout`). A code without a status here is a bug.
3. **IDs and references in URLs are percent-encoded** (`encodeURIComponent`), because they contain `#`, `/`, `:`, spaces and `§`: `GET /api/nodes/SPEC-02%232`, `GET /api/nodes/file%3Asrc%2Fsdd%2Fcli.py`, `GET /api/sections/SPEC-03%20%C2%A74.2`. Path parameters that hold an ID use Starlette's `{id:path}` converter. The dashboard's URL hash encodes the same way (`#impact/table%3Aattachments`).
4. Read endpoints that mirror an MCP tool accept that tool's optional `agent` as a query parameter; write endpoints take `agent` in the JSON body (SPEC-05 §1 rule 2).
5. The dashboard is plain static HTML + ES modules + vendored Cytoscape.js. **No build step, no framework.** The same files run in the daemon, in `sdd public`, and on GitHub Pages ([SPEC-11 §6](SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)) through a data adapter (`api.js`: HTTP, or the in-browser WASM store). The adapter adds the bearer header when the daemon has a token ([SPEC-09 §2](SPEC-09-security.md#2-local-daemon) rule 2).

## 2. Endpoint index

| # | Method + path | Public | Returns |
|---|---|---|---|
| 1 | `GET /api/health` | ✓ | `{ok, mode: "daemon"\|"public", synced_at, schema_version, instance, project}`. `instance` is a random ID per daemon start, also in `daemon.json`, so the CLI knows the answer comes from this project's daemon ([SPEC-01 §5](SPEC-01-architecture.md#5-daemon-lifecycle) step 1) |
| 2 | `GET /api/status?agent=` | ✓ | as MCP `status` |
| 3 | `GET /api/graph?labels=&focus=&depth=1&limit=300` | ✓ | `{nodes: [{id, label, title, props}], edges: [{source, target, type}]}`; `focus` expands around one node |
| 4 | `GET /api/nodes/{id}` | ✓ | one node with all properties and its relationships grouped by type |
| 5 | `GET /api/board?milestone=` | ✓ | tasks in columns `todo`, `claimed`, `done`, with claimer and times; default milestone = first not done |
| 6 | `GET /api/milestones` | ✓ | milestones in order with counts and status |
| 7 | `GET /api/sections/{ref}` | ✓ | as MCP `read_section` |
| 8 | `GET /api/tasks/{id}/context` | ✓ | as MCP `get_context` |
| 9 | `GET /api/impact?target=&depth=` | ✓ | [SPEC-06 §2](SPEC-06-code-context.md#2-impact) |
| 10 | `GET /api/explain?path=` | ✓ | [SPEC-06 §3](SPEC-06-code-context.md#3-explain) |
| 11 | `GET /api/find?feature=&domain=&table=&spec=&text=` | ✓ | [SPEC-06 §4](SPEC-06-code-context.md#4-find_code) |
| 12 | `GET /api/changes?since=&agent=` | ✓ | as MCP `what_changed` |
| 13 | `GET /api/presets` · `GET /api/presets/{name}` | ✓ | preset list `[{name, params, description}]` ([SPEC-06 §5](SPEC-06-code-context.md#5-presets)); one preset as graph JSON `{nodes, edges}` (`name` percent-encoded, e.g. `impact%3Adocuments`) |
| 14 | `POST /api/query` `{cypher, params}` | ✓ (guarded, may be preset-only) | `{columns, rows, truncated}` |
| 15 | `GET /api/mermaid?preset=` | ✓ | `text/plain` Mermaid ([SPEC-08 §3](SPEC-08-cli-and-exports.md#3-exports-and-snapshots)) |
| 16 | `GET /api/events` | ✓ | SSE stream ([§3](#3-live-events)) |
| 17 | `POST /api/tasks/{id}/claim` · `/release` · `/complete` | ✗ | as the MCP write tools (used by the CLI and replay) |
| 18 | `POST /api/deviations` · `POST /api/milestones/{id}/complete` | ✗ | as the MCP write tools |
| 19 | `POST /api/sync` | ✗ | trigger a full scan (code, Markdown, git); the result is the `sdd sync` JSON, with `code` and `git` objects (`git` is `null` when skipped) |
| 20 | `/mcp` | ✗ | MCP streamable HTTP ([SPEC-05](SPEC-05-agent-tools.md)) |
| 21 | `GET /api/next?milestone=&limit=&agent=` | ✓ | as MCP `next_tasks` (used by `sdd next` when a daemon runs) |

## 3. Live events

`GET /api/events` (SSE, keep-alive comment every 15 s). Event types: `task` (`{id, status, claimed_by, milestone_id}`), `deviation` (`{id, title}`), `graph_changed` (`{ids: [...], kinds: [...]}`), `milestone` (`{id, status}`). The daemon publishes after each committed write job. `sdd public` publishes `graph_changed` after each snapshot reopen, with the changed task statuses compared to the previous snapshot. The browser falls back to polling `/api/board` every 5 s if SSE fails.

## 4. Dashboard views

One page, five tabs; the URL hash keeps the tab and selection (`#impact/table%3Aattachments`, encoded per [§1](#1-rules) rule 3) so README links can deep-link.

1. **Board** (default): milestone picker; columns *To do · In progress · Done*; cards show ID, title, group, and the claiming agent as a coloured chip. Cards move live with a short highlight. Header: counts and the last few events as a ticker. **This is the demo video's main shot.**
2. **Graph:** Cytoscape view with a label filter (checkboxes, colour per label), search box (ID or title), click to show properties in a side panel, double-click to expand neighbours, *Reset*. Opens on the `schema` preset or on a milestone.
3. **Impact:** a target box with autocomplete (tables, sections, files, features). Shows the result as grouped lists **and** as a graph where the target is centred and the `via` chains are drawn; clicking an item shows its chain.
4. **Explain:** a file picker (searchable tree). Shows the summary paragraph and the chain feature → spec → tasks/commits → deviations as a left-to-right layered graph.
5. **Query:** a Cypher box with example queries (the presets as Cypher), a results table, and *Show as graph* when the result has nodes. In public mode with `SDD_PUBLIC_QUERY=presets`, the box is read-only and only presets run.

Look: system font stack, light and dark themes via `prefers-color-scheme` and a toggle, colour tokens as CSS custom properties, one accent colour per label, sentence case, no emoji. Layout works from 360 px wide (tabs collapse into a select).

## 5. Acceptance checks

1. Every endpoint marked ✗ returns 403 `read_only` in public mode, and `/mcp` returns 404 there.
2. Claiming a task through MCP moves its card on an open Board within 2 s (SSE).
3. `GET /api/graph?focus=SPEC-02%232&depth=1` (the ID `SPEC-02#2`, encoded) returns the section and its direct neighbours only.
4. The Impact view for a table renders every group returned by `/api/impact` and highlights a chain on click.
5. With SSE blocked, the Board still updates by polling.
6. The dashboard loads with no network requests outside its own origin.
7. `GET /api/nodes/{id}` answers for a Section ID (`#`) and a File ID (`/`) given percent-encoded, and a deep link `#impact/<encoded section id>` opens that target.
