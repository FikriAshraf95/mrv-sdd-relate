# M02 — Sync daemon

> **Depends on:** [M01b](M01b-graph-sync.md) · **Blocks:** [M03a](../M03a-coordination-tools.md)
> **Read first:** [SPEC-01 §1, §4–5](../../specs/SPEC-01-architecture.md#1-process-model) · [SPEC-04 §1–2, §5.2–5.4](../../specs/SPEC-04-sync.md#1-watcher) · [SPEC-07 §1–3](../../specs/SPEC-07-dashboard-and-api.md#1-rules) · [SPEC-08 §1](../../specs/SPEC-08-cli-and-exports.md#1-rules) · [SPEC-09 §2](../../specs/SPEC-09-security.md#2-local-daemon)
> **Model:** Opusplan. Process ownership, polling through the Windows bind mount, safe atomic write-back and loop prevention. Write `M02-plan.md` first.

## Goal
`sdd daemon` runs in the dev container, owns the store, picks up edits made in VS Code on Windows within 3 s, serves the first API endpoints and an SSE stream, and can safely edit Markdown without triggering itself. The CLI routes through the daemon when it runs.

## Tasks
### Daemon
- [x] **M02.1** `sync/watcher.py`: `poll` / `native` / `auto`, debounce, batches into the indexer, the two poll intervals ([SPEC-04 §1](../../specs/SPEC-04-sync.md#1-watcher)).
- [x] **M02.8** Measure one poll of a generated 20 000-file tree through the Windows bind mount; set the `SDD_POLL_INTERVAL` / `SDD_POLL_CODE_INTERVAL` defaults from the result and record it in SPEC-04 §1. (after M02.1)
- [x] **M02.3** `web/api.py`: endpoints 1–4, 6 and 19, the error mapping, percent-encoded IDs in paths, the token, the Host and Origin checks, the bind rule ([SPEC-07 §2](../../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index), [SPEC-09 §2](../../specs/SPEC-09-security.md#2-local-daemon)).
- [x] **M02.2** `daemon.py`: lifecycle (health-call and writer-lock detection, not the pid alone), startup full scan, `daemon.json`, refusal when one runs, clean shutdown with checkpoint ([SPEC-01 §5](../../specs/SPEC-01-architecture.md#5-daemon-lifecycle)). (after M02.1, M02.3)
- [x] **M02.4** `service/events.py` + `web/sse.py`: in-process event bus and `/api/events` with `graph_changed` ([SPEC-07 §3](../../specs/SPEC-07-dashboard-and-api.md#3-live-events)). (after M02.2)
- [x] **M02.5** CLI routing: detect the daemon, call its API; read-only snapshot fallback without a daemon; `sync` and `ids --write` refuse with `daemon_running` ([SPEC-01 §1](../../specs/SPEC-01-architecture.md#1-process-model) rule 3, [SPEC-08 §1](../../specs/SPEC-08-cli-and-exports.md#1-rules) rule 4). (after M02.2)
### Write-back
- [x] **M02.6** `sync/writeback.py`: atomic writes, line endings, re-locate by ID, `source_changed`, the order inside a job, idempotent edits, loop prevention through the stored hash; first edit: tick a task box (used by M03a) ([SPEC-04 §5.2–5.4](../../specs/SPEC-04-sync.md#52-safety)).
### Tests
- [x] **M02.7** [SPEC-01 §7](../../specs/SPEC-01-architecture.md#7-acceptance-checks) checks 1–3; [SPEC-04 §7](../../specs/SPEC-04-sync.md#7-acceptance-checks) checks 1 and 6 (tick through the service function); [SPEC-07 §5](../../specs/SPEC-07-dashboard-and-api.md#5-acceptance-checks) checks 2 (API part: a committed write publishes on `/api/events`) and 3; [SPEC-09 §6](../../specs/SPEC-09-security.md#6-acceptance-checks) checks 1–3 and 8.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** in the dev container, `uv run sdd daemon --host 0.0.0.0` on this repo → from Windows, `curl http://localhost:8770/api/health` is ok → edit a section of SPEC-04 in VS Code → within 3 s `GET /api/nodes/SPEC-04%231` shows the new text and `/api/events` emitted `graph_changed` → `sdd status` in a second `exec` shell answers through the daemon → stopping the daemon removes `daemon.json`.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-22). Verified: full gates green (374 tests; ruff, mypy strict, import-linter 13/13); walkthrough run in the dev container: health from the Windows host, a host edit of SPEC-04 §1 visible at `/api/nodes/SPEC-04%231` after ~1 s with `graph_changed` on `/api/events`, `sdd status`/`info` answered through the daemon, `sdd sync` and a second daemon refused with `daemon_running`, `daemon.json` removed on stop. M02.8: 20 000-file code poll 30 s median through the bind mount, so the code poll backs off to 10x its duration (SPEC-04 §1). Opus review of the Sonnet build: fixed a broken SPEC-07 table row and replaced the fixed 301 s code-poll default with the back-off. Deviations: none.
