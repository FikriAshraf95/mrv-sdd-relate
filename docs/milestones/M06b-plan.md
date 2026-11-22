# M06b implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-11 §2–4, §7, §9](../specs/SPEC-11-deployment-and-demo.md#2-compose), [SPEC-09 §4–6](../specs/SPEC-09-security.md#4-public-mode), [SPEC-07 §2–3, §5](../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index), [SPEC-01 §1](../specs/SPEC-01-architecture.md#1-process-model) rule 4, [SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands), [SPEC-10 §4](../specs/SPEC-10-testing-and-benchmark.md#4-invariant-suite). Milestone: [M06b](M06b-public-replay-deploy.md). Previous plan: [M06a-plan](done/M06a-plan.md).
Follow `CLAUDE.md`. D005 is the highest deviation. This plan expects **no new deviation**: every decision below fills a gap the spec leaves open and goes into the owning spec in the same change (§9). If you knowingly depart from a spec anyway, log it (`sdd deviation …`, D006…).

## 0. Scope and boundaries

- **In:** `samples/courtside/replay.toml`; `src/sdd/public.py` + `sdd public`; `src/sdd/demo/` (prepare, replay) + `sdd demo prepare|replay|serve`; runtime image final; root `docker-compose.yml` (judges); `deploy/docker-compose.yml`, `deploy/.env.example`, `deploy/README.md`; tests; spec edits.
- **Not in:** the actual home-server deploy and the phone check (the human does them after the review, from `deploy/README.md`); `sdd bench` (M07); the static site (M08).
- **Layering (SPEC-01 §3):** `public.py` wires parts like `daemon.py` (anything but `relate`). `demo/` may import `service`, `sync`, `ids`, `errors`, `config`, never `graph`. If `demo/` needs a store call, add a small function in `service/` and call that. Only `config.py` reads `os.environ`. All Markdown writes go through `sync/writeback.py`. No new dependencies.
- **Nothing from office-suite-v2.** M06b.5 says "the shape of office-suite-v2's `deploy/`". **Do not open that repo.** SPEC-11 §7 already holds the shape (files, services, env, run book). Build from the spec only.
- **Do not commit.** Leave the work tree for the Opus review; it commits.
- Work through the sdd CLI in the dev container (the daemon is running): `sdd claim M06b.N --agent sonnet-1`, `sdd context M06b.N`, `sdd section "SPEC-11 §4"`, `sdd done M06b.N --agent sonnet-1 --notes … --files …`. Don't edit task boxes by hand.

## 1. Facts verified on relate-db 1.2.0 (2026-11-22, dev container)

- A **commit does not touch `manifest.json`**. It first appears at the first `flush()` (`Store.checkpoint()`), and **every flush rewrites it**, even with no new data (its bytes and mtime change).
- A `read_only=True` connection sees what was committed **when it opened**; it never moves forward. A writer's later commit + flush is invisible until you reopen. That is why `sdd public` reopens (SPEC-01 §1 rule 4).
- Consequences: the replay must call `runtime.store.checkpoint()` after each write job (SPEC-11 §4 step 3), including right after the startup sync. `public` must tolerate a missing `manifest.json` (keep waiting) and a store that briefly fails to open (keep the old one).

## 2. `replay.toml` (M06b.1)

File `samples/courtside/replay.toml`:

```toml
# Sprint replay script for the hosted demo (SPEC-11 §4). Read by `sdd demo prepare|replay`.
[start]
# Milestones whose task boxes all start unticked and whose **Status:** line starts empty.
# Only milestones outside done/ may be listed (prepare fails with invalid_input otherwise).
unticked = ["M05a", "M05b", "M06"]

[run]
# Milestones the simulated agents work, in this order. The loop ends when all are done.
milestones = ["M05a", "M05b", "M06"]
verification = "Replay: every task done by the simulated agents; checks re-run green."

[[task]]          # optional outcome per task; tasks without an entry get generated notes
id = "M05a.1"
notes = "…"
files = ["src/…"]  # real paths in the sample

[[deviation]]     # logged by the worker that holds `task`, just before it completes it
task = "M05a.2"
title = "…"
amends = ["SPEC-05 §2"]
spec_says = "…"
does = "…"
why = "…"
consequences = "…"   # optional
affects = ["src/…"]  # optional
```

