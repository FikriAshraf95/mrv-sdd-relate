# M02 implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-01 §1, §4–5](../../specs/SPEC-01-architecture.md#1-process-model), [SPEC-04 §1–2, §5.2–5.4](../../specs/SPEC-04-sync.md#1-watcher), [SPEC-07 §1–3](../../specs/SPEC-07-dashboard-and-api.md#1-rules), [SPEC-08 §1](../../specs/SPEC-08-cli-and-exports.md#1-rules), [SPEC-09 §2](../../specs/SPEC-09-security.md#2-local-daemon), [SPEC-10 §1–2](../../specs/SPEC-10-testing-and-benchmark.md#1-conventions). Milestone: [M02](M02-sync-daemon.md). Previous plan: [M01b-plan](M01b-plan.md).
Follow `CLAUDE.md`. D003 is the highest deviation. This plan expects **no deviation**: every decision below fills a place where a spec is silent, and is written into the owning spec in the same change (§10). Any knowing departure you still make → `D004…`, index row, spec note, same change.

## 0. Scope and boundaries

- **In:** `sync/watcher.py`, parse cache + batch sync in `sync/indexer.py`, the tick write-back in `sync/writeback.py`, `service/runtime.py`, `service/events.py`, `service/remote.py`, `service/api_views.py`, `service/tasks.py` (tick only), `web/api.py`, `web/security.py`, `web/sse.py`, `daemon.py`, CLI `daemon`, CLI routing for `status` and `info`, `daemon_running` refusals for `sync` and `ids --write`, tests, the M02.8 measurement.
- **Not in:** MCP (`/mcp` is M03a; leave a comment where it mounts), claims and `complete_task` (M03a wraps the tick), git poller (M04a: leave a `# M04a: git sync` hook in startup), code walker and `.gitignore` rules (M04a), dashboard static files (M05a), public mode (M06b), endpoints other than 1–4, 6, 19.
- **Import rules (import-linter enforces them):** `web/` imports only `service`, `ids`, `errors`, `config`, plus Starlette/sse-starlette. `cli` never imports `graph`/`sync`. `daemon.py` may import everything except `relate`. `service/` may import `graph`, `sync`, `parse`. Nobody imports `daemon`/`public` except `cli`.
- **No new dependencies.** HTTP client = stdlib `urllib.request`. Tests use Starlette's `TestClient` (already available through the installed httpx package). No sockets in tests (pytest-socket stays on).
- **Probed facts you can rely on:** `type(r)` works (`schema.counts`). Variable-length paths are **not** probed; don't use them (graph focus is a Python BFS, §5.3).

## 1. Watcher — `sync/watcher.py` (M02.1)

```python
@dataclass(frozen=True, slots=True)
class Batch:
    paths: frozenset[str]          # project-relative POSIX paths created, modified or deleted
    sdd_files: Mapping[str, str]   # current {path: kind} of SDD documents (after this batch)

class Watcher:
    def __init__(self, settings: Settings, on_batch: Callable[[Batch], None], *,
                 debounce: float = 0.3) -> None
    mode: str                      # resolved: "poll" or "native"
    def start(self) -> None        # initial snapshot (no batch for it), then threads
    def stop(self) -> None         # stops threads, flushes nothing, joins
    def poll_once(self, *, code: bool) -> set[str]   # one poll, returns changed paths; tests + M02.8
    def sdd_files(self) -> dict[str, str]
```

