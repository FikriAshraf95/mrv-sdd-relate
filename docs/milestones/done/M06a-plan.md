# M06a implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-11 §5](../../specs/SPEC-11-deployment-and-demo.md#5-sample-project), [SPEC-08 §3–4](../../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots), [SPEC-06 §2, §5](../../specs/SPEC-06-code-context.md#2-impact), [SPEC-10 §3](../../specs/SPEC-10-testing-and-benchmark.md#3-fixtures), [DEC-004](../../decisions/DEC-004-sample-fallback.md), [DEC-001](../../decisions/DEC-001-committed-store.md), [D001](../../deviations/D001-store-copies-keep-lock-markers.md). Milestone: [M06a](M06a-sample-and-exports.md). Previous plan: [M04b-plan](M04b-plan.md).
Follow `CLAUDE.md`. D005 is the highest deviation. This plan expects **no new deviation**: every decision below fills a gap the spec leaves open and goes into the owning spec in the same change (§8). If you knowingly depart from a spec anyway, log it (`sdd deviation …`, D006…).

## 0. Scope and boundaries

- **In:** `sdd export --mermaid | --cypher | --json | --claude-status`; endpoint 15 `GET /api/mermaid?preset=`; `sdd snapshot`; O3 closed; table `impact` gains commits (new task **M06a.6**); the invented sample `samples/courtside/` (docs + placeholder code); `scripts/make_sample.py` (scripted history → `samples/courtside.bundle`, then sync + snapshot); the committed stores; tests; spec edits; `Dockerfile` runtime stage copies `samples/`; `.sddignore` gains `samples/`.
- **Not in:** `replay.toml`, `sdd demo prepare|replay|serve`, `docker-compose.yml` for judges, public deploy (all M06b); static site (M08); a dashboard button for Mermaid.
- **Layering:** only `graph/store.py` imports `relate` **and only it runs the `relate` CLI** (subprocess), so every Relate access stays behind one door. Cypher lives in `graph/` and `service/` only. All Markdown writes go through `sync/writeback.py`. No new dependencies.
- **Nothing from office-suite-v2.** The sample is invented from scratch (domain below). Do not open `D:\Works\ai\office-suite-v2`. Do not use the table name `attachments` anywhere in the sample.
- **Do not commit.** Leave the work tree for the Opus review; it commits.

## 1. O3: what the tooling allows (verified 2026-11-22 on relate-db 1.2.0)