- Write 1–2 scripted deviations on the replayed tasks. The text is **invented** and plausible for Courtside (waitlist, reminders, reports). The amended sections must exist in the sample. Give notes and files to roughly half the tasks; use real file paths from `samples/courtside/src/`.
- **Generated notes** for a task without an entry: `"Done per <comma-joined refs of the sections it IMPLEMENTS>."`, or `"Done."` if it has none. Files: none.
- **Keep `replay.toml` out of the bundle.** It is demo tooling, not part of Courtside's history. Add `replay.toml` (root file of the sample only) to the skip rules in `scripts/make_sample.py` (`sample_files`, `check_tip_tree`) and in `tests/spec11/test_sample.py` (`SKIP` / the file walk). This leaves the bundle and the committed stores unchanged. **Do not re-run `make_sample.py`** unless a test proves you must. If you do re-run it, say so in `sdd done`, because the `.bundle` bytes change.
- Parse it in `demo/script.py` with `tomllib` into frozen dataclasses (`ReplayScript`, `TaskOutcome`, `ScriptedDeviation`). Unknown keys, a task ID outside `run.milestones`, or a missing file give `invalid_input` with the key named.

## 3. `sdd demo prepare` (M06b.3) — `demo/prepare.py`

`prepare(sample: Path, data: Path, *, target: str = "run") -> Path` builds `<data>/<target>` and returns it:

1. The bundle is `sample.parent / f"{sample.name}.bundle"` (`samples/courtside.bundle`); `invalid_input` if it is missing.
2. Delete `<data>/<target>` if it exists. Then run `git clone -q <bundle> <data>/<target>` (the git CLI through `subprocess`, `GIT_CONFIG_GLOBAL=os.devnull`, `GIT_CONFIG_NOSYSTEM=1`; the env goes through a helper in `config.py`, which is the only env reader, or is built from `os.environ` there).
3. Apply `[start]`. For each listed milestone, find its file under the clone's milestones globs (not in `done/`). Untick every `- [x]` task line and set the `**Status:**` line to empty. Write through `sync/writeback.py`: add `untick_line` / `untick_all` next to `tick_line`, plus a `clear_status_line` next to `set_status_line`. All writes use `atomic_write` and keep line endings. Unit-test both helpers (CRLF too).
4. Do **not** git-commit the start state (a commit would add a git `COMPLETES`-shaped history; see the memory note on task IDs in commit messages). The working tree is dirty, which is fine.
5. Do **not** open a store. `demo replay` and `demo serve` open one themselves (§4, §5).

CLI: `sdd demo prepare --sample DIR --data DIR` prints the path (`--json`: `{run, unticked: {M05a: 2, …}}`).

## 4. `sdd demo replay` (M06b.3) — `demo/replay.py`

A class you can drive tick by tick, so the tests need no sleeps:

```python
class Replay:
    def __init__(self, settings_for: Callable[[Path], Settings], sample: Path, data: Path,
                 script: ReplayScript, seed: int | None) -> None
    def start(self) -> None          # prepare into <data>/run, open Runtime, full sync, checkpoint, heartbeat
    def tick(self) -> bool           # one tick; False when every run milestone is complete
    def reset(self) -> None          # §4.3
    def run(self, sleep=time.sleep, stop: threading.Event | None = None) -> None   # the loop
    def close(self) -> None
```