- **Mode:** `settings.watch`; `auto` → `poll` when `settings.in_container`, else `native`.
- **Ignore rule** (one function, `indexer.ignored_dir(name)`, shared with `discover`): any path segment starting with `.` (covers `.sdd/`, `.git/`), `node_modules`, `__pycache__`. Move `_PRUNED_DIRS` logic from `discover` into it. M04a replaces/extends it with the walker's `.gitignore` rules; leave a `# M04a:` comment.
- **Classification:** add public `indexer.classify(settings, rel) -> str | None` (wrapping `_classify` with cached `PathSpec`s; build specs once per Settings, e.g. a small class `Classifier(settings)` held by the watcher).
- **Poll mode — two snapshots of `{path: (st_mtime_ns, st_size)}`:**
  - *SDD poll* every `settings.poll_interval`: `os.stat` every known SDD file, plus `os.scandir` of the **glob base directories** (the literal prefix of each glob in `settings.paths` for the SDD kinds: specs, milestones, plans, deviations, deviation_index, docs) to find new `.md` files. A base followed by `**` is walked recursively; others are listed one level. A glob whose base is the project root (e.g. `**/CLAUDE.md`) only lists the root folder here; nested matches are found by the code poll. **Write this rule into SPEC-04 §1** (spec is silent).
  - *Code poll* every `settings.poll_code_interval`: `os.walk` the whole root (pruned by the ignore rule), stat every file. Any new file that classifies as SDD joins the SDD set.
  - Diff old vs new snapshot → created/modified/deleted paths → debouncer. Stat errors (file vanished mid-poll) count as deleted.
  - One thread runs both schedules (sleep to the next due time; `threading.Event` for stop).
- **Native mode:** `watchdog.observers.Observer`, one recursive watch on the root; the handler maps `src_path`/`dest_path` to relative POSIX, drops ignored paths, updates the SDD set (classify on create/move, drop on delete/move), feeds the debouncer.
- **Debouncer:** collects paths; when 300 ms pass with no new path, hands one `Batch` to `on_batch` on **one dedicated batch thread** (batches never overlap). An exception in `on_batch` is logged (path count only, no file text) and the watcher keeps running.
- Non-SDD paths are delivered in the batch too; until M04a the runtime ignores them.

### M02.8 measurement (after M02.1)
`scripts/measure_poll.py` (commit it): generates 20 000 small files in `/workspace/_pollbench/` (a non-dot folder **inside the bind mount**, ~200 folders × 100 files), builds `Settings` with that folder as `project_root`, and times `poll_once(code=True)` 5 times (report min/median) and `poll_once(code=False)` on this repo. Delete `_pollbench/` at the end (and add `/_pollbench/` to `.gitignore`). Rule for the defaults: `SDD_POLL_CODE_INTERVAL ≥ 10 × median code poll`, rounded up to a whole second, minimum 10 s; `SDD_POLL_INTERVAL` stays 1 s unless the SDD poll of this repo takes over 50 ms. Update `config.py` defaults if they change, and **record the numbers (date, file count, min/median, chosen defaults) in SPEC-04 §1**, replacing the "M02 (task M02.8) measures…" sentence.

## 2. Indexer changes — `sync/indexer.py`

