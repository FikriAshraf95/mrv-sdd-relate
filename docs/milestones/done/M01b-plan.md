# M01b implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-02 §1–2, §4–5, §7](../../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties), [SPEC-04 §2–3](../../specs/SPEC-04-sync.md#2-incremental-sync), [SPEC-08 §1–2](../../specs/SPEC-08-cli-and-exports.md#1-rules), [SPEC-10 §4](../../specs/SPEC-10-testing-and-benchmark.md#4-invariant-suite), [SPEC-03 §1, §2.1, §7](../../specs/SPEC-03-markdown-parsing.md#7-acceptance-checks), [SPEC-01 §3–4](../../specs/SPEC-01-architecture.md#3-module-boundaries). Milestone: [M01b](M01b-graph-sync.md). Previous plan for the parser API: [M01a-plan](M01a-plan.md).
Follow `CLAUDE.md`. D001 is the highest deviation; this plan already decides **D002** and **D003** (§9). Any other knowing departure → `D004…`, index row, spec note, same change. Where a spec is merely silent, decide, write the rule into the spec, and list it in the report.

## 0. Scope and boundaries

- In: `graph/upsert.py`, `sync/indexer.py`, `sync/writeback.py` (atomic write helper + legacy task-ID rewrite only), `service/` functions for `sync`, `status`, `doctor`, `ids --write`, the four CLI commands, tests, `.sdd/config.toml` for this repo.
- Not in: watcher, daemon, daemon detection (`daemon.json`, M02.5), SSE, code walker, git, Table/Column/Feature/Domain nodes, MENTIONS/AFFECTS to code files or tables (M04a/M04b), claims and `complete_task` (M03a).
- **Import rules (import-linter enforces them):** `graph/` may not import `parse/` or `sync/`; `sync/` may import `parse`, `graph`, `ids`, `errors`, `config`; `cli` may import only `service`, `ids`, `errors`, `config` (never `graph`, `sync`, `parse`). So: **sync resolves**, graph receives plain data, CLI calls service.
- Only `graph/store.py` imports `relate`. All graph writes go through `Store.write` (one job = one transaction). A job cannot queue another job.
- Probed on relate-db 1.2 (2026-11-22, in-memory): `UNWIND $rows AS row MERGE (n:Task {id: row.id}) SET n += row.props`, `REMOVE n.x`, `SET n.p = null` (removes the key), `MATCH ()-[r {src:$s}]->() DELETE r`, `MATCH (n) WHERE n.id IN $ids`, `DETACH DELETE`, `CASE` in `SET`, `labels(n)`, `properties(r)` all work. **Not yet probed: `SET n = $map` (full replace).** Probe it first; if it fails, use `SET n += $props` plus `REMOVE` of the stale keys computed in Python (§2.2).
- Labels and relationship types cannot be parameters: they are formatted into the Cypher text **only from whitelists** (`schema.LABELS`, new `schema.REL_TYPES`). Anything else raises `ValueError`.

## 1. Data flow of one full sync

```
discover(settings)            → {path: kind}           (sync/indexer.py, file I/O)
read + hash + parse every file → ParsedFile list         (parse/*)
duplicate-ID pass             → drop later duplicates + duplicate_id warnings
cross_check_index             → deviation_index_mismatch warnings
GraphState = read_state(store) → File hashes, Meta, old catalog rows
changed / removed / relink_all decided in Python
phase 1  (one write job per changed file, order spec → milestone → plan → deviation → deviation index → doc)
removals (one write job per removed file)
phase 2  (one write job per file in changed ∪ (all files if relink_all))
meta job (schema_version, project_name, last_full_sync)
checkpoint()
→ SyncReport
```