### 4.1 One tick (deterministic for a fixed seed; `random.Random(seed)`)
- Agents: `opus-orch` (orchestrator) and workers `sonnet-1`, `sonnet-2`, `sonnet-3`, handled in this order every tick.
- **Busy worker** (holds a task): decrement its countdown. At 0: if `replay.toml` scripts a deviation on that task, call `coordination.log_deviation(...)` first, then `coordination.complete_task(runtime, task, worker, notes=…, files_touched=…)`. The worker is now idle.
- **Idle worker:** `coordination.next_tasks(runtime, milestone=<first run milestone not complete>, limit=10, agent=worker)`. Claim the first task it returns with `claim_task`; if the claim loses (`already_claimed`) or returns nothing, stay idle. Set the countdown to `rng.randint(2, 5)` ticks. Only claim tasks of `run.milestones`.
- **Orchestrator:** for each run milestone in order whose tasks are all done and that is not yet complete, call `coordination.complete_milestone(runtime, m, "opus-orch", script.verification)`. (That moves the file to `done/` and rewrites links, through write-back.)
- After **every** write call: `runtime.store.checkpoint()`. If any call raises `SddError`, log its code (never the text of Markdown) and go on. A failed tick must not kill the loop.
- Return `False` once every run milestone is complete.

### 4.2 Heartbeat
`<data>/run/.sdd/replay.heartbeat`: touch it (create, then `os.utime`) at the end of `start()`, after every tick, and **every 5 s during any pause or sleep** (the 30 s reset pause included), so the 30 s healthcheck never fails while the replay is healthy.

### 4.3 Reset (SPEC-11 §4 step 4), with the store swapped in as late as possible
1. Prepare a fresh copy into `<data>/run.next` (`prepare(..., target="run.next")`). Open a Runtime on it, full sync, checkpoint, touch its heartbeat, close it.
2. Close the live Runtime.
3. Run `os.rename(<data>/run, <data>/run.old)`, then `os.rename(<data>/run.next, <data>/run)`, then `shutil.rmtree(<data>/run.old)`.
4. Open a Runtime on `<data>/run` (settings for that path; the startup sync finds no changes) and checkpoint. Reset the agents' state.

A moved directory store and a moved git clone both keep working. Check that in the reset test. `public` sees one manifest change and reopens. If it tries to open during the gap between the two renames, it fails, keeps the old snapshot and tries again 2 s later.

### 4.4 The loop
`run()`: `start()`; then repeat: `tick()`, then sleep `settings.replay_tick`, with heartbeats. When `tick()` returns False **or** `settings.replay_max_min` minutes have passed since the last (re)start, pause 30 s (with heartbeats), call `reset()` and go on. On SIGTERM/SIGINT, stop cleanly and close the Runtime (it checkpoints). The CLI wires the signal to `stop`.

CLI: `sdd demo replay --sample DIR --data DIR [--seed N]`. The seed comes from `--seed`, else `SDD_REPLAY_SEED`, else none. The replay owns `<data>/run/.sdd/graph`: no daemon, no HTTP server, no watcher (write-back already re-parses the files it edits).

## 5. `sdd demo serve` (M06b.3)

`sdd demo serve --sample DIR --data DIR [--host 127.0.0.1] [--port 8770]`: `prepare(sample, data)`, then `daemon.run(config.load(<data>/run, None), host=…, port=…)`. That is the full daemon (with `/mcp`, so judges can also point Claude Code at it); its startup sync builds the store. Every start re-prepares, so a restart always shows the start state.

## 6. `sdd public` (M06b.2) — `src/sdd/public.py`

`sdd public --store PATH [--project DIR] [--host 127.0.0.1] [--port 8780]`. The project root defaults to `PATH/../..` when `PATH` ends in `.sdd/graph`; otherwise `--project` is required (`invalid_input`). Apply `daemon.check_bind` (inside a container, `SDD_ALLOW_REMOTE=1` is enough).

### 6.1 The runtime
`Runtime(settings, store=Store.open(path, read_only=True), mode="public")`. Add a classmethod `Runtime.open_public(settings)` in `service/runtime.py`, so `public.py` never needs `graph`. `api_views.health` already reports `runtime.mode`.

