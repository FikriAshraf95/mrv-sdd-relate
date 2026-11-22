# SPEC-10 — Testing and benchmark

> **Status:** v1 (2026-11-21) · **Owner of:** test conventions, fixtures, the invariant suite, gates, the benchmark method

## 1. Conventions

- pytest. Every numbered acceptance check in a spec becomes a test named after it: `test_spec05_ac03_double_claim_one_winner`. One test per check (more if needed, same prefix). Plain names for extra tests.
- Files by spec: `tests/spec03/test_parse_*.py`, `tests/spec05/…`; invariants in `tests/invariants/`.
- This naming also feeds the tool itself: on this repo, `TESTS` relationships link our tests to our own spec checks (dogfooding).
- Assert on error `code`, never on `message` text.
- Never mock Relate or the write queue. Mock only time (`freezegun`-style clock injected through `config`) and, for the benchmark's optional exact count, the HTTP client.

## 2. Test host

- `project` fixture: copies a fixture repo into `tmp_path`, optionally `git init`s it with scripted commits (git CLI, no network).
- `store` fixture: a real Relate directory store in `tmp_path` (`graph.store.Store`), with the [SPEC-02 §6](SPEC-02-graph-schema.md#6-indexes-and-constraints) schema applied; closed (queue drained, checkpointed) after the test.
- `app` fixture: the daemon's Starlette app on a real store, driven through Starlette's `TestClient` (in-process, no sockets). `public_app` does the same in public mode.
- Watcher tests use `SDD_WATCH=poll` with a 0.1 s interval.
- Concurrency tests use real threads against the real write queue.
- `pytest-socket` blocks the network; the in-process client needs none.

## 3. Fixtures

`tests/fixtures/` holds small repos **written to mirror each reference format, with invented content**. Nothing is copied from the reference projects (private-repo-app cannot be made public, open item O1); only their conventions are reproduced:
- `rag_style/`: office-rag conventions (`` ## 2. `documents` `` schema tables, `**Status:**` then text, `docs/deviations/` empty, root and nested CLAUDE.md).
- `suite_style/`: private-repo-app conventions (`**Spec ID:**` headers, `### attachments` tables with `→ users [restrict]`, letter-suffixed milestones, `**Status: DONE (…)**` paragraphs, plan files, nested `> > **DEVIATION:**` notes, legacy task lines without IDs).
- `tool_style/`: this tool's own conventions (task IDs, `(after …)`, Feature lines), plus code files, tests named after checks, and a scripted git history.

## 4. Invariant suite

`tests/invariants/` grows every milestone:
1. `relate` is imported only in `graph/store.py` (also an import-linter contract).
2. **Rebuild equivalence:** `sdd sync --reset` on a synced project reproduces every node and relationship except graph-only state ([SPEC-02 §2](SPEC-02-graph-schema.md#graph-only-state-canonical-list)). The comparison excludes Agent and Event nodes; `CLAIMED`, `ABOUT` and every `src = "tool"` relationship; the graph-only Task properties; `last_synced`, Section `changed_at` and `Meta.last_full_sync`; and the derived `status` of tasks that were claimed and of their milestone.
3. Upserts change the graph-only Task properties (`claimed_by`, `claimed_at`, `completed_by`, `done_at`, `notes`) only in the cases of [SPEC-04 §2.1](SPEC-04-sync.md#21-task-upsert-rules), and never delete a relationship with `src = "tool"` (except the `CLAIMED` relationship that a hand tick clears, SPEC-04 §2.1).
4. Write-back changes exactly the intended lines (diff check) and preserves line endings.
5. Public mode: no route outside the public list answers, and `/mcp` is absent (built from the route table, so new routes are covered automatically).
6. **Doc ↔ code drift:** the MCP tools in [SPEC-05 §2](SPEC-05-agent-tools.md#2-tool-index), the endpoints in [SPEC-07 §2](SPEC-07-dashboard-and-api.md#2-endpoint-index) and the commands in [SPEC-08 §2](SPEC-08-cli-and-exports.md#2-commands) match what the code registers. The test parses our own specs with our own parser.
7. The query guard rejects every write clause in a fixed corpus.

## 5. Benchmark

`sdd bench` measures what the graph saves, deterministically, so judges can reproduce it. Results go to `bench/results/<date>.json` and `.md` (the README table).

### 5.1 Context per task
For every task in the chosen milestones of the sample project:
- **Markdown baseline (the token rule as practised today):** root CLAUDE.md + the whole milestone file + each *Read first* target (whole file when marked, otherwise the referenced sections' line ranges, as `grep -n '^## '` + Read would load them) + `DEVIATIONS.md` + every deviation file amending a read section + the plan file if one exists.
- **Graph, `detail="milestone"`:** the same sections from `get_context`, without the surrounding files.
- **Graph, `detail="task"`:** the default packet.

Reported per task and averaged: characters and estimated tokens (chars ÷ 4). `--exact` uses the Anthropic token-counting API when `ANTHROPIC_API_KEY` is set (never in tests).

### 5.2 Session restart
"What changed since my last session?" after a scripted set of edits (two section edits, one deviation, three completed tasks):
- **Baseline:** re-reading CLAUDE.md, the active milestone, `DEVIATIONS.md` and every Markdown file changed since (by git).
- **Graph:** one `what_changed` result.

### 5.3 Parallel collisions
`sdd bench collisions --agents 10 --tasks 30`:
- **Naive:** 10 threads each tick their own box with read-modify-write of the same milestone file, with small random delays. Count lost ticks.
- **Graph:** the same 10 agents through `claim_task` / `complete_task`. Count double claims and lost ticks (expected: 0 and 0).

### 5.4 Live run (optional, stretch)
Two real Claude Code runs of the same milestone on a copy of the sample, one with the plain workflow and one with the MCP tools, comparing the tokens recorded in the session transcripts. Reported separately and labelled as a single run, not a benchmark.

## 6. Gates

`ruff check`, `ruff format --check`, `mypy --strict src/sdd`, `lint-imports`, `pytest -q` (which includes a smoke test that every dashboard file is served and references no external URL). All run in the dev container ([SPEC-11 §1](SPEC-11-deployment-and-demo.md#1-development-container)) and in GitHub Actions.

## 7. Acceptance checks

1. `pytest -q` passes in the dev container with the network blocked.
2. The invariant suite contains items 1–7 above and passes.
3. `sdd bench context` on the sample project prints the per-task table and writes the JSON and Markdown results.
4. `sdd bench collisions` reports lost ticks > 0 for naive (over 5 runs) and exactly 0 double claims and 0 lost ticks for the graph.