`sdd sync` is always a full scan in M01b (it is the daemon's startup scan in M02). Hash equal → the file is skipped (no phase 1). Re-syncing an unchanged repo therefore runs **no** phase 1 or phase 2 jobs; only the Meta job writes (`last_full_sync`, SPEC-04 §2 step 8).

## 2. `graph/upsert.py`

Plain-data API; no `parse` imports. All functions take a `Tx` (run inside a caller's job) unless noted.

```python
@dataclass(frozen=True, slots=True)
class NodeIn:      label: str; id: str; props: dict[str, Any]      # parsed props, no last_synced
@dataclass(frozen=True, slots=True)
class RelIn:       type: str; from_id: str; to_id: str; props: dict[str, Any]   # resolved; no src
@dataclass(frozen=True, slots=True)
class FileIn:      path: str; content_hash: str                     # → File node file:<path>

@dataclass
class NodeChanges:                      # what phase 1 did, for the report and Events
    created: list[str]; updated: list[str]; deleted: list[str]
    sections_changed: list[str]         # changed_at set this run
    ticked: list[str]; unticked: list[str]; released: list[str]

def upsert_file_nodes(tx, file: FileIn, nodes: list[NodeIn], *, keep_ids: set[str],
                      now: str, initial: bool, writeback: bool) -> NodeChanges
def replace_file_rels(tx, src: str, rels: list[RelIn], unresolved: dict[str, list[str]]) -> int
def delete_file(tx, path: str, *, keep_ids: set[str], now: str, initial: bool) -> NodeChanges
def add_event(tx, *, kind, actor, target_id, summary, data, now) -> str   # returns event id
def write_meta(tx, *, schema_version: int, project_name: str, last_full_sync: str | None) -> None
def read_state(store) -> GraphState        # store.read calls (not inside a job)
```

### 2.1 Phase 1: `upsert_file_nodes` (one transaction per file)
1. Read the existing nodes of this file's IDs (`MATCH (n:<Label>) WHERE n.id IN $ids RETURN n.id AS id, properties(n) AS p`, per label) **and** the nodes still carrying `source_path = path` (to find removed ones).
2. For each parsed node compute the final property map in Python with a **pure** function `merge_props(label, existing, parsed, *, now, initial, writeback, spec_existed) -> (props, flags)` (unit-test it without a store):
   - Start from `encode_props(parsed)` (maps such as `header` become `header_json`) + `last_synced = now`.
   - **Kept from `existing`** (never overwritten by Markdown): `unresolved` (phase 2 owns it); Section `changed_at`; Task `claimed_by`, `claimed_at`, `completed_by`, `done_at`, `notes`.
   - **Section `changed_at`** (SPEC-02 §2, SPEC-04 §2 step 7): only when `not initial`: existing section whose `content_hash` differs → `now`; new section in a spec that already existed before this job (`spec_existed`) → `now`; otherwise keep the existing value (null for new specs).
   - **Task rules (SPEC-04 §2.1, exactly the table):** new task → graph-only empty, no Event. `checked` unchanged → graph-only untouched. `false → true` and `not initial` → `done_at = now` if empty, `claimed_by`/`claimed_at` removed, the task's `CLAIMED` relationships deleted, flag `ticked` (Event `task_completed`, `actor = "human"`). `true → false` → `done_at` and `completed_by` removed, `notes` kept, flag `unticked` (no Event in the table; none). During the initial sync a hand transition cannot happen (no existing nodes).
   - **Task `status`** derived: `done` if `checked` (or `writeback is False` and `completed_by` set) → else `claimed` if `claimed_by` → else `todo`. Put the derivation in one function `task_status(props, writeback)`; M03a reuses it.
   - **Milestone `status`**: the parser's value unless it is `done`; otherwise `in_progress` if any of its tasks (same file, after the merge) is `done` or `claimed`, else `todo`.
3. Write each node: `MERGE (n:<Label> {id: row.id}) SET n = row.props` batched with `UNWIND` per label (or the `+=`/`REMOVE` fallback: remove every key of `existing` that is not in the final map). The final map must contain `id`.
4. Upsert the File node `file:<path>`: `path`, `name` (basename), `content_hash`, `last_synced`. **Never the file's contents** (SPEC-02 ac5).
5. Delete the nodes that carried `source_path = path` but are no longer produced, **except IDs in `keep_ids`** (every ID produced by any file of this batch; SPEC-04 §3): `DETACH DELETE`. A deleted Task with `claimed_by` set → `task_released` Event, `actor = "sync"` (not on initial).
6. Events (not on initial): `task_completed` per ticked task; `section_changed` per section whose `changed_at` was set now; `spec_added` when the file's Spec node is new. All via `add_event` in the same transaction.

### 2.2 Phase 2: `replace_file_rels` (one transaction per file)
1. `MATCH ()-[r {src: $src}]->() DELETE r` — only this file's own relationships. Never touches `src = "tool"`, `walker`, `git:*`.
2. Create every `RelIn`, grouped by `(type, from label, to label)` (labels via `ids.label_of`) for `UNWIND`: `MATCH (a:<FL> {id: row.f}) MATCH (b:<TL> {id: row.t}) CREATE (a)-[r:<TYPE>]->(b) SET r = row.p` with `row.p` including `src`. Relationship props are only what SPEC-02 says (`note`, `whole`, `src`); drop internal flags such as `strict`. Return the number created; if it is lower than the input (an endpoint vanished), that is a bug: raise.
3. `unresolved`: for every node with `source_path = src`, set `unresolved` to its sorted, de-duplicated list, or remove the key when empty (`SET n.unresolved = null`). This makes `unresolved` wholly owned by one file.

### 2.3 Removals: `delete_file` (one transaction per removed path)
`MATCH ()-[r {src: $path}]->() DELETE r` (rels whose endpoints both survive, e.g. a reversed `Blocks:`), then `DETACH DELETE` the File node and every node with `source_path = path` and `id NOT IN keep_ids`. Because removals run **after** phase 1, a moved file's nodes already carry the new `source_path`, so a move (delete + add in one batch) keeps M17, its tasks, their claims and their tool-owned relationships; only `path` / `source_path` change (SPEC-04 ac3). Events (not on initial): `spec_removed` when a Spec node was deleted, `task_released` for deleted claimed tasks.

### 2.4 Events and ULIDs
`ids.new_ulid(moment: datetime, rand: bytes | None = None) -> str` (stdlib, Crockford base32, 48-bit ms time + 80 random bits from `os.urandom`). Event props per SPEC-02 §2: `id = event:<ulid>`, `at`, `kind`, `actor`, `target_id`, `summary`, `data` (map → `data_json` via `encode_props`). `(e)-[:ABOUT {src: "tool"}]->(target)` when the target still exists (graph-only; write the `src = "tool"` owner for ABOUT into the SPEC-02 §4 `src` table: "and `ABOUT` from sync Events"). M03a reuses `add_event`.

### 2.5 `schema.py`
Add `REL_TYPES: tuple[str, ...]` = every type in SPEC-02 §4, in table order. A test asserts it matches the SPEC-02 §4 table parsed from the spec file (cheap drift guard; invariant 6 proper comes later).

### 2.6 `read_state(store)`
`GraphState(files: dict[path, content_hash], last_full_sync: str | None, catalog_rows: list[Row])` where catalog rows are `label, id, source_path, anchor, title, spec_id, path` for labels Spec, Section, AcceptanceCheck, Milestone, Task, Deviation, Doc, File.

## 3. `sync/indexer.py`

### 3.1 Discovery
- Walk the project with `os.walk`, pruning directories whose name starts with `.` (`.git`, `.sdd`, `.venv`, …) and `node_modules`, `__pycache__`. Match project-relative POSIX paths against the config globs with `pathspec` (`gitwildmatch`), so `**/CLAUDE.md` and `docs/milestones/**/M*.md` behave as written.
- Kinds, first match wins: `spec`, `plan` (glob **and** name `M\d+[a-z]?-plan\.md`), `milestone` (glob **and** name `M\d+[a-z]?-.+\.md`, not `-plan`), `deviation`, `deviation_index`, `doc`. Sorted by path (this is the "first by path wins" order).
- Parser per kind: `parse_spec`, `parse_milestone`, `parse_plan`, `parse_deviation`, `parse_deviation_index`, `parse_doc`. Read bytes; `content_hash` of the File node = sha256 hex of the **raw bytes** (`file_hash(data)`, public: M02's write-back uses the same); decode UTF-8 (`errors="replace"`) for the parser.

### 3.2 Batch-level checks
- **Duplicate IDs across files:** the first file by path keeps the ID; the later file's node is dropped together with the relationships whose `from_id` is that node, and gets a `duplicate_id` warning at the node's `source_line`. `duplicate_id` is not in `WARNING_CODES` yet: add it (severity `warning`) to `parse/model.py` and to the SPEC-03 §1 table (SPEC-04 §3 already names it).
- **Deviation index:** `cross_check_index(index rows, {Dnnn: path}, index path)`; a project with no `DEVIATIONS.md` skips the check.

### 3.3 Resolution (pure function, unit-tested without a store)
- `catalog = Catalog.from_results(all kept results)`, then add every tracked SDD file path that no node claims: `catalog.paths[path] = "file:<path>"`, `catalog.ids.add("file:<path>")` (SPEC-03 §2.1 says a link resolves to Spec, Milestone, Deviation, Doc **or File**; add `File` to the `LINKS_TO` targets in the SPEC-02 §4 table so the two specs agree).
- For each `Rel` of each file: `kind == "mention"` → resolve only against tracked file paths (`catalog.paths` keys that map to `file:`); no hit → drop **silently** for MENTIONS, record as unresolved for AFFECTS (the parser marks AFFECTS with `strict: True`; Tables arrive in M04b, code Files in M04a). Other kinds → `parse.resolve(ref, catalog, path=…)`; collect its `link_moved` warnings.
- Each resolved target → `RelIn(type, from_id, target, props)` with `props = rel.props` minus `strict`, plus `src = path`. De-duplicate on `(type, from, to, note, whole)`.
- **Where an unresolved string is recorded** (decide and write into SPEC-02 §5): on the relationship's source node if this file produces it; else on its resolved target if this file produces that; else on the file's primary node (its Spec, Milestone, Deviation or Doc). A file with no node (the deviation index) records nothing. Any relationship whose `from_id` is not in `catalog.ids` is unresolved (its string is the `from_id`).

### 3.4 Changed, removed, re-link
- `initial = state.last_full_sync is None`.
- `changed` = discovered paths whose hash differs from `state.files` or that are new. `removed` = paths in `state.files` that are no longer discovered.
- **Re-link rule (D003):** build the old catalog from `state.catalog_rows` (same semantics as `Catalog.from_results` + the File fallback) and compare a canonical fingerprint of both (sets of `ids`, `paths` items, `(spec, anchor, id)`, `(spec, slug, id)`, `docs` items). Different → `relink_all` (phase 2 for every file). Also `relink_all` on the initial sync. Otherwise phase 2 runs only for `changed`.
- `keep_ids` = every node ID produced by the kept results.

### 3.5 Entry point
```python
@dataclass
class SyncReport:
    initial: bool; scanned: int; changed: list[str]; removed: list[str]; relinked: int
    warnings: list[ParseWarning]          # parse + duplicate_id + index mismatch + link_moved
    unresolved: dict[str, list[str]]      # node id → strings
    events: int; created: int; updated: int; deleted: int

def analyse(settings) -> Analysis                      # discover + parse + checks + resolve; no store
def full_sync(store, settings) -> SyncReport           # analyse + the jobs of §1
def reset(store) -> None                               # one job: MATCH (n) DETACH DELETE n
```
`analyse()` is what `sdd doctor` runs (§5). `now = settings.now_iso()` once per batch.

## 4. `sync/writeback.py` (minimal; M02 extends it)
- `atomic_write(path: Path, text: str) -> None`: the caller passes text with `\n`; the helper detects the file's current line ending (CRLF if the original contains `\r\n`) and final-newline state, converts, writes a temp file in the same folder, `os.replace`. UTF-8.
- `add_task_ids(path: str, text: str) -> tuple[str, int]`: uses `parse_milestone` to find tasks with `stable_id = False` (their `source_line`), so code blocks are never touched; numbers them after the highest stable number in that file, in document order; inserts `**M17.n** ` right after the `[ ] ` / `[x] ` marker on that exact line, nothing else changes. Returns the new text and the count. Idempotent (a second run changes nothing).

## 5. Service and CLI

Services (CLI imports only these): `service/indexing.py` (`sync(settings, *, reset)`, `doctor(settings)`), `service/status.py` (`status(settings)`), `service/task_ids.py` (`plan_ids(settings, milestone)`, `write_ids(settings, plan)`). Each returns plain dicts for `--json`.

- **`sdd sync [--reset] [--yes]`**: open the store writable (`daemon_running` if another process holds it; that is all the daemon detection M01b has — M02.5 adds the rest), `schema.ensure`, optionally `reset` (asks unless `--yes`; with `--json` and no `--yes` → `invalid_input`), `full_sync`, close (checkpoints). Prints counts, warnings (one line each: `path:line severity code message`), unresolved total. Exit 0 (warnings do not fail sync). `--store :memory:` works and writes nothing.
- **`sdd doctor`**: `analyse(settings)` only; it reads the Markdown and **never opens the store** (write that into the SPEC-08 §2 row). Prints every warning grouped by file, every unresolved link (`node: strings`), and counts: specs, sections, milestones, tasks, deviations, legacy task lines (`stable_id = false`), unresolved links, warnings by severity. Exit 1 if any `error`.
- **`sdd status`**: `--store :memory:` → run `full_sync` into the throwaway store first; otherwise open the store read-only (`invalid_input` "run `sdd sync`" if missing). Reads: milestones by `order` with every task (`[x]/[ ]`, ID, title, status, `claimed_by`), claims, unresolved per node, warning counts (from `analyse`), `writeback` off note, "unticked tasks with COMPLETES commits" (query returns nothing until M04a; keep the query). Human output: plain text; JSON: `{milestones:[{id,title,status,order,done,total,tasks:[…]}], claims, unresolved, warnings, unticked_completed, writeback}`.
- **`sdd ids --write [--milestone M17] [--yes]`**: for each milestone file (or the one given; unknown → `milestone_not_found`), `add_task_ids`; print a unified diff; ask unless `--yes` (`--json` without `--yes` → `invalid_input`); write with `atomic_write`. Without `--write` it only prints the diff. Does not sync.
- Exit codes come from the existing `EXIT_CODES` map; reuse `resolve()`/`fail()`/`emit()`.

## 6. This repo's config
Commit `.sdd/config.toml` with `docs = ["CLAUDE.md", "docs/IDEA.md", "docs/design-system.md", "HANDOFF.md", "README.md"]`, so the fixture repos' `tests/fixtures/*/CLAUDE.md` are not Docs of this project. Make sure `/.sdd/graph/` stays ignored and `config.toml` is not.

## 7. Tests (SPEC-10 §1 naming; real stores, never mocked; fixtures copied with the `project` fixture)

Shared helper `tests/graph_dump.py`: `dump(store, *, exclude=…) -> (nodes: dict[id, (label, props)], rels: Counter[(type, from, to, frozenset(props))])`, used for equivalence checks. A `sync_project(path, store, clock=…)` helper builds `Settings` via `config.load(path, …, clock=…)` and runs `full_sync`.

| File | Tests |
|---|---|
| `tests/spec03/test_sync_fixtures.py` | `test_spec03_ac01_…` (rag fixture: zero `error`; M02's READS in the graph to exactly the listed targets), `ac02` (suite: M17 `done`, `done_date`, RAISED_IN from D021 in the graph), `ac03` (grammar results land as relationships for the fixture lines that use them), `ac04`, `ac05` (stable vs legacy task nodes, BLOCKED_BY in the graph), `ac06` (AMENDS D018 → section in the graph) — graph side only |
| `tests/spec02/test_upsert.py` | `test_spec02_ac02_resync_idempotent` (counts equal and `dump` equal minus `last_synced`), `ac03` (remove one link, re-sync → exactly that LINKS_TO gone), `ac04` (missing section → `unresolved`, no rel), `ac05` (File nodes: only `id,path,name,content_hash,last_synced`); `merge_props` / `task_status` unit tests for every row of SPEC-04 §2.1; `REL_TYPES` matches SPEC-02 §4 |
| `tests/spec04/test_sync.py` | `test_spec04_ac02_unchanged_resync_writes_nothing` (no `changed_at` or `last_synced` moves, no Events, no node/rel count change), `ac03` (move a milestone to `done/` with an active claim set by a test write: `claimed_by` on a task + an `Agent` node + a `CLAIMED {src:'tool'}` rel → all kept; only `path`/`source_path` change), `ac04` (delete a spec: Spec, Sections, checks gone; READS/GOVERNED_BY gone; the referring milestone's `unresolved` lists them), `ac05` (add a spec a milestone already links to → resolved in the same batch, `unresolved` cleared), `ac11` (fresh store: links to a later spec and a `Blocks:` to a later milestone resolve; zero Events; no `changed_at`/`done_at`; a pre-ticked task is `done` with `done_at` null). Plus: edit a section after the initial sync → only that section gets `changed_at` + one `section_changed` Event; a hand tick → `done_at`, claim cleared, `task_completed` actor `human`; untick → `done_at`/`completed_by` cleared, `notes` kept; duplicate ID across two files → `duplicate_id` warning, first path wins |
| `tests/spec08/test_cli_sync.py` | `test_spec08_ac03_ids_write_suite_fixture` (every legacy task gets an ID, existing IDs unchanged, a re-sync shows zero `task_unstable_id`; CRLF file stays CRLF); CLI smoke for `sync`, `status`, `doctor` with `--store :memory:` and `--json`; `doctor` exits 1 on an `error` warning (fixture copy with a bad file name), 0 otherwise; `sync --reset --yes`; `sync --json --reset` without `--yes` → exit 2 |
| `tests/invariants/test_inv02_rebuild.py` | sync `tool_style` and `suite_style`, edit a section, hand-tick a task, add a claim + Agent + Event + a `src:'tool'` TOUCHES (needs a File node: use an SDD doc's File node) by test writes, re-sync; then `sdd sync --reset --yes` through the service; `dump` equal **excluding** Agent/Event nodes, `CLAIMED`/`ABOUT`/`src='tool'` rels, Task graph-only props, `last_synced`, `changed_at`, `Meta.last_full_sync`, and `status` of tasks that were claimed (+ their milestone's `status`). Write this exclusion list into SPEC-10 §4 invariant 2 |
| `tests/invariants/test_inv03_graph_only.py` | Upserts change graph-only Task props only per SPEC-04 §2.1 (drive each case: re-sync unchanged, edit title, tick, untick, move file) and never delete a `src='tool'` relationship |

## 8. Gates and walkthrough (acceptance 2)
- Full gates in the dev container: `uv run pytest -q`, `ruff check`, `ruff format --check`, `mypy src/sdd`, `lint-imports`.
- `sdd doctor --project /refs/office-rag --store :memory:` and `--project /refs/office-suite`: zero `error`. Record **counts only** (specs, sections, milestones, tasks, deviations, legacy task lines, unresolved links) — never names or text from private-repo-app (O1). The `/refs` mounts are read-only; never write there (doctor does not write anyway).
- `sdd sync` on this repo (`--project /workspace`): zero warnings. If our own docs warn, fix the docs (or the parser if it is a parser bug, with a test). `sdd status` lists M00a … M99 with their tasks.
- Do **not** tick boxes or move the milestone file; the Opus review does that.

## 9. Deviations decided in this plan (write them in the same change)
- **D002 — `sdd sync --reset` empties the store in place.** SPEC-08 §2 says "deletes the store first". Implementation: open the store writable (which fails with `daemon_running` if another process holds it) and `DETACH DELETE` every node in one job, then sync. Why: deleting a directory a daemon may hold open is unsafe on Linux (the daemon keeps writing to unlinked files), and an in-place empty is equivalent for every reader. Spec note in SPEC-08 §2 `sync` row.
- **D003 — Re-link trigger widened to the whole link catalog.** SPEC-04 §2 step 3 re-parses everything only when the set of SDD document IDs changes. Implementation re-links every file when anything links resolve against changes (node IDs incl. sections and tasks, section anchors, title slugs, document paths, doc stems). Why: a renamed section or a new task would otherwise leave links in unchanged files unresolved until those files are edited, and the cost is one extra phase 2 per file only in those batches. Spec note in SPEC-04 §2 step 3.

Spec clarifications (spec silent or inconsistent, not deviations; edit the spec text in the same change and list them in the report): `duplicate_id` in the SPEC-03 §1 table; `File` as a `LINKS_TO` target in SPEC-02 §4; where `unresolved` is recorded (SPEC-02 §5); `ABOUT` from sync Events carries `src = "tool"` (SPEC-02 §4); `doctor` reads Markdown only (SPEC-08 §2); invariant 2's exclusion list (SPEC-10 §4).

## 10. Commits
The builder does **not** commit. After the Opus review, the change goes in as `feat: graph upsert and full sync [M01b]` when the user asks. Never push.