- The Python package has **no** clone or codec API (`Connection` has only `execute/commit/rollback/flush/close/…`).
- The `relate` CLI (in the dev image at `/usr/local/bin/relate`; **not** in the runtime image) does both:
  - `relate clone SRC DEST.rl` → single-file bundle;
  - `relate clone --to-snapshot-format json SRC DEST` → directory store with a readable `graph.json`;
  - `relate clone SRC DEST` → plain directory copy.
  - Clone reads the LSN visible on open and works **beside a running writer** (tested against this repo's live store with the daemon up: same node and relationship counts).
  - Clone output contains `.cypherlite.writer` files (root and `wal/`); delete them (D001). The `.cypherlite.lock` markers stay.
  - `relate.connect(path, read_only=True)` opens the `.rl`, the JSON-codec directory and the plain clone.
- **Answer:** `.rl` and JSON copies are possible only through the `relate` CLI. Record this in SPEC-00 §8 O3 (**Closed (2026-11-22)**) and SPEC-08 §3.

## 2. Store helpers (`graph/store.py`)

Add, at module level:
- `relate_cli() -> str | None`: `shutil.which("relate")`.
- `clone(src: str, dest: Path, *, codec: Literal["json"] | None = None) -> None`: runs `relate clone [--to-snapshot-format json] src dest` (`subprocess.run(..., check=False, capture_output=True, text=True, timeout=120)`), raises `SddError("invalid_input", …)` with stderr on failure, then deletes every `.cypherlite.writer` under `dest` (if `dest` is a directory). Raises if the CLI is missing (callers check first).
- `copy_store(src: str, dest: Path) -> None`: `shutil.copytree` that skips `.cypherlite.writer`. Used only when the CLI is missing and the caller holds the writer itself (no daemon).
- `counts(path: str | Path) -> dict[str, Any]`: opens `read_only=True`, returns `{"nodes": {label: n}, "relationships": {type: n}, "total_nodes", "total_relationships"}`, closes. Reuse whatever `service/info.py` already queries for the per-label counts (move the Cypher into `graph/queries/` if it isn't already, or call the same named query) so live and copy are counted the same way.

## 3. `sdd snapshot` (M06a.3) — `service/snapshot.py`

`snapshot(settings, out: Path | None) -> dict`; default `out = <project>/.sdd/snapshots`. `:memory:` → `invalid_input`.
1. **Checkpoint.** No daemon (see `service/remote.detect`): `Store.open(settings.store_path)` writable (fails `daemon_running` if another writer holds it), `checkpoint()`, `close()`. Daemon running: skip the checkpoint, because `relate clone` reads every committed transaction from the WAL; without the CLI and with a daemon, fail with `daemon_running` and a message saying to install the `relate` CLI or stop the daemon.
2. Replace `out/graph`, `out/graph.rl`, `out/graph-json` (delete the old ones first; never touch anything else in `out`).
3. With the CLI: `clone(store, out/"graph")`, `clone(store, out/"graph.rl")`, `clone(store, out/"graph-json", codec="json")`. Without it: `copy_store(store, out/"graph")`; the other two are `skipped`.
4. Verify: `counts()` on the live store (read-only open) and on each written copy; any mismatch is an error (`invalid_input`, details with both counts).
5. Result: `{"out", "copies": {"graph": "written", "graph_rl": "written"|"skipped", "graph_json": "written"|"skipped"}, "relate_cli": bool, "checkpointed": bool, "total_nodes", "total_relationships"}`. Human output: one line per copy plus the totals.

CLI: `@app.command() def snapshot(ctx, out: --out, project, store, as_json)`.

## 4. Exports (M06a.3) — `service/exports.py` + `sdd export`

All four read the graph through `commands._local(settings, write=False)` (a read-only open, or a throwaway sync for `:memory:`), **daemon or not**: a `read_only` open works beside the daemon (O12), and there is no endpoint for a full dump. Note this in SPEC-08 §1 rule 1 ("exports and `snapshot` read the store files directly").

CLI: one `export` command with mutually exclusive options `--mermaid TEXT`, `--cypher`, `--json`, `--claude-status`, plus `--out FILE` (stdout if absent; ignored by `--claude-status`). Exactly one mode, else `invalid_input` (exit 2).

### 4.1 `--mermaid PRESET|CYPHER`
- **Which:** the argument is Cypher when it matches `^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|CALL|RETURN)\b` (case-insensitive); otherwise a preset name → `impact.preset(runtime, name)`.
- **Cypher mode:** run through `query_guard.run_query`. Every result value that is a map with an `id` key becomes a node; a row with columns `source` and `target` (and optional `type`, default `RELATED`) whose values are IDs or node maps becomes an edge. Look labels/titles up with one named query over the collected IDs (`labels(n)[0]`, `coalesce(n.title, n.name, n.message, n.path, n.id)`), producing the `/api/graph` node shape (`api_views.shape_node`). Unknown IDs are dropped.
- **Renderer** `render_mermaid(graph: dict, *, max_nodes: int = 60) -> str`, pure:
  - first line `flowchart LR`;
  - node order: the preset's root first (the first node in `graph["nodes"]` — make `_chain_graph`/`_schema_graph` keep their root first, or pass `root`), then the rest sorted by `(label, id)`; keep the first 60; drop edges to dropped nodes; when nodes were dropped, append `%% truncated N nodes` as the last line;
  - Mermaid IDs: `n` + index (`n0`, `n1`, …) in that order (collision-free, sanitised by construction);
  - shapes: Spec `[[…]]`, Section `[…]`, Task `(…)`, Deviation `{{…}}`, File `[/…/]`, Table `[(…)]`, Milestone `([…])`, Feature `>…]`, everything else (Column, Commit, AcceptanceCheck, Domain, Label, …) `[…]`;
  - label text: `"<id>: <title>"` when title differs from id, else the id; for the `schema` preset (label `Label`) use the node `title` (`Table (12)`). Escape: wrap in double quotes, replace `"` with `#quot;`, `<` `#lt;`, `>` `#gt;`, newlines with a space; cut to 60 characters with `…`;
  - edges: `nA -->|TYPE| nB`; when the edge has a `count`, `nA -->|"TYPE (12)"| nB`; sorted by (source index, type, target index);
  - classes: one `classDef <label lowercased> fill:#…,stroke:#…,color:#111` per label present (fixed palette dict, same hues as `web/static/cystyle.js` where a label exists there) and one `class nX,nY <label>` line per label;
  - output ends with a newline; deterministic (golden files).

### 4.2 `--cypher`
An idempotent script, **one statement per line, each ending in `;`**, so a loader can split on lines:
- header comment lines `// sdd export --cypher · <N> nodes · <M> relationships` (no timestamp, so re-exports diff cleanly);
- nodes sorted by id: `MERGE (n:<Label> {id: '<id>'}) SET n += {<props>};` with the props **as stored** (re-encode decoded maps with `store.encode_props`, so `header_json` etc. round-trip), keys sorted, `null`s skipped;
- relationships sorted by (source id, type, target id): `MATCH (a:<L1> {id: '…'}), (b:<L2> {id: '…'}) MERGE (a)-[r:<TYPE>]->(b)` plus ` SET r += {…}` when it has properties, then `;`;
- literals: strings single-quoted with `\\`, `\'`, `\n`, `\r`, `\t` escaped; ints/floats/bools as Cypher literals; lists of scalars `[…]`; keys backquoted when not `^[A-Za-z_][A-Za-z0-9_]*$`.
- **Probe Relate first** (throwaway script in the container, in-memory store, not committed): `MERGE … SET n += {…}`, `MATCH (a:L {id:…}), (b:L {id:…}) MERGE (a)-[r:T]->(b) SET r += {…}`, escaped quotes/newlines inside strings, list literals. Adjust the format to what works and note it in the M06a.3 completion notes. Add `load_cypher(store, script)` in `service/exports.py` (runs each line in one write job) for the test and for M08.

### 4.3 `--json`
`{"nodes": [...], "edges": [...]}` for the whole graph in the `/api/graph` shape (`shape_node` for nodes, `{source, target, type}` edges), sorted by id / (source, type, target), `indent=2`, `ensure_ascii=False`. No limit.

### 4.4 `--claude-status`
- Block between `<!-- sdd:status -->` and `<!-- /sdd:status -->` in the project's root `CLAUDE.md`. Missing file or markers → `invalid_input` (exit 2) with a message showing the two marker lines to add. Text outside the markers is byte-for-byte unchanged.
- Content (deterministic, no timestamps), one line each, the marker lines themselves unchanged:
  ```
  _Generated by `sdd export --claude-status`; edit outside the markers._
  - **Done:** M01 Skeleton and members (2026-09-18) · M02 … (dates from the DONE status when the graph has them, else omitted)
  - **Next:** [M05a Waitlist](docs/milestones/M05a-waitlist.md) (3/4 tasks open). Read first: SPEC-05 §1 · SPEC-05 §2 · …
  - **Open deviations:** D003 Cancelled bookings are kept (M03b) · … | none
  - **Active claims:** M05a.3 by sonnet-1 · … | none
  ```
  "Next" = the first milestone in order that is not done; its *Read first* = the sections it `READS`, in source order.
- Write through a new `writeback.replace_status_block(text, block) -> tuple[str, bool]` (pure) + `atomic_write`, with a source-hash check (re-read the file right before writing; if it changed since it was read, `source_changed`). Idempotent: a second run reports `changed: false` and writes nothing.
- Result `{"path": "CLAUDE.md", "changed": bool}`.

### 4.5 Endpoint 15 `GET /api/mermaid?preset=`
In `web/api.py`: `text/plain; charset=utf-8`, body `render_mermaid(impact.preset(runtime, name))`. Presets only (never Cypher), so it is safe in public mode; make sure `public.py`'s app serves it too (it reuses `create_app` — check). Missing `preset` → `invalid_input` 400; unknown → `node_not_found` 404 through the existing error handler.

## 5. Table impact reaches commits (M06a.6)

SPEC-06 §2's Table row ends at tests, so `impact` on a table never fills `commits`, yet the M06a walkthrough needs every group. Add to the Table row: "· Commits that `COMPLETES` those Tasks". Implement as one named query `impact.table.commits` in `graph/queries/impact.cypher` (tasks `GOVERNED_BY` the defining section or a section that `MENTIONS` / `LINKS_TO` the table ← `COMPLETES` commit; `via` extends the task's chain with `<-COMPLETES`), appended to `TABLE_STEPS` after the task steps. Commit items' title = the short message, like the File traversal's commits. Columns inherit it through `COLUMN_STEPS` (they run the table traversal). Test in `tests/spec06/` on `tool_style` with history: `impact documents` has a commit whose `via` ends `<-COMPLETES <sha>`.

## 6. The sample: `samples/courtside/` (M06a.1, M06a.2)

**Courtside**: bookings for a community sports hall (badminton and tennis courts). A small team (invented: Nadia Okafor, Tomás Reyes, Mei Lin Chua, emails `@courtside.example`) builds it spec-first. **The centrepiece table is `bookings`.** Write in plain, believable English, short files. Format: the office-suite conventions (`> **Spec ID:** SPEC-02 · **Consumed by:** …` headers, `### <table>` schema tables with `→ <table> [restrict]`, letter-suffixed milestones, `**Status: DONE (…)**` paragraphs, a plan file, nested `> > **DEVIATION:**` notes in specs) plus this tool's conventions (task IDs `**M03a.2**`, `(after …)`, Feature lines `> **Feature:** … · **Domain:** … · **Implements:** \`src/…/**\` · **Tables:** …`). Mirror the shapes in `tests/fixtures/suite_style/` and `tests/fixtures/tool_style/` (read them; they are invented too).

### 6.1 Specs (`docs/specs/`)
| File | Feature line | Sections |
|---|---|---|
| `SPEC-00-overview.md` | — | 1 Purpose · 2 Glossary (member, court, slot, booking, waitlist, desk) · 3 Users · 4 Spec map · 5 Non-goals · **6 Conventions** (UTC, money in cents, IDs uuid; this is the `always_include` section) |
| `SPEC-01-members-and-access.md` | Members · Accounts · `src/members/**` · members | 1 Sign-up · 2 Roles (member, desk, admin) · 3 Sessions · 4 Acceptance checks (3) |
| `SPEC-02-database-schema.md` (schema spec) | — | `## 1. Accounts ([SPEC-01](../…))` → `### members` · `## 2. Courts ([SPEC-03](../…))` → `### courts`, `### opening_hours` · `## 3. Bookings ([SPEC-03](../…))` → `### bookings` · `## 4. Payments ([SPEC-04](../…))` → `### payments`, `### refunds` · `## 5. Waitlist and reminders ([SPEC-05](../…))` → `### waitlist_entries`, `### reminders` · `## 6. Table → milestone map` · `## 7. Acceptance checks` (3: FK columns are indexed; two bookings of one court never overlap; a member with bookings cannot be deleted) |
| `SPEC-03-booking-rules.md` | Booking · Courts · `src/booking/**` · bookings, courts, opening_hours | 1 Slots and opening hours · 2 Making a booking · 3 Overlap rule · 4 Cancellation · 5 Desk overrides · 6 Acceptance checks (4) |
| `SPEC-04-payments.md` | Payments · Billing · `src/payments/**` · payments, refunds, bookings | 1 Prices · 2 Taking payment · 3 Refunds · 4 Acceptance checks (3) |
| `SPEC-05-waitlist-and-reminders.md` | **two lines:** Waitlist · Courts · `src/waitlist/**` · waitlist_entries, bookings; Reminders · Notifications · `src/reminders/**` · reminders, bookings | 1 Joining the waitlist · 2 Promotion · 3 Reminders · 4 Acceptance checks (3) |
| `SPEC-06-reports-and-audit.md` | Reports · Admin · `src/reports/**` · bookings, payments | 1 Daily usage report · 2 Audit trail · 3 Acceptance checks (2) |

Tables (8), columns in the `| Column | Type | Notes |` shape: `members` (id PK, email unique, name, role, created_at); `courts` (id, name, surface, indoor); `opening_hours` (id, court_id → courts [cascade], weekday, opens_at, closes_at); **`bookings`** (id, member_id → members [restrict], court_id → courts [restrict], starts_at, ends_at, status `held|confirmed|cancelled`, cancelled_at null, created_at); `payments` (id, booking_id → bookings [restrict], amount_cents, captured_at null); `refunds` (id, payment_id → payments [restrict], amount_cents, reason); `waitlist_entries` (id, court_id → courts, member_id → members, wanted_start, promoted_booking_id → bookings null); `reminders` (id, booking_id → bookings [cascade], send_at, sent_at null). So `payments`, `waitlist_entries` and `reminders` depend on `bookings`. Spec prose in SPEC-03/04/05/06 mentions `` `bookings` `` in backticks where natural, and links `[SPEC-02 bookings](../SPEC-02-database-schema.md#bookings)`.

### 6.2 Milestones (`docs/milestones/`, done ones under `done/`)
Each has `> **Depends on:**`, a `> **Read first:**` line with section links, `## Goal`, `## Tasks` (`### Backend` / `### Tests` groups), `## Acceptance criteria`, a status paragraph. Task lines link the sections they implement (and `SPEC-02 bookings` wherever a task writes that table).
| Milestone | State | Tasks | Deviations |
|---|---|---|---|
| `done/M01-skeleton-and-members.md` | DONE (2026-09-18) | M01.1 skeleton · M01.2 members + sign-up · M01.3 roles · M01.4 tests SPEC-01 §4 checks 1–3 | none |
| `done/M02-courts-and-schema.md` | DONE (2026-09-30) | M02.1 courts · M02.2 opening hours · M02.3 migration for `bookings` · M02.4 tests SPEC-02 §7 checks 1, 3 | D001 |
| `done/M03a-booking-core.md` + `done/M03a-plan.md` | DONE (2026-10-14) | M03a.1 slot grid · M03a.2 create booking · M03a.3 overlap rule (after M03a.2) · M03a.4 tests SPEC-03 §6 checks 1–3 | D002 |
| `done/M03b-cancellations.md` | DONE (2026-10-24) | M03b.1 cancel · M03b.2 desk overrides · M03b.3 tests SPEC-03 §6 check 4 and SPEC-02 §7 check 2 | D003 |
| `done/M04-payments.md` | DONE (2026-11-07) | M04.1 prices · M04.2 take payment · M04.3 refunds (after M04.2) · M04.4 tests SPEC-04 §4 | D004, D005 |
| `M05a-waitlist.md` | in progress (`**Status:**` empty) | **[x]** M05a.1 join · **[x]** M05a.2 promotion · [ ] M05a.3 tell the member (after M05a.2) · [ ] M05a.4 tests SPEC-05 §4 checks 1–2 | D006 |
| `M05b-reminders.md` | todo | M05b.1 schedule on confirm · M05b.2 send job · M05b.3 drop with cancelled booking (after M05b.1) · M05b.4 tests SPEC-05 §4 check 3 | — |
| `M06-reports-and-audit.md` | todo | M06.1 daily usage report · M06.2 audit trail · M06.3 tests SPEC-06 §3 | — |

### 6.3 Deviations (`docs/deviations/D00n-….md` + `docs/DEVIATIONS.md` index + spec notes)
| ID | Milestone · task | Title | Amends | Affects | Status |
|---|---|---|---|---|---|
| D001 | M02 · M02.2 | Opening hours are per court, not per hall | SPEC-02 `opening_hours`, SPEC-03 §1 | `opening_hours`, `src/booking/hours.py` | Resolved → spec updated |
| D002 | M03a · M03a.2 | Bookings store an end time, not a duration | SPEC-02 `bookings`, SPEC-03 §2 | `bookings`, `src/booking/model.py` | Resolved → spec updated |
| D003 | M03b · M03b.1 | Cancelled bookings are kept with `cancelled_at` | SPEC-03 §4, SPEC-02 `bookings` | `bookings`, `src/booking/cancel.py` | Open |
| D004 | M04 · M04.3 | Late refunds are partial | SPEC-04 §3 | `refunds`, `src/payments/refunds.py` | Open |
| D005 | M04 · M04.2 | Payment is taken at check-in | SPEC-04 §2 | `payments`, `bookings` | Open |
| D006 | M05a · M05a.2 | A promoted waitlist entry holds the slot for 15 minutes | SPEC-05 §2 | `bookings`, `waitlist_entries`, `src/waitlist/promote.py` | Open |

Notes in the specs: `> > **DEVIATION:** see [D002](../…) — …` under `### bookings` (D002, D003, D006) and `### opening_hours` (D001), `> **DEVIATION:**` under the SPEC-03/04/05 sections. So `bookings` is touched by SPEC-02, 03, 04, 05, 06, milestones M02, M03a, M03b, M04, M05a, M05b, M06, and deviations D002, D003, D005, D006.

### 6.4 Other files
`CLAUDE.md` (short project guide in this tool's style, with an empty `<!-- sdd:status -->` / `<!-- /sdd:status -->` block that `make_sample.py` fills), `README.md`, `docs/deviations/README.md` (template), `pyproject.toml` (name `courtside`, no deps). **No `.sdd/config.toml`** (the defaults fit) and **no `.sdd/.gitignore`** (`sdd init`'s one ignores `/graph/`, which would hide the committed store from git).

### 6.5 Code tree (placeholder Python, 3–15 lines each, a docstring naming the spec section, plausible stubs)
`src/members/{__init__,signup,roles}.py` · `src/booking/{__init__,model,slots,hours,overlap,cancel,overrides}.py` · `src/payments/{__init__,prices,capture,refunds}.py` · `src/waitlist/{__init__,join,promote}.py` · `src/reminders/__init__.py` (empty stub: M05b not started) · `src/reports/__init__.py` · `migrations/000{1..5}_*.sql` (members, courts, bookings, payments, waitlist) · tests named after checks (`def test_spec03_ac2_overlap_is_refused(): …`): `tests/test_members.py` (SPEC-01 1–3), `tests/test_schema.py` (SPEC-02 1–3), `tests/test_booking.py` (SPEC-03 1–4), `tests/test_payments.py` (SPEC-04 1–3), `tests/test_waitlist.py` (SPEC-05 1 only). Check how the walker links tests to checks (`tests/fixtures/tool_style/tests/test_ingest.py`, SPEC-04 §4) and match it.

### 6.6 `scripts/make_sample.py` (runs in the dev container: `uv run python scripts/make_sample.py`)
1. **Status block:** `sdd export --claude-status --project samples/courtside --store :memory:` (call the service function directly), so the sample's CLAUDE.md shows the generated block. This edits `samples/courtside/CLAUDE.md` in place before the history is built.
2. **History:** in a temp dir, `git init -b main`, then replay `COMMITS`, a list in the script of `Commit(date, author, message, paths, stages={})`: each commit writes the listed paths (from `samples/courtside/`, or from `stages[path]` for an earlier version of a file), then commits with fixed `GIT_AUTHOR_*`/`GIT_COMMITTER_*` dates and names, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1` (like `tests/conftest.py::git_commit_all`). About 30 commits, 2026-09-08 → 2026-11-14, in milestone order: a docs commit for the specs, then per milestone feature commits naming their tasks (`feat: overlap rule [M03a.3]`), docs commits that tick tasks and close milestones (`docs: close M03a [M03a]`), deviation commits (`docs: D002 bookings store an end time [M03a.2]`), a couple of commits without a task (`chore: format`). Files with history: `src/booking/model.py` changes in M02.3, M03a.2 (stage without `ends_at`), M03b.1 (adds `cancelled_at`), M05a.2 (adds `held`); `docs/specs/SPEC-02-database-schema.md` changes several times (use `stages` for the early versions where it is cheap). Use `stages` for milestone files where it is cheap (unticked boxes before the closing commit); otherwise the final text is fine.
   - **Assert** the tip tree equals `samples/courtside/` (every file, byte for byte, ignoring `.sdd/`); fail loudly otherwise.
   - `git bundle create samples/courtside.bundle main`.
3. **Store:** clone the bundle into a second temp dir (the project root for sync, so git sync sees the history), delete `samples/courtside/.sdd/graph` and `samples/courtside/.sdd/snapshots`, then run the service functions with `project=<clone>`, `store=samples/courtside/.sdd/graph`: `indexing.sync`, then `snapshot.snapshot(out=samples/courtside/.sdd/snapshots)`. Delete any `.cypherlite.writer` left in `samples/courtside/.sdd/graph`.
4. **Checks** (fail on any): doctor on the sample has zero warnings of any severity; `impact bookings` has every group non-empty: specs, sections, tables, features, files, tasks_open, tasks_done, deviations, tests, commits; **no absolute temp path** (`/tmp`, the clone path) appears in `samples/courtside/.sdd/snapshots/graph-json/graph.json`. Print a summary (commits, nodes, relationships, group counts).
5. Idempotent: re-running rebuilds everything from `samples/courtside/` (the bundle SHAs stay the same because dates and authors are fixed).

## 7. Committed stores (M06a.4)

- `samples/courtside/.sdd/graph/` (built store) and `samples/courtside/.sdd/snapshots/{graph/, graph.rl, graph-json/}`, plus `samples/courtside.bundle`. Check `git status --ignored` that none of them is ignored (root `.gitignore` anchors `/.sdd/graph/`; `.cypherlite.writer` is ignored everywhere, which is right) and that `.dockerignore`'s `.sdd` only matches the root.
- This repo: `uv run sdd snapshot` with the daemon running (the CLI clones beside it) → `.sdd/snapshots/`. Never `.sdd/graph/`.
- `.sddignore`: add `samples/` (do this **first**, before creating any sample file, so the running daemon never walks the sample into this repo's graph).
- `Dockerfile` runtime stage: `COPY samples /app/samples` (replace the "added here by M06a" comment). `.env.example`: if it has a `SAMPLE` key, set it to `courtside`.

## 8. Spec and doc edits (same change)

- SPEC-00 §8: O3 → **Closed (2026-11-22)** with the §1 answer.
- SPEC-08 §1 rule 1: exports and `snapshot` read the store files directly (a `read_only` open, O12), daemon or not. §3: Mermaid ID/shape/label/class/truncation rules and Cypher-mode input from §4.1; the `--cypher` line format; `--claude-status` content and the missing-marker error; snapshot steps (relate CLI when on PATH, copy fallback without it, `daemon_running` when neither works, counts verified, result shape).
- SPEC-06 §2: Table row gains "· Commits that `COMPLETES` those Tasks".
- SPEC-07 row 15: errors (`invalid_input` without `preset`, `node_not_found`).
- SPEC-11 §5: the sample is `samples/courtside/` (Courtside, a sports-hall booking app); the centrepiece table is `bookings`; the bundle and store paths. §3: runtime image copies `samples/`.
- `tests/fixtures/README.md` needs nothing; the sample is not a fixture.

## 9. Tests (M06a.5 and the rest)

Named `test_spec08_ac04_…` etc., in `tests/spec08/test_exports.py` unless noted. Fixtures: `tool_style` with `TOOL_STYLE_HISTORY` (fixed dates → stable SHAs).
- **ac4:** `render_mermaid` of the `schema` and `impact:documents` presets equals `tests/spec08/golden/schema.mmd` and `impact_documents.mmd` (write them from the implementation once, read them, check they look right; a module-level `UPDATE = os.environ.get("SDD_UPDATE_GOLDEN") == "1"` rewrites them). Unit tests: escaping (`"`, `<`, `>`), shapes per label, 61 nodes → 60 kept + `%% truncated 1 nodes`, Cypher-mode argument detection, CLI `sdd export --mermaid schema --out F`.
- **ac5:** `--cypher` on tool_style, loaded with `load_cypher` into `Store.open(":memory:")`, gives the same per-label and per-type counts; loading it twice changes nothing (idempotent); a node with a `_json` property and a string with `'`, `\` and a newline round-trips.
- **ac6:** `--claude-status` on a copy whose CLAUDE.md has text before, between and after the markers: bytes outside unchanged, block filled, second run `changed: false`; no markers → exit 2 `invalid_input`; also through the CLI.
- **ac7:** `sdd snapshot` on a synced tool_style store: `graph/`, `graph.rl`, `graph-json/` exist (skip the last two with `pytest.skip` when `relate_cli()` is None), no `.cypherlite.writer` anywhere, each opens with `Store.open(…, read_only=True)` and has the live counts; `:memory:` → `invalid_input`.
- `tests/spec07`: endpoint 15 (`text/plain`, starts `flowchart LR`; missing preset 400; unknown 404; served in public mode too — follow how existing public-mode tests build the app).
- `tests/spec06`: table impact reaches commits (§5).
- `tests/spec11/test_sample.py` (new package with `__init__.py`): on a **copy** of `samples/courtside` in `tmp_path`, doctor reports zero warnings; on a copy of the committed store, `impact bookings` (read-only open) fills every group listed in §6.6 step 4; the bundle's tip tree matches the sample (`git clone` the bundle into tmp_path and compare). These read only files committed in this repo, no network.

## 10. Order of work, claims, and gates

Agent name `sonnet-1`. The daemon runs for this repo; use the CLI (it routes through the daemon): `uv run sdd claim <task> --agent sonnet-1`, `uv run sdd context <task>`, `uv run sdd section "SPEC-08 §3"`, then `uv run sdd done <task> --agent sonnet-1 --notes "…" --files …` (this ticks the box in the milestone file; do not tick boxes by hand).
1. `.sddignore` += `samples/`. Probe Relate (§4.2).
2. **M06a.3** (store helpers, snapshot, exports, endpoint 15, spec edits) and **M06a.6**.
3. **M06a.1** (docs), then **M06a.2** (code tree, `make_sample.py`; run it until its checks pass and `sdd doctor --project samples/courtside --store :memory:` shows zero warnings).
4. **M06a.5** and the other tests.
5. **M06a.4**: run `make_sample.py` one final time, then `uv run sdd snapshot` for this repo.
6. Gates, all green: `uv run pytest -q` and `sh -c "uv run ruff check . && uv run ruff format --check . && uv run mypy src/sdd && uv run lint-imports"`. If the same test fails twice or a design question comes up, stop and report instead of guessing.
7. Do **not** run `sdd milestone-done`; the Opus review closes the milestone.

Report at the end: files added/changed, the Relate probe outcome, the `make_sample.py` summary, the `sdd impact bookings` group counts, gate results, any deviation logged, anything left open.