### 6.2 Following the writer (`service/follow.py`, a thread started by `public.py`)
- Every **2 s** (a constructor argument; tests use 0.05): `stat` `<store>/manifest.json` and compare `(st_ino, st_mtime_ns, st_size)` with the last value seen. If it changed, try `Store.open(path, read_only=True)`. If the open fails, log the code and keep the old store; the next check tries again.
- On success: read the task states `{id: (status, claimed_by, milestone_id)}` and milestone states `{id: status}` from the new store. Swap `runtime.store = new` (one attribute assignment). Close the previous store **10 s later** (`threading.Timer`), so a request still holding it can finish. Set `runtime.synced_at = None`, so health re-reads `Meta`.
- Then publish, comparing the new states with the previous snapshot's: one `task` event `{id, status, claimed_by, milestone_id}` per changed task, one `milestone` event `{id, status}` per changed milestone, and one `graph_changed` `{ids, kinds}` with every changed ID (`runtime.publish_changed`). SPEC-07 §3 says only `graph_changed`; the Board's ticker lists only `task`, `deviation` and `milestone` events, so publish those too and write it into SPEC-07 §3 (§9). Deviation events: optional; skip them.
- Put the queries in `service/` (reuse the board queries in `api_views` where they fit), not in `public.py`.

### 6.3 The app
Make it with `create_app(runtime, public=True)` (new keyword in `web/api.py`; no `mcp_app`):
- **Routes:** a public table, `PUBLIC_PATHS`, derived from SPEC-07 §2 by hand and asserted against the spec by the invariant test (§8). The non-public write routes (endpoints 17–19) stay registered but answer **403 `read_only`** ("This is the read-only public demo."). `/mcp` is **not mounted** (404). Endpoint 21 `/api/next` is public per the table.
- **Middleware:** public mode uses a `PublicMiddleware` instead of `SecurityMiddleware`. It has no Host check, no token and no Origin check, because public serves only public data and has no write route (write that into SPEC-09 §4). In order:
  1. **Rate limit.** A sliding 60 s window per client IP, in memory with a lock: `POST /api/query` 60/min, every other request (static files included) 600/min. Over the limit: **429 `rate_limited`** with `Retry-After: <seconds until the oldest hit leaves the window>` (integer ≥ 1). Prune empty buckets so memory stays bounded.
  2. **Client IP:** the ASGI `client` host. If that address is inside `settings.trusted_proxy_net` (`ipaddress.ip_network`), use `CF-Connecting-IP`, else the first `X-Forwarded-For` entry, else the socket address. Outside the trusted network, never read those headers. Run Uvicorn with `proxy_headers=False`, so it does not rewrite `client` itself.
  3. **Headers on every response:** `Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`.
- **`agent` parameters are ignored** in public mode. Strip `agent` from the query string before the handlers see it, or pass `None`, because some read paths write agent state (for example `what_changed` cursors). Every public endpoint must answer on a read-only store with no 5xx (§8 test).
- **Presets-only:** with `SDD_PUBLIC_QUERY=presets`, `POST /api/query` answers **400 `query_rejected`** ("Only the named presets run on this server."). Presets still run through `/api/presets/{name}`.
- **Errors:** never a stack trace or a path outside the project. Starlette's default 500 with `debug=False` is fine. Assert it in a test (a handler that raises a plain exception, injected through a test-only route, gives a body without "Traceback" or "/").
- **CSP check:** load the dashboard under `default-src 'self'` in a browser and confirm there are no CSP violations: no inline `<script>`, no `style="…"` attributes in `index.html`, and no `setAttribute("style", …)` (CSSOM `el.style.x = …` is allowed). If something breaks, fix the dashboard, not the CSP. The Opus review checks this with Playwright; you check it by grepping the static files.

### 6.4 Serving
Uvicorn on one worker with `proxy_headers=False` and `timeout_graceful_shutdown=2`. Run the follower thread alongside. On SIGTERM: stop the follower and close the store(s). Public writes no `daemon.json`.

## 7. Docker and hosting (M06b.4, M06b.5)

