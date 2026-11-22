# SPEC-00 — Overview

> **Status:** v1 (2026-11-21) · **Owner of:** concepts, glossary, global conventions, success criteria, schedule, open items
> **Read with:** [IDEA](../IDEA.md) · [HANDOFF](../../HANDOFF.md) (verified Relate facts)

## 1. What we build

A Python tool, `sdd`, that turns a spec-driven repo into a live Relate graph that agents query instead of re-reading Markdown.

Pipeline: **Markdown + code + git → parse (changed files only) → one Relate directory store → MCP tools for agents, JSON API + dashboard for people → write-back of task status and deviations to Markdown**.

Parts (one Python package, [SPEC-01](SPEC-01-architecture.md)):
- `daemon`: the **only** process that opens the store for writing. Watches files, syncs, serves MCP (`/mcp`), the JSON API (`/api`) and the dashboard (`/`) on `127.0.0.1:8770`.
- `public`: a separate, read-only process for the hosted demo. Opens a read-only snapshot of the store. No MCP, no writes.
- `cli`: `sdd …` for humans and CI. Talks to the daemon when it runs; otherwise reads a snapshot directly.
- `web`: a plain static dashboard (HTML + JS + Cytoscape.js), served by both `daemon` and `public`.

## 2. Concepts

- **Project**: one repo with SDD docs. One project = one store at `<repo>/.sdd/graph/`.
- **Spec**: a `SPEC-NN-*.md` file. **Section**: one heading inside it, with its own text, so an agent can load §5.2 alone.
- **Acceptance check**: a numbered item in a spec's *Acceptance checks* section. Tests are named after it (`test_spec03_ac06_…`, `Spec06_Ac02…`).
- **Milestone**: an `M<nn>[a-z]-*.md` file. **Task**: one checkbox line in it, with a stable ID such as `M02.3` ([SPEC-03 §4](SPEC-03-markdown-parsing.md#4-milestones-and-tasks)).
- **Deviation**: a `D<nnn>-*.md` file plus its index row and spec notes.
- **Claim**: an agent's exclusive hold on a task. Claims live only in the graph.
- **Context packet**: what `get_context(task)` returns: the task, its milestone, the sections to read with the deviations that amend them, upstream outcomes and related code ([SPEC-05 §4](SPEC-05-agent-tools.md#4-get_context)).
- **Feature / Domain**: author-declared groupings that tie specs to files and tables ([SPEC-03 §3.3](SPEC-03-markdown-parsing.md#33-feature-line)).
- **Write-back**: the daemon editing Markdown on an agent's behalf (tick a box, write a deviation).
- **Graph-only state**: claims, agents and events, including what events record (completion notes, files touched, `AFFECTS`). Everything else can be rebuilt from Markdown, code and git.

## 3. Glossary

| Term | Meaning |
|---|---|
| Relate | Embedded property-graph database by Neo4j (`pip install relate-db`, `import relate`), Cypher queries, single-process store |
| Directory store | Relate's default storage: WAL + shards in a directory. Needed for snapshots and `relate clone` |
| `.rl` | Relate's single-file store, made with `relate clone` |
| MCP | Model Context Protocol. Claude Code reaches the daemon over streamable HTTP |
| Read-only snapshot | `relate.connect(path, read_only=True)`: loads once, refuses writes, sees new data only after reopen (verified 2026-11-21) |
| Sample project | The demo repo under `samples/` with specs, milestones, deviations, code and a committed store ([SPEC-11 §5](SPEC-11-deployment-and-demo.md#5-sample-project)) |
| Replay | Simulated agents working the sample project in a loop, for the live demo |
| Reference projects | `D:\Works\ai\office-rag` and `D:\Works\ai\office-suite-v2`: real SDD repos whose format we parse. **Read-only** |

## 4. Non-goals

See [IDEA](../IDEA.md#non-goals-for-this-build). Also: no Windows-native service install, no authentication beyond a loopback bind plus an optional token, no editing of spec text through tools.

## 5. Spec map

| Spec | Owns |
|---|---|
| [SPEC-01](SPEC-01-architecture.md) | Package layout, process model, module boundaries, the Relate access layer, concurrency |
| [SPEC-02](SPEC-02-graph-schema.md) | **Every** node label, property and relationship type, IDs, and the label → milestone map |
| [SPEC-03](SPEC-03-markdown-parsing.md) | What is parsed from specs, milestones, deviations, docs; link and ID rules; schema tables |
| [SPEC-04](SPEC-04-sync.md) | Watcher, incremental sync, deletes, code walker, git sync, write-back, loop prevention |
| [SPEC-05](SPEC-05-agent-tools.md) | **Every** MCP tool, claim rules, the context packet, Claude Code integration |
| [SPEC-06](SPEC-06-code-context.md) | `impact`, `explain`, `find_code`: definitions, traversals, output |
| [SPEC-07](SPEC-07-dashboard-and-api.md) | **Every** HTTP endpoint, SSE events, dashboard views |
| [SPEC-08](SPEC-08-cli-and-exports.md) | **Every** CLI command, Mermaid / Cypher / snapshot exports, the CLAUDE.md status block |
| [SPEC-09](SPEC-09-security.md) | Binding, tokens, the query guard, public mode, limits |
| [SPEC-10](SPEC-10-testing-and-benchmark.md) | Test conventions, invariants, the benchmark |
| [SPEC-11](SPEC-11-deployment-and-demo.md) | Docker, Compose, home hosting, replay, static demo, sample project, submission |

## 6. Global conventions

These apply everywhere. A rule here beats any other spec, and a conflict is a deviation ([DEVIATIONS](../DEVIATIONS.md)).

### 6.1 Source of truth
1. Specs are the source of truth. Code that disagrees with a spec is either a bug or a logged deviation.
2. **SPEC-02 owns every label and relationship type.** A new one is a SPEC-02 change in the same change as the code.
3. **SPEC-05 indexes every MCP tool, SPEC-07 every HTTP endpoint, SPEC-08 every CLI command.**
4. Milestones are worked in number order, one at a time; a milestone's *Read first* line lists the sections to load.
5. **Markdown is the product's source of truth too.** The graph holds nothing that cannot be rebuilt from Markdown, code and git, except graph-only state ([§2](#2-concepts)).

### 6.2 Names and formats
- Python 3.13, package `sdd` in `src/sdd/`, distribution name `relate-sdd`, CLI `sdd`.
- Node IDs are human-readable strings, never generated UUIDs: `SPEC-03`, `SPEC-03#5.2`, `M02`, `M02.3`, `D012`, `file:src/sdd/cli.py` ([SPEC-02 §1](SPEC-02-graph-schema.md#1-ids-and-common-properties)). The one exception is Event IDs (`event:<ulid>`): events are graph-only and have no natural key.
- Timestamps are UTC ISO 8601 strings with `Z` in the graph and JSON. The dashboard shows them in the browser's zone.
- JSON fields are `snake_case` everywhere (API, MCP, exports). Enumerations are lowercase strings (`todo`, `claimed`, `done`).
- Paths in the graph are POSIX, relative to the project root.

### 6.3 Layering
- **Only `sdd/graph/store.py` imports `relate`.** Everything else uses its functions.
- **All graph writes go through the write queue** in `sdd/graph/store.py` ([SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)).
- **All Markdown writes go through `sdd/sync/writeback.py`.**
- MCP tools, HTTP routes and CLI commands only validate input, call one function in `sdd/service/`, and map the result. **No Cypher outside `sdd/graph/` and `sdd/service/`.**
- Parsers are pure: text in, parsed objects out. No I/O, no graph access.

### 6.4 Errors
- One error shape for MCP, HTTP and CLI `--json`: `{"error": {"code", "message", "retryable", "details"}}`. Codes are stable `snake_case` ([SPEC-05 §8](SPEC-05-agent-tools.md#8-error-codes)).
- Messages say what happened and what to do next ("Task M02.3 is claimed by sonnet-2 since 10:42. Pick another from next_tasks.").

### 6.5 Security
- The daemon binds to loopback only. MCP and every write path are never reachable from the public process ([SPEC-09](SPEC-09-security.md)).
- Arbitrary Cypher runs only through the query guard, in a transaction that is always rolled back.

### 6.6 Tests
- Every numbered acceptance check in a spec becomes a test named after it: `test_spec05_ac03_double_claim_one_winner` ([SPEC-10 §1](SPEC-10-testing-and-benchmark.md#1-conventions)).
- Tests never touch the network or the reference projects. They use fixture repos under `tests/fixtures/`.
- Full gates: `ruff check`, `ruff format --check`, `mypy`, `pytest`.

### 6.7 Development environment
- All building, testing and running happens **in Docker** (`docker compose exec dev …`). Nothing is installed on the Windows host ([SPEC-11 §1](SPEC-11-deployment-and-demo.md#1-development-container)).
- File watching defaults to **polling** inside containers, because inotify does not see Windows-host edits through a bind mount (verified 2026-11-21).

## 7. Success criteria

1. `docker compose up` on a clean machine starts the daemon on the sample project, and the dashboard shows its graph within 60 s of the images being built.
2. The parser indexes both reference formats (fixtures that mirror office-rag and office-suite-v2 with invented content) with zero unparsed task lines and zero unresolved spec links that resolve on GitHub.
3. Ten parallel simulated agents claiming tasks produce **zero** double claims and zero lost checkbox updates.
4. On the sample project, the average `get_context` packet is **at least 70 % smaller** than the Markdown an agent reads by the token rule for the same task ([SPEC-10 §5](SPEC-10-testing-and-benchmark.md#5-benchmark)).
5. `impact("attachments")` (or the sample's equivalent table) returns specs, sections, features, files, tasks and deviations, each with the path that connects it.
6. The repo ships committed stores (a checkpointed snapshot directory + `.rl`, made by `sdd snapshot`; the live `.sdd/graph/` is never committed, [DEC-001](../decisions/DEC-001-committed-store.md)), Mermaid diagrams in the README, a live demo link and a static demo link.
7. This repo's own docs index cleanly with its own tool (dogfooding), from M03b on.

> **DEVIATION:** see [D007](../deviations/D007-sample-s-graph-packet-is-61-smaller-than-the-markdown-rule.md) — Sample's graph packet is 61% smaller than the Markdown rule, not 70%

## 8. Schedule and open items

**Schedule** (deadline **Thu 2026-12-11, 18:00 PST** = Fri 12 Dec, 10:00 MYT; the user also has the office-rag presentation on Thu 26 Nov):

| Days | Target |
|---|---|
| Fri 21 – Sat 22 Nov | Specs, milestones, CLAUDE.md; review; M00a Docker and skeleton, M00b Relate access layer |
| Sun 23 | M01a parsers |
| Mon 24 | M01b graph sync |
| Tue 25 – Wed 26 | M02 sync daemon (lighter on 26 Nov) |
| Thu 27 | M03a coordination tools |
| Fri 28 | M03b context, query guard, Claude Code integration |
| Sat 29 – Sun 30 | M04a code and git layer (M05a dashboard core can run in a parallel session) |
| Mon 1 Dec | M04b schema, features, impact |
| Tue 2 – Wed 3 | M05a dashboard core (if not done in parallel), M05b Impact and Explain |
| Thu 4 | M06a invented sample and exports |
| Fri 5 – Sat 6 | M06b public mode, replay, home deploy |
| Sun 7 | M07 benchmark |
| Mon 8 | M08 static demo (cut first if late) |
| Tue 9 – Thu 11 | M99 README, video, submission. **Submit by Thu 11, 23:59 MYT** to leave margin |

**Open items**

| # | Item | Owner | Status |
|---|---|---|---|
| O1 | Can office-suite-v2 content be published in this public repo as the sample? | User | **Closed (2026-11-21): no.** Nothing from office-suite-v2 is ever published; the sample is invented ([DEC-004](../decisions/DEC-004-sample-fallback.md), [SPEC-11 §5](SPEC-11-deployment-and-demo.md#5-sample-project)) |
| O2 | Relate WASM package name and how fast it loads an exported graph (Cypher script vs JSON) | M08 | Open |
| O3 | Are JSON-codec snapshots and `.rl` clones possible from Python, or only from the `relate` CLI? | M06a | **Closed (2026-11-22): only from the CLI.** The `relate-db` 1.2.0 Python package has no clone or codec API (`Connection` has `execute`, `commit`, `rollback`, `flush`, `close`, …). The `relate` CLI (in the dev image, not the runtime image) does all three: `relate clone SRC DEST.rl` (single file), `relate clone --to-snapshot-format json SRC DEST` (directory with a readable `graph.json`) and `relate clone SRC DEST` (directory copy). A clone reads what was committed when it opened and works beside a running writer; its output holds `.cypherlite.writer` files (dropped) and keeps the `.cypherlite.lock` markers ([D001](../deviations/D001-store-copies-keep-lock-markers.md)); `relate.connect(…, read_only=True)` opens all three. **`graph/store.py`:** the only module that runs the CLI (`clone`, `copy_store` as the fallback without it); `sdd snapshot` ([SPEC-08 §3](SPEC-08-cli-and-exports.md#3-exports-and-snapshots)) |
| O4 | Does `relate-db` support a per-query timeout or row cap from Python? | M03b | **Closed (2026-11-22): no.** `relate-db` 1.2.0 has neither: `connect()` and `execute()` take no timeout, and `execute()` builds the whole result before `fetchmany()` returns (a single value over the engine's expression-memory limit fails with `DataError`). **`service/query_guard.py`:** the fallback of [SPEC-09 §3](SPEC-09-security.md#3-query-guard) step 3: the query runs on a worker thread that holds a per-process gate until it really ends; the caller gets `query_timeout` after 5 s; the row cap is applied by fetching at most 101 rows |
| O5 | Is one `Connection` safe for concurrent reads from several threads, and does a read on it during an open write transaction see uncommitted data? | M00b | **Closed (2026-11-21): no, connections are thread-affine.** `relate-db` 1.2.0 declares DB-API `threadsafety = 1`; a call from any thread other than the opening one raises `ProgrammingError` (`WrongThread`). A read on the connection inside an open transaction does see that transaction's own uncommitted writes. **`store.py`:** its worker thread opens the connection and runs every job, reads included, one at a time in submission order, each in its own transaction, so a read never sees another job's writes ([SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)) |
| O6 | Does Relate Cypher support uniqueness constraints, property indexes and full-text indexes? | M00b | **Closed (2026-11-21): yes, all three.** Neo4j 5 syntax with `IF NOT EXISTS` (idempotent), created inside a transaction and rolled back with it. A duplicate raises `IntegrityError` (`ConstraintVerificationFailed`), also within one statement. Full-text is queried with `CALL db.index.fulltext.queryNodes(name, text)` (the `SEARCH … FULLTEXT` clause does not parse). `SHOW CONSTRAINTS` / `SHOW INDEXES`, `db.labels()` work. **`graph/schema.py`:** a unique `id` on every label, the five property indexes and both full-text indexes ([SPEC-02 §6](SPEC-02-graph-schema.md#6-indexes-and-constraints)) |
| O7 | Can browser.neo4j.io (HTTPS) connect to a local `relate serve --bolt`? | M99 (bonus) | Open |
| O8 | Can Relate's `fs-to-graph` / `git-to-graph` extensions write into a store our daemon owns? | M04a | **Closed (2026-11-22): no, keep our walker and git reader.** `relate` 1.2.0 has `relate extension install\|list` and `relate run <name> -d PATH`; `run` says "the child walks its source and emits rows over the wire; the host alone owns the store". No extension is installed, and installing one fetches from the network. So an extension can only write into a store the `relate` host opens itself, which the daemon's writer lock prevents ([SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)). **`sync/files.py`, `sync/git.py`:** the walker and the git reader ([SPEC-04 §4, §6](SPEC-04-sync.md#4-code-walker)) |
| O9 | Relate CLI install in the Docker image (install script, amd64 + arm64) | M00a | **Closed (2026-11-21).** The `relate-db` 1.2.0 wheel ships no CLI binary. The `dev` stage runs the official `https://relatedb.ai/install.sh` with `HOME=/opt/relate` and links `/opt/relate/.local/bin/relate` to `/usr/local/bin/relate`. The script picks amd64/arm64 from `uname`, verifies the signed `SHA256SUMS` with `ssh-keygen` (so the stage adds `openssh-client`) and always installs the latest release (no pin option). CLI telemetry is on by default; the image sets `DO_NOT_TRACK=1` ([SPEC-11 §1](SPEC-11-deployment-and-demo.md#1-development-container)) |
| O10 | Can node and relationship properties hold maps (`Spec.header`, `Event.data`)? | M00b | **Closed (2026-11-21): no.** A map, or a list holding lists or maps, raises `DataError` (`InvalidPropertyType`) on nodes and relationships; flat lists, empty lists, `null`, bool, int, float work. Maps as *parameters* (`UNWIND $rows`) work. **`store.py`:** `encode_props()` stores such values as JSON strings under `<name>_json` (`header_json`, `data_json`); every result is decoded on the way out (nodes, relationships, `properties()`, columns named `*_json`), so callers see `header` as a map |
| O11 | Can a `read_only=True` connection open a store on a **read-only mount** (no lock files created)? Does a crashed writer leave a stale `.cypherlite.writer` lock that blocks the next open? | M00b | **Closed (2026-11-21): yes; no stale lock.** A read-only open creates and writes no file and works on a `:ro` mount, **but only if the `.cypherlite.lock` markers exist** in the store root and in `wal/` (content is irrelevant; `.cypherlite.writer` is not needed). Without them it fails with "read-only open requires an existing database / WAL". The writer lock is an OS lock: a SIGKILLed writer leaves the files, but the next writable open succeeds at once. A read-only open never creates a missing store. A read-only connection refuses a write in autocommit mode, but **inside a transaction it accepts the write and refuses only at commit**, so the always-rollback rule of [SPEC-09 §3](SPEC-09-security.md#3-query-guard) is load-bearing. **`store.py`:** `exists()` checks the markers; a read-only open of a store without them fails with `invalid_input` naming them; `sdd snapshot` and the `.gitignore` keep them ([D001](../deviations/D001-store-copies-keep-lock-markers.md), [SPEC-08 §3](SPEC-08-cli-and-exports.md#3-exports-and-snapshots)) |
| O12 | Can one process hold the writable connection **and** open a `read_only=True` snapshot of the same store? (Used for guarded queries, [SPEC-09 §3](SPEC-09-security.md#3-query-guard)) | M00b | **Closed (2026-11-21): yes.** The snapshot opens next to the writer (same or another process, on any thread), holds every *committed* transaction, flushed or not, and nothing uncommitted. It loads once and does not follow later commits. Opening takes about 20 ms at 20k nodes. **`store.py`:** `read_snapshot()` opens a fresh read-only connection on the calling thread for each guarded query (thread affinity rules out sharing one), runs it in a rolled-back transaction and closes it; it never waits behind the write queue. In-memory and read-only stores run it as a rolled-back job instead |

**Decisions** ([docs/decisions/](../decisions/README.md)): DEC-001 snapshots only (accepted), DEC-002 deviation links in Markdown (accepted), DEC-003 2 h claim TTL + forced release, `last_session` = since the agent's last `what_changed` (accepted), DEC-004 invented sample (accepted). None pending.
