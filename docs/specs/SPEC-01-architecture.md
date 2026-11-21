# SPEC-01 — Architecture

> **Status:** v1 (2026-11-21) · **Owner of:** repo layout, process model, module boundaries, the Relate access layer, concurrency, dependencies
> **Read with:** [SPEC-00 §6](SPEC-00-overview.md#6-global-conventions)

## 1. Process model

```
docs/specs/*.md, docs/milestones/*.md, docs/deviations/*.md, code, .git   ← humans and agents edit
        │  watcher (polling in Docker) → hash → re-parse changed files only
        ▼
  sdd daemon   ONE process · sole writer of .sdd/graph/ · 127.0.0.1:8770
     ├─ /mcp     MCP streamable HTTP  ← Claude Code: orchestrator + N subagents
     ├─ /api     JSON API + /api/events (SSE)
     └─ /        dashboard (static)
        │  checkpoint
        ▼
  sdd public   separate process · read_only snapshot, reopened on change · no /mcp · :8780
```

Rules:
1. **One writable connection per store, in one process: the daemon.** Relate is a single-process engine. A second writer gets `storage locked` (verified).
2. MCP uses **HTTP on localhost, never stdio**. stdio would start one server per Claude Code session, and they would fight over the store.
3. The CLI never opens the store for writing while the daemon runs. It detects the daemon through `.sdd/daemon.json` (pid, port, token hash, started_at) **plus a health call**; the file alone proves nothing, because PIDs are reused (especially inside containers) and a killed daemon leaves the file behind. The authority for "a writer exists" is Relate's own writer lock (`storage locked`). Read commands then call the API. Without a daemon, read commands open a read-only snapshot, and write commands (`sync`, `ids --write`) open the store themselves.
4. `sdd public` opens `read_only=True` and reopens when the store's `manifest.json` changes (checked every 2 s). This is how the hosted demo follows the replay writer, because Python has no live WAL follow.

## 2. Repo layout

```
src/sdd/
  config.py           Settings from env + .sdd/config.toml (the only reader of os.environ)
  ids.py              ID formats and normalisation (SPEC-02 §1)
  errors.py           SddError(code, message, retryable, details)
  parse/              pure parsers (SPEC-03): links.py, specs.py, milestones.py, deviations.py,
                      docs.py, schema_tables.py, features.py
  graph/              store.py (the ONLY relate import, write queue), schema.py (labels, indexes),
                      upsert.py (parsed objects → Cypher), queries.py (loads named read queries),
                      queries/*.cypher (every named read query; shared with the static demo, SPEC-11 §6)
  sync/               watcher.py, indexer.py (file → parser → upsert), files.py (code walker),
                      git.py, writeback.py (the ONLY Markdown writer)
  service/            coordination.py (next/claim/complete/deviation), context.py, changes.py,
                      impact.py (impact/explain/find), query_guard.py, events.py
  mcp/server.py       MCP tools → service
  web/api.py          Starlette routes → service; sse.py; static/ (dashboard, vendored JS)
  cli.py              `sdd` (Typer) → service or daemon API
  daemon.py           wires store + watcher + MCP + web; public.py (read-only server)
  demo/replay.py      simulated agents (SPEC-11 §4)
tests/                pytest; fixtures/ (small repos in both reference formats)
samples/              the demo project (SPEC-11 §5)
docs/                 this project's own SDD docs
Dockerfile · docker-compose.yml · pyproject.toml · .mcp.json
```

## 3. Module boundaries

| Module | May import | Never |
|---|---|---|
| `ids`, `errors` | stdlib only | any other `sdd` module |
| `config` | stdlib, `errors` | any other `sdd` module |
| `parse/` | stdlib, `markdown-it-py`, `ids`, `errors` | `config`, `graph`, `sync`, `service`, any I/O |
| `graph/` | `relate`, `ids`, `errors`, `config` | `parse`, `sync`, `service`, `mcp`, `web` |
| `sync/` | `parse`, `graph`, `ids`, `errors`, `config` | `service`, `mcp`, `web` |
| `service/` | `graph`, `sync`, `parse`, `ids`, `errors`, `config` | `mcp`, `web`, `cli`, `relate` |
| `mcp/`, `web/` | `service`, `ids`, `errors`, `config` | `graph`, `relate`, `sync` |
| `demo/` | `service`, `sync`, `ids`, `errors`, `config` | `graph`, `relate`, `mcp`, `web` |
| `daemon.py`, `public.py` | everything except `relate` (they wire the parts) | being imported by anything except `cli` |
| `cli` | `service`, `daemon`, `public`, `demo`, `ids`, `errors`, `config` | `graph`, `relate`, `sync` |

Enforced by `import-linter` contracts in CI. `relate` appears only in `graph/store.py`.

## 4. Relate access and concurrency

- `store.py` owns one `relate.Connection` per process. It exposes `read(cypher, params)`, `write(fn)` and `checkpoint()`.
- **Write queue:** every write is a function run by one dedicated writer thread, in order. Each job runs inside `autocommit = False` … `commit()`, with `rollback()` on any error (verified: Cypher `BEGIN` is not supported; the connection methods are). A job that touches several nodes (claim, complete, re-sync of one file) is **one transaction**.
- On `write-write conflict` or `storage locked`, the job retries 3 times with 50 / 200 / 800 ms backoff, then fails with `write_conflict` (retryable). With one writer thread these should be rare; the retry exists for the open race and for engine-internal conflicts. **A job must be idempotent**, because a retry runs it again from the start (including its write-back, [SPEC-04 §5.2](SPEC-04-sync.md#52-safety)).
- **Reads:** until open item O5 is resolved, reads take the same lock as writes, so access is serialized. Lock-free reads on the shared connection are allowed **only if O5 shows both** that concurrent reads are thread-safe **and** that a read never sees another job's uncommitted writes (the connection is in `autocommit = False` during a job). Otherwise reads stay serialized, or move to a separate read-only snapshot connection if O12 allows one.
- **Guarded queries** ([SPEC-09 §3](SPEC-09-security.md#3-query-guard)) never hold the shared lock while they run: they use a `read_only=True` snapshot connection opened by `store.py` (refreshed after each checkpoint) if O12 allows it. Otherwise they run under the lock and the variable-length bound and 5 s limit keep the stall short.
- `checkpoint()` calls `flush()`. It runs after each sync batch and before `sdd snapshot`, so the public process and committed stores see complete data.
- Storage mode: **directory store** at `<repo>/.sdd/graph/` (durability `full`). The live store is **never committed** (gitignored): a store a daemon writes to would keep the tree dirty, conflict on every merge and change under `git checkout`. Committed copies for judges are made by `sdd snapshot` ([SPEC-08 §3](SPEC-08-cli-and-exports.md#3-exports-and-snapshots), [DEC-001](../decisions/DEC-001-committed-store.md)).
- One store per project. No cross-store queries (Relate has none). The global lessons store is a stretch goal and holds copies only.

## 5. Daemon lifecycle

1. Load config. If `.sdd/daemon.json` exists and its port answers `/api/health` for this project, refuse to start (`daemon_running`). A file whose daemon does not answer is stale and is ignored.
2. Open the store writable. `storage locked` means another process writes it: exit with `daemon_running`. Then create indexes ([SPEC-02 §6](SPEC-02-graph-schema.md#6-indexes-and-constraints)).
3. **Startup sync:** full scan comparing content hashes, then git sync ([SPEC-04 §2](SPEC-04-sync.md#2-incremental-sync)).
4. Start the watcher, the git poller and the HTTP server (Uvicorn, one worker; MCP mounted with `MCPServer.streamable_http_app()` from `mcp` 2.x).
5. Write `.sdd/daemon.json`. On SIGTERM: stop the watcher, drain the write queue, checkpoint, close, remove `daemon.json`.

## 6. Dependencies

Runtime: `relate-db` (≥ 1.2), `mcp` (≥ 2.3, 2.x API), `starlette`, `uvicorn`, `sse-starlette`, `markdown-it-py`, `watchdog`, `pathspec`, `typer`, `pydantic` (v2, for tool and API schemas). Dev: `pytest`, `pytest-socket`, `ruff`, `mypy`, `import-linter`. Git is called as the `git` CLI (no GitPython). Dashboard: vendored `cytoscape.min.js` (no CDN at runtime, so the hosted demo has no third-party calls).

Licences must be permissive (MIT, Apache-2.0, BSD). Relate is Apache-2.0.

## 7. Acceptance checks

1. A second `sdd daemon` on the same project exits with `daemon_running` and leaves the first untouched.
2. With the daemon running, `sdd sync` refuses with `daemon_running`, and `sdd impact X` answers through the daemon API.
3. Without a daemon, `sdd impact X` answers from a read-only snapshot and creates no lock file.
4. A write job that raises midway leaves no partial nodes (rollback), and the next job succeeds.
5. 50 concurrent `claim_task` calls on different tasks all succeed, in queue order, with no `write_conflict` surfaced.
6. `import-linter` passes: `relate` is imported only in `graph/store.py`.