### 7.1 Runtime image (`Dockerfile` stage `runtime`)
Add `PYTHONDONTWRITEBYTECODE=1`, `SDD_WATCH=auto`, and `RUN mkdir -p /data && chown 10001:10001 /data`. A new named volume copies the image's `/data` ownership, so uid 10001 can write it. Keep `USER 10001`, `ENTRYPOINT ["sdd"]` and no image `HEALTHCHECK`. `samples/` is already copied. Check size < 250 MB and uid 10001 (§10).

### 7.2 `docker-compose.yml` (judges, repo root)
```yaml
name: relate-sdd-sample
services:
  sample:
    build: { context: ., target: runtime }
    image: relate-sdd/sdd:local
    command: ["demo", "serve", "--sample", "/app/samples/courtside", "--data", "/data", "--host", "0.0.0.0", "--port", "8770"]
    environment: { SDD_ALLOW_REMOTE: "1", SDD_PROJECT_NAME: courtside }
    ports: ["127.0.0.1:8770:8770"]
    volumes: ["sample-data:/data"]
    restart: unless-stopped
    healthcheck: { test: ["CMD", "python", "-c", "<urllib GET http://127.0.0.1:8770/api/health, timeout 3>"], interval: 10s, timeout: 5s, retries: 5, start_period: 60s }
    read_only: true
    tmpfs: ["/tmp"]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
volumes: { sample-data: {} }
```
(Use the healthcheck snippet written out in full; the image has no curl.) A healthcheck that sends `Host: 127.0.0.1:8770` passes the daemon's loopback Host check.