1. **Parse cache:** `class ParseCache` = `dict[str, tuple[str, str, ParseResult]]` (path → hash, kind, pristine result). `analyse(settings, *, cache=None, files=None)`:
   - `files` given → use it instead of `discover()` (the watcher's SDD set); else `discover()`.
   - For each file: read bytes, hash; cache hit on `(path, hash, kind)` → reuse the result, else parse and store. **Always work on a shallow copy** (`dataclasses.replace(result)`), because `_drop_duplicates` reassigns `nodes`/`rels`; never mutate the cached object's lists. Drop cache entries for paths no longer present.
   - This is how "otherwise only changed files are re-parsed" (SPEC-04 §2 step 3) holds; resolution still runs over all files (cheap).
2. **`sync(store, settings, *, full: bool = True, files=None, cache=None) -> SyncReport`**: today's `full_sync` body with the new arguments; `last_full_sync` is written only when `full`. Keep `full_sync = sync` with `full=True` as an alias for existing callers/tests. The Meta job still runs on every call (schema_version, project_name) but with `last_full_sync=None` when not full. **No `checkpoint()` when nothing changed** (changed, removed and phase-2 all empty) — avoids a flush per no-op batch; still checkpoint when full.
3. `SyncReport` gains `changed_ids: list[str]` = created + updated + deleted node IDs + `file:<path>` for every changed and removed path, de-duplicated, sorted. `kinds` for SSE are derived in the runtime with `ids.label_of` (skip IDs it rejects).
4. No locking in the indexer; the runtime serializes (§4).

## 3. Write-back tick — `sync/writeback.py` (M02.6)

Pure part:
```python
def tick_line(path: str, text: str, task_id: str) -> tuple[str, bool]
```
Parse `text` with `parse_milestone` (re-locate **by ID in the fresh text**, never a cached line), find the Task node with `id == task_id`, take its `source_line`, check the line matches `^\s*[-*] \[[ xX]\] ` and contains `**<task_id>**`. Missing → `SddError("source_changed", …, details={"task": task_id, "path": path})`. Already `[x]`/`[X]` → `(text, False)`. Else replace only the `[ ]` of that line → `(new_text, True)`. Nothing else on the line changes.

Job part (runs **inside one write job**, order of SPEC-04 §5.2):
```python
def tick_task(tx: Tx, settings: Settings, task_id: str, *, now: str,
              agent: str | None = None) -> TickResult   # TickResult(task_id, path, changed_file: bool, milestone_id, status)
```
1. **Check:** `MATCH (t:Task {id:$id}) RETURN t.source_path, t.milestone_id` → none: `task_not_found`. Resolve `settings.project_root / source_path` with `Path.resolve()` and require it inside the resolved root (SPEC-09 §2 rule 5) → else `invalid_input`. Read bytes; keep CRLF knowledge to `atomic_write` (it already preserves endings); work on `\n` text. `tick_line(...)` (raises `source_changed` before any change).
2. **Graph (uncommitted):** `SET t.checked = true, t.status = 'done', t.done_at = coalesce(t.done_at, $now)`; `completed_by = $agent` when given; remove `claimed_by`/`claimed_at` and the task's `CLAIMED` relationships. Recompute the milestone status the way phase 1 does (`in_progress` unless parsed `done`) — or simply let step 4's upsert do it (it does: re-parse runs `upsert_file_nodes`, which derives milestone status). Prefer the latter; keep step 2 to the task.
3. **Markdown** (only when `settings.writeback` and the line changed): `atomic_write(path, new_text)`.
4. **Re-parse (loop prevention, SPEC-04 §5.4):** read the written bytes, hash with `indexer.file_hash`, `parse_milestone`, then `upsert.upsert_file_nodes(tx, FileIn(path, hash), nodes, keep_ids={ids produced by this file}, now=now, initial=False, writeback=settings.writeback)` and `SET f.content_hash = $hash` on `file:<path>`. Because step 2 already set `checked = true`, the upsert sees no false→true transition: **no `task_completed` Event with actor `human`, no second claim clearing**. Relationships are unchanged by a tick, so phase 2 is skipped.
   - `writeback` import note: `sync/writeback.py` may import `graph` and `parse` (sync layer). Put `file_hash` where both indexer and writeback can use it without a cycle (`writeback` importing `indexer` is fine; `indexer` must not import `writeback`).
5. Return; the store commits.
- **Idempotent:** a retry finds `[x]` → no file write; the graph `SET`s repeat harmlessly.
- `writeback = false`: steps 1 (graph check only — still `task_not_found`; skip the file check? **No**: still re-locate, so a removed line is still `source_changed`), 2, no 3, no 4.
- Don't touch `add_task_ids`/`atomic_write` behaviour.

Service wrapper `service/tasks.py`:
```python
def tick_task(runtime: Runtime, task_id: str, *, agent: str | None = None) -> dict[str, Any]
```
Normalise the ID (`ids.normalise`, `InvalidIdError` → `invalid_input`), take `runtime.sync_lock`, `runtime.store.write(lambda tx: writeback.tick_task(tx, settings, id, now=settings.now_iso(), agent=agent))`, then publish SSE `task` `{id, status, claimed_by: None, milestone_id}` and `graph_changed` `{ids: [task, milestone, file:<path>], kinds}`. Returns `{task, path, changed_file, status}`. No HTTP route and no CLI in M02 (M03a's `complete_task` wraps it).

## 4. Runtime and events — `service/runtime.py`, `service/events.py`

```python
class EventBus:                                   # service/events.py, thread-safe
    def publish(self, type_: str, data: Mapping[str, Any]) -> None   # any thread
    def subscribe(self, loop: asyncio.AbstractEventLoop, *, maxsize: int = 1000) -> Subscription
class Subscription:                               # wraps an asyncio.Queue fed with loop.call_soon_threadsafe
    async def get(self) -> tuple[str, dict[str, Any]]
    def close(self) -> None
```
A full queue drops that subscriber (close it; the SSE stream ends and the browser reconnects). `publish` never blocks.

```python
@dataclass
class Runtime:                                    # service/runtime.py
    settings: Settings
    store: Store
    events: EventBus
    mode: str = "daemon"
    instance: str = <secrets.token_hex(8)>
    started_at: str
    sync_lock: threading.Lock
    cache: ParseCache
    last_report: SyncReport | None
    synced_at: str | None

    @classmethod
    def open(cls, settings) -> Runtime     # Store.open(writable) + schema.ensure; daemon_running passes through
    def sync(self, *, full: bool = True, files: Mapping[str, str] | None = None) -> dict[str, Any]
    def on_batch(self, batch: Batch) -> None   # watcher callback
    def close(self) -> None                # store.close() (drains queue, flushes)
```
- `sync()` holds `sync_lock`, runs `indexer.sync(store, settings, full=…, files=…, cache=self.cache)`, stores `last_report`/`synced_at`, and when `changed_ids` is non-empty publishes **one** `graph_changed` `{ids, kinds}` (kinds = sorted distinct labels). Returns the same dict shape as `service.indexing.sync` (factor a shared `report_dict(report, counts)` in `indexing.py`).
- `on_batch`: if no path in `batch.paths` is an SDD path (in `batch.sdd_files`) or a removed former SDD path (present in the graph's File set — simplest: in `last_report`-tracked set or just in the previous `sdd_files`), return. Else `self.sync(full=False, files=batch.sdd_files)`. Catch and log exceptions (code + path count; never file text).
- `service.indexing.sync(settings)` (the CLI path) first calls `remote.ensure_no_daemon(settings)` (§7), then behaves as today.

## 5. HTTP API — `web/api.py`, `web/security.py`, `service/api_views.py` (M02.3)

### 5.1 App
`create_app(runtime: Runtime) -> Starlette` with routes (sync `def` handlers → Starlette runs them in its threadpool; SSE handler async):

| # | Route | Service call |
|---|---|---|
| 1 | `GET /api/health` | `api_views.health(runtime)` → `{ok: true, mode, synced_at, schema_version, instance, project}` (`project` = `settings.project_root.name`) |
| 2 | `GET /api/status` | `api_views.status(runtime)` — refactor `service/status.py` so `_read(store, settings, warnings)` becomes public `read_status(...)`; the daemon passes `runtime.last_report.warnings` (no re-parse per request) |
| 3 | `GET /api/graph?labels=&focus=&depth=1&limit=300` | `api_views.graph(runtime, labels, focus, depth, limit)` |
| 4 | `GET /api/nodes/{id:path}` | `api_views.node(runtime, id)` |
| 6 | `GET /api/milestones` | `api_views.milestones(runtime)` |
| 16 | `GET /api/events` | `web/sse.py` (§6) |
| 19 | `POST /api/sync` | `runtime.sync(full=True)` |

- Handlers validate query params (ints, ranges) → `SddError("invalid_input")`, call one service function, return `JSONResponse`.
- **Error mapping** (one dict `HTTP_STATUS: dict[str, int]` + an exception handler for `SddError` returning `err.to_dict()`): 400 `invalid_input`, `query_rejected`, `ambiguous_target`; 401 `unauthorized`; 403 `read_only`, `forbidden_origin`, `forbidden_host`, `writeback_disabled`; 404 every `*_not_found`, `unknown_section`; 409 `already_claimed`, `task_done`, `task_blocked`, `not_claimed_by_you`, `milestone_incomplete`, `source_changed`, **`daemon_running`** (spec addition, §10); 429 `rate_limited` (+ `Retry-After: 1`); 503 `write_conflict`, `query_timeout`. A test asserts `set(HTTP_STATUS) == errors.CODES`.
- Unknown `/api/...` path → 404 in the error shape with `node_not_found`? **No** — plain Starlette 404 is fine for unknown routes.
- IDs in paths: Starlette already gives the percent-decoded path; `{id:path}` keeps `/`. `SPEC-02%232` → `SPEC-02#2`, `file%3Asrc%2Fsdd%2Fcli.py` → `file:src/sdd/cli.py`. Test both.
- Leave `# M03a: mount /mcp here (streamable_http_app)` in `create_app`.

### 5.2 Security middleware (`web/security.py`, pure ASGI middleware, applies to `/api` and `/mcp`; order Host → token → Origin)
1. **Host** (SPEC-09 §2 rule 3): parse the `Host` header (handle `[::1]:8770`, missing port, missing header → reject). Allowed: `localhost`, `127.0.0.1`, `::1`, plus `settings.allowed_hosts` (exact host match, case-insensitive). Else 403 `forbidden_host`.
2. **Token** (rule 2): if `settings.token`: `Authorization: Bearer <t>` compared with `hmac.compare_digest`; else 401 `unauthorized`. Health too. Never log the header.
3. **Origin** (rule 4): for any method other than GET/HEAD/OPTIONS on `/api/*`, and for every `/mcp` request: an `Origin` header present and `!= f"http://{host_header}"` → 403 `forbidden_origin`. No `Origin` → allowed.
Responses use the error shape (`SddError(...).to_dict()`, JSON).

### 5.3 `service/api_views.py`
- `graph(...)`: `labels` = comma list, each must be in `schema.LABELS` (else `invalid_input`); default = all labels except `Event`, `Meta`, `Agent`. `limit` 1–2000 (default 300), `depth` 1–3 (default 1).
  - No `focus`: `MATCH (n:<L>) RETURN properties(n) AS p, labels(n) AS l` per label up to `limit` total (stable order by id), then edges among the returned IDs: `MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS source, b.id AS target, type(r) AS type`.
  - `focus`: node must exist (`node_not_found`). BFS `depth` hops in Python: per hop, `MATCH (a)-[r]-(b) WHERE a.id IN $frontier RETURN a.id, b.id, type(r), startNode(r).id …` — **probe `startNode`**; if unsupported, run two directed queries (`(a)-[r]->(b)` and `(b)-[r]->(a)`). Respect the `labels` filter for added nodes, stop at `limit`. Edges only between returned nodes; edge `{source, target, type}` with the true direction.
  - Node shape `{id, label, title, props}`; `label` = first label; `title` = `props.title` or `props.name` or `id`. Drop nothing else from `props`.
- `node(runtime, id)`: `{id, label, props, relationships: {TYPE: [{direction: "out"|"in", id, label, title, props}]}}`, grouped by type, each list sorted by `(direction, id)`. Missing → `node_not_found` with `details={"id": id}`.
- `milestones(runtime)`: from `read_status`: `[{id, title, status, order, done, claimed, total}]` in order.
- `health(runtime)`: `synced_at = runtime.synced_at` (end of last sync) else `Meta.last_full_sync`.
- All reads go through `runtime.store.read` (worker-thread reads). No Cypher in `web/`.

## 6. SSE — `web/sse.py` (M02.4)
`async def events(request)`: `sub = runtime.events.subscribe(asyncio.get_running_loop())`; return `EventSourceResponse(gen(), ping=15)` where `gen` yields `{"event": type, "data": json.dumps(data)}` until disconnect; `finally: sub.close()`. Factor the generator as `event_stream(sub)` so a test can drive it with asyncio directly (no streaming client needed). Event types used in M02: `graph_changed`, `task`.

## 7. Daemon and detection — `daemon.py`, `service/remote.py` (M02.2, M02.5)

### 7.1 `service/remote.py`
```python
@dataclass(frozen=True) class DaemonInfo: port: int; instance: str; pid: int; started_at: str; auth_ok: bool
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, Any]]  # method, url, headers, body → (status, json)
TRANSPORT: Transport = _urllib_transport          # tests monkeypatch this module attribute
def daemon_file(settings) -> Path                 # <root>/.sdd/daemon.json
def detect(settings) -> DaemonInfo | None
def ensure_no_daemon(settings) -> None            # raises daemon_running
class DaemonClient: get(path, params=None) -> Any; post(path, body=None) -> Any   # error shape → SddError
```
- `detect`: no file / unreadable JSON → `None`. `GET http://127.0.0.1:<port>/api/health` (timeout 1 s, bearer token if `settings.token`). 200 and `body.instance == file.instance` → `DaemonInfo(auth_ok=True)`. 401 → `DaemonInfo(auth_ok=False)` (something answers with auth; treat as running). Connection error, timeout, other status, other instance → `None` (stale file; **never delete it here**). Never trust the pid alone.
- `ensure_no_daemon`: `detect` → `daemon_running` ("A daemon runs for this project on port N; use its API or stop it"). Then, if the store directory exists and is not `:memory:`, the writer lock is the authority: the CLI's own `Store.open` writable already raises `daemon_running` after retries — no extra probe needed for `sync`. For `ids --write` (which never opens the store), open the store writable once and close it (`daemon_running` passes through) when `store.exists(path)`.
- The `_urllib_transport` sends `Host: 127.0.0.1:<port>` (urllib does by default) and no `Origin`.

### 7.2 `daemon.py`
```python
def check_bind(host: str, settings: Settings) -> None   # SPEC-09 §2 rule 1 → invalid_input
def run(settings: Settings, *, host: str = "127.0.0.1", port: int = 8770) -> None
```
Lifecycle (SPEC-01 §5):
1. `check_bind`. Loopback = `127.0.0.1`, `localhost`, `::1`. Otherwise require `settings.allow_remote` and (`settings.token` or `settings.in_container`).
2. `remote.ensure_no_daemon`-style check via `detect` → `daemon_running`. `settings.in_memory` → `invalid_input` (a daemon needs a store on disk).
3. `Runtime.open(settings)` (writer lock → `daemon_running`).
4. `runtime.sync(full=True)` (startup scan; `# M04a: git sync`).
5. `Watcher(settings, runtime.on_batch).start()`.
6. Uvicorn: `uvicorn.Config(create_app(runtime), host, port, workers=1, log_level="info", timeout_graceful_shutdown=2)`; subclass `uvicorn.Server` and override `startup` to write `daemon.json` **after** the socket is bound (`await super().startup(...)`, then write if `self.started`). `daemon.json` = `{pid, host, port, instance, started_at, token_sha256 (or null), project}`, written with tmp + `os.replace` (it is not Markdown, so not through writeback).
7. `finally` (uvicorn handles SIGINT/SIGTERM): `watcher.stop()`, `runtime.close()` (drains queue, flushes), remove `daemon.json` **only if its `instance` is ours**.
Also expose `prepare(settings, host) -> Runtime` (steps 1–4) so tests can build the daemon without uvicorn.

### 7.3 CLI (M02.5)
- `sdd daemon [--host 127.0.0.1] [--port 8770]` → `daemon.run(settings, host=…, port=…)`; `SddError` → `fail()` (exit 4 for `daemon_running`, 2 for `invalid_input`).
- **Routing rule:** route through the daemon only when `--store` is the project default (not `:memory:`, not an explicit other path) and `remote.detect` finds one. `auth_ok=False` → `unauthorized` error telling the user to set `SDD_TOKEN`.
  - `status` → `GET /api/status` (same JSON as the local path; printing unchanged).
  - `info` → local counts still from the read-only store (works next to a writer), but `daemon` field = `{port, pid, started_at}` and the text line shows `daemon  running on :8770`.
  - `doctor` never routes (Markdown only).
  - `sync` and `ids --write` → `daemon_running` (through `ensure_no_daemon` in the service functions; exit 4).
- Without a daemon: unchanged (read-only open for `status`, which creates no file — tested).

## 8. Tests (M02.7) — names per SPEC-10 §1

Fixtures (`tests/conftest.py`): `runtime` (copies `tool_style` into `tmp_path`, `Runtime.open` on a store in `tmp_path`, startup sync, closed after), `app` (`TestClient(create_app(runtime))`, default `Host: testserver` is **not loopback** → set `base_url="http://localhost:8770"` so the Host check passes), `fake_daemon` (monkeypatches `remote.TRANSPORT` to route `http://127.0.0.1:<port>/…` into a `TestClient` of a running runtime, and writes `daemon.json`). Settings in tests: `config.load(project, store, env={...})` with `SDD_WATCH=poll`, `SDD_POLL_INTERVAL=0.1`, `SDD_POLL_CODE_INTERVAL=0.1`.

| File | Tests |
|---|---|
| `tests/spec01/test_daemon.py` | `test_spec01_ac01_second_daemon_refuses` (`daemon.prepare` with a `fake_daemon` answering → `daemon_running`; first runtime still answers health and its store still writes; plus: no daemon.json but the store held by the first runtime → `daemon_running` from the lock). `test_spec01_ac02_sync_refuses_status_routes` (CliRunner: `sdd sync` exit 4 / code `daemon_running`; `sdd --json status` answers and the transport saw `/api/status`). `test_spec01_ac03_status_without_daemon_read_only` (after a CLI sync, `sdd status` with no daemon; the store dir's file list and mtimes are unchanged). Plain: stale daemon.json (transport raises connection error) is ignored; other `instance` is ignored; daemon.json removed on `run` shutdown only if ours (unit-test the cleanup helper). **Note:** SPEC-01 checks 2–3 name `sdd impact`, which arrives in M04b; M02 tests them with `sdd status` and M04b extends them (§10). |
| `tests/spec04/test_watcher.py` | poll mode: create/modify/delete detected; ignored dirs (`.sdd/`, `.git/`, `node_modules/`) never reported; debounce merges a burst into one batch; a new nested `CLAUDE.md` is found by the code poll only; `test_spec04_ac01_host_edit_updates_section_within_3s` (runtime + watcher at 0.1 s, rewrite one section's text on disk, wait ≤ 3 s for that Section's `text` and `changed_at`; every other Section's `changed_at` unchanged; a `graph_changed` was published listing it). |
| `tests/spec04/test_writeback_tick.py` | `test_spec04_ac06_tick_one_line_crlf_no_resync` (CRLF milestone file; `tasks.tick_task` → exactly one line differs (`[ ]`→`[x]`), all endings still CRLF, final newline kept; `runtime.sync(full=False)` afterwards reports `changed == []` and creates no Event). Plain: tick twice is idempotent; removed line → `source_changed` and graph unchanged; unknown task → `task_not_found`; `writeback=false` leaves the file untouched and the task `done`; `tick_line` unit tests (code fence lookalike untouched, `[X]` counts as done). |
| `tests/spec04/test_parse_cache.py` | second batch with one changed file re-parses only that file (monkeypatch-count the parser via the `_PARSERS` table — counting, not mocking Relate); cached results are not mutated by duplicate dropping. |
| `tests/spec07/test_api.py` | `test_spec07_ac02_write_publishes_sse` (API part: subscribe to the bus, `POST /api/sync` after editing a file → `graph_changed`; and `event_stream` yields a formatted SSE item). `test_spec07_ac03_graph_focus_depth1` (`/api/graph?focus=SPEC-01%231&depth=1` on tool_style: the section and exactly its direct neighbours). Plain: health shape; `/api/nodes/<encoded section id>` and an encoded `file:` id; unknown node → 404 `node_not_found`; bad `depth` → 400; milestones order; status matches the service; `set(HTTP_STATUS) == errors.CODES`. |
| `tests/spec09/test_local_security.py` | `test_spec09_ac01_bind_rule` (`check_bind` with/without allow_remote, token, in_container). `test_spec09_ac02_token` (401 without, 200 with). `test_spec09_ac03_foreign_origin_rejected` (on `POST /api/sync` — the claim endpoint arrives in M03a, which extends this test). `test_spec09_ac08_host_check` (`Host: evil.example` → 403 `forbidden_host`; `Host: localhost:8770` + `Origin: http://localhost:8770` → `POST /api/sync` 200). |

Gates: `ruff check`, `ruff format --check`, `mypy src/sdd` (strict), `lint-imports`, full `pytest -q`. Keep existing tests green (`full_sync` alias).

## 9. Walkthrough (acceptance 2) — run it, report the output
In the container: `uv run sdd daemon --host 0.0.0.0` on this repo (compose sets `SDD_ALLOW_REMOTE=1`, `SDD_WATCH=poll`). From Windows `curl http://localhost:8770/api/health`; edit a line in SPEC-04 §1 (then revert it), check `curl http://localhost:8770/api/nodes/SPEC-04%231` within 3 s and that `curl -N http://localhost:8770/api/events` printed `graph_changed`; `sdd status` in a second `exec` shell answers through the daemon; Ctrl+C removes `.sdd/daemon.json`. The builder can't edit in VS Code; simulate the host edit from Windows (Git Bash/PowerShell on the host writing the file, which goes through the bind mount the same way). **Leave SPEC-04 exactly as it was** (or with only the M02.8 numbers).

## 10. Spec and doc changes in the same change
- **SPEC-04 §1:** the glob-base polling rule (§1 above); the M02.8 measurement result and defaults.
- **SPEC-07 §1 rule 2:** add `daemon_running` to the 409 list. **§2 row 1:** health returns `{ok, mode, synced_at, schema_version, instance, project}`, with one sentence: `instance` is a random ID per daemon start, also in `daemon.json`, so the CLI knows the answer comes from this project's daemon (SPEC-01 §5 step 1).
- **SPEC-01 §1 rule 3 / §5:** `daemon.json` fields: add `instance` and `host` to the listed fields.
- **M02 milestone M02.7 line:** "SPEC-07 §5 checks 3 and 7" → "checks 2 (API part: a committed write publishes on `/api/events`) and 3" (SPEC-07 §5 has no check 7).
- **M04b:** add task **M04b.8** "Extend `test_spec01_ac02`/`ac03` to `sdd impact` (M02 tested them with `sdd status`). (after M04b.5)". **M03a:** append to M03a.6: "; extend `test_spec09_ac03` to `POST /api/tasks/M01.1/claim`".
- **SPEC-08 §2:** no change (`sdd daemon` row exists). SPEC-05: none.
- `.gitignore`: `/_pollbench/`.
- If you change anything else in behaviour vs a spec → deviation D004.

## 11. Report back
Files changed; gate output (pass counts); the M02.8 numbers and chosen defaults; walkthrough transcript (curl outputs, timing); every place you decided something not in this plan; any deviation logged. Do **not** tick milestone boxes, set Status, move files, or commit — the Opus review does that.