### 7.3 `deploy/`
- `deploy/docker-compose.yml`: `name: relate-sdd`; services `replay`, `public` and `cloudflared` exactly as in the SPEC-11 §7.2 table. Image `${IMAGE_PREFIX}/sdd:${IMAGE_TAG}`, built from `..` with `target: runtime` (on `replay`; `public` reuses the image). `networks.default.ipam.config: [{subnet: ${COMPOSE_SUBNET}}]`.
  - `replay`: `command: ["demo", "replay", "--sample", "/app/samples/${SAMPLE}", "--data", "/data"]`; env `SDD_REPLAY_TICK`, `SDD_REPLAY_MAX_MIN`, `SDD_REPLAY_SEED`, `TZ`; `demo-data:/data` (rw); healthcheck: heartbeat file exists and is younger than 30 s (a python one-liner; `interval: 10s`, `start_period: 120s`); limits 1 CPU, 768 MB; no ports.
  - `public`: `command: ["public", "--store", "/data/run/.sdd/graph", "--host", "0.0.0.0", "--port", "8780"]`; env `SDD_ALLOW_REMOTE=1`, `SDD_TRUSTED_PROXY_NET=${COMPOSE_SUBNET}`, `SDD_PUBLIC_QUERY`, `SDD_PROJECT_NAME=${SAMPLE}`, `PUBLIC_BASE_URL`, `TZ`; `demo-data:/data:ro`; `ports: ['${PUBLIC_BIND:-127.0.0.1}:${PUBLIC_PORT:-8780}:8780']`; healthcheck on `/api/health`; `depends_on: {replay: {condition: service_healthy}}`; limits 1 CPU, 512 MB.
  - `cloudflared`: as the table (`profiles: [tunnel]`, `command: [tunnel, --no-autoupdate, run]`, `TUNNEL_TOKEN`); no ports; `restart: unless-stopped`.
  - On all three: `restart: unless-stopped`. On `replay` and `public`: `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `deploy.resources.limits` (SPEC-09 §5).
- `PUBLIC_BASE_URL` (SPEC-11 §7.1, "shown in the dashboard footer"): add `public_base_url` to `Settings` (env `PUBLIC_BASE_URL`) and to `/api/health` as `base_url` (`null` when unset). Have the dashboard footer show it if it is set. Update SPEC-07 row 1. Keep this small; if the footer doesn't exist, add one line to `index.html`.
- `deploy/.env.example`: SPEC-11 §7.1's block **verbatim** (placeholders only), with `SAMPLE=courtside` instead of `CHANGE_ME`. That one value is not a secret; update the spec block to match.
- `deploy/README.md`: the run book of SPEC-11 §7.3, steps 1–6, written for a person at the server. Add a "Check it" step: `curl -s http://127.0.0.1:8780/api/health` (mode `public`), `curl -so /dev/null -w '%{http_code}' http://127.0.0.1:8780/mcp` gives 404, and `curl -X POST …/api/sync` gives 403.
- `SDD_PROJECT_NAME` (new, in `config.py`; default: the project folder's name) is what `/api/health` reports as `project`. Without it the header would read `run · public`, the name of the data folder. Document it next to the other `SDD_*` variables (find where SPEC-11 or SPEC-09 lists them) and in SPEC-07 row 1.
- `.dockerignore`: add `deploy/`, `docs/`, `tests/` and `scripts/` only if the build context then still has everything the Dockerfile copies (`pyproject.toml`, `uv.lock`, `README.md`, `src`, `samples`). Keep `samples/**/.sdd` **in** the context; the committed stores are part of the image.

## 8. Tests (M06b.6)

New files: `tests/spec09/test_public.py`, `tests/spec11/test_demo.py`, `tests/invariants/test_inv05_public_routes.py`, plus additions to `tests/invariants/test_inv06_drift.py`. Add a `public_app` fixture to `conftest.py` (SPEC-10 §2): sync a fixture project with a writable Runtime, close it, open `Runtime.open_public`, and wrap `create_app(rt, public=True)` in a `TestClient`.

| Test | Checks |
|---|---|
| `test_spec09_ac07_public_mcp_404_writes_403` | `/mcp` 404; every ✗ endpoint (17, 18, 19) 403 `read_only` |
| `test_spec07_ac01_public_write_endpoints_read_only` | same, driven from the parsed SPEC-07 §2 ✗ rows |
| `test_spec11_ac01_*` | covered by the full suite. Add one test: running `prepare` + replay ticks writes only under the given `data` folder (compare a listing of `tmp_path`'s siblings? simplest: assert every new path is under `data`) |
| `test_spec11_ac02_demo_prepare_and_serve_populate_the_graph` | `prepare(SAMPLE, tmp)` → `Runtime.open` + full sync on `tmp/run` → `/api/health` ok, `/api/board` non-empty, the start-state milestones have 0 done tasks; `daemon.build_app` builds (no socket) |
| `test_spec11_ac03_public_follows_writer_within_2s` | writable Runtime on a store + public Runtime + follower at 0.05 s. Claim a task through `coordination.claim_task` and checkpoint. Within 2 s `/api/board` on the public client shows it claimed, and a `task` event was published (subscribe to `runtime.events`). Health `mode: public`. Also: the follower survives a missing `manifest.json` and a failed open |
| `test_spec11_ac04_replay_loop_resets_to_start_state` | drive `Replay` with seed 42: `start()`, `tick()` until False (bound it: ≤ 200 ticks); every run milestone complete and moved to `done/`, and a scripted deviation file exists. `reset()`: the board of the first run milestone is back to all `todo`, the files are back in `milestones/`, `run.old`/`run.next` are gone, and `tick()` claims again |
| `test_spec11_ac04_replay_is_deterministic` | two fresh replays with the same seed give the same sequence of (tick, agent, action, task) |
| `test_spec11_ac06_runtime_image_contract` | static: parse `Dockerfile` → stage `runtime` has `USER 10001`, `ENTRYPOINT ["sdd"]`, no `HEALTHCHECK`. Parse both Compose files with `yaml` only if PyYAML is already a dependency; otherwise do plain text asserts: every `ports` entry starts with `127.0.0.1:` or `${PUBLIC_BIND`, `name: relate-sdd`, `read_only: true`, `cap_drop`, `tmpfs`. The size check (< 250 MB) is in the walkthrough, not pytest |
| `test_spec10_ac02_*` | read SPEC-10 §7 check 2 and name the test after it. The invariant suite is complete: invariants 1–7 each have a file in `tests/invariants/` |
| `test_inv05_public_routes` | build the daemon app (`daemon.build_app` on a runtime) and the public app. For **every** route path of the daemon app (fill path parameters with `x`), the public app either answers it as public (path in `PUBLIC_PATHS`) or returns 403/404. `/mcp` and `/mcp/` return 404. Built from the route table, so a new route is covered automatically |
| `test_inv06_endpoints_match_spec07` | parse SPEC-07 §2 with our parser. Expand rows like `` `POST /api/tasks/{id}/claim` · `/release` · `/complete` `` and `` `GET /api/presets` · `GET /api/presets/{name}` ``. Compare `(method, path)` with the registered Starlette routes (normalise `{id:path}` → `{id}`; `/mcp` matched by its mount). Also assert the spec's ✓ set equals `PUBLIC_PATHS`. Remove `public` and `demo` from `PENDING_COMMANDS` (only `bench: M07` stays) |
| plain tests | rate limiter: 61st query in a window gives 429 with `Retry-After`. Client IP: with `SDD_TRUSTED_PROXY_NET=10.0.0.0/8`, `CF-Connecting-IP` counts only when the socket address is inside (TestClient's client is `testclient`; build the ASGI scope by hand, or test the IP function directly). Response headers present on `/`, `/api/health` and a 404. Presets mode gives `query_rejected`. Every public GET endpoint (with `agent=x` added) answers without 5xx. writeback `untick_*` / `clear_status_line` keep CRLF. `replay.toml` parse errors. `sdd demo prepare --json` through Typer's `CliRunner` |

Tests use the real sample bundle (`samples/courtside.bundle`), as `tests/spec11/test_sample.py` already does: local files, no network. Copy into `tmp_path`; never write under `samples/`.

## 9. Spec and doc edits (same change)

- **SPEC-07 §2 row 1:** `/api/health` adds `base_url`, and `project` is `SDD_PROJECT_NAME` or the folder name. **§3:** `sdd public` publishes `task` and `milestone` events for each change it detects, plus `graph_changed`.
- **SPEC-09 §4:** public mode has no Host, token or Origin check (read-only, public data only); it ignores `agent` parameters; with `presets`, `POST /api/query` gives `query_rejected`; Uvicorn runs with `proxy_headers=False`.
- **SPEC-11 §4:** the `replay.toml` keys (§2 of this plan), generated notes, the heartbeat every 5 s during pauses, and the reset through `run.next` (§4.3). **§5:** `replay.toml` is the one file of the sample folder that is not in the bundle. **§7.1:** `SAMPLE=courtside`. **§2:** the judges' Compose project name.
- **SPEC-08 §2:** `sdd public` gains `[--project DIR] [--host]`; `sdd demo prepare --json` shape.
- The env variable list (wherever `SDD_TRUSTED_PROXY_NET` is documented): add `SDD_PROJECT_NAME`, `PUBLIC_BASE_URL`.
- `CLAUDE.md`: do **not** touch the Status block (the review does it at close-out).

## 10. Order of work, claims, and gates

1. M06b.1 (`replay.toml`, parser, make_sample/test skip) → M06b.2 (public) → M06b.3 (prepare, replay, serve) → M06b.4 → M06b.5 → M06b.6. Write each task's tests with it; M06b.6 is the leftover and invariant work.
2. Claim each one before starting; `sdd done` with notes and files when its tests pass.
3. Gates before you report: `uv run pytest -q` (the full suite), and `ruff check`, `ruff format --check`, `mypy src/sdd`, `lint-imports`, all green.
4. The dev container has no Docker CLI, so skip `docker build`. Report "Docker files written, not built", and the review builds them.
5. Report: what you built per task, every spec edit, anything you left out or were unsure about, the test count, and the gate output.
