# M04b implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-06](../../specs/SPEC-06-code-context.md) (whole file), [SPEC-03 §3.2, §3.3, §5.1, §6](../../specs/SPEC-03-markdown-parsing.md#33-feature-line), [SPEC-02 §3–4](../../specs/SPEC-02-graph-schema.md#3-codebase-layer), [SPEC-04 §4](../../specs/SPEC-04-sync.md#4-code-walker), [SPEC-05 §4](../../specs/SPEC-05-agent-tools.md#4-get_context). Milestone: [M04b](M04b-schema-features-impact.md). Previous plan: [M04a-plan](M04a-plan.md).
Follow `CLAUDE.md`. D005 is the highest deviation. This plan expects **one deviation to be resolved (D004) and no new one**. Each decision below fills a gap the spec leaves open, and goes into the owning spec in the same change (§10). If you knowingly depart from a spec anyway, call `log_deviation` (D006…).

## 0. Scope and boundaries

- **In:** `parse/schema_tables.py`; Feature/Domain nodes from the existing `FeatureLine`s; mention and Affects resolution against Tables and every File; Feature glob expansion (`IMPLEMENTED_IN`); `graph/queries.py` + `graph/queries/*.cypher`; `service/impact.py` (impact, explain, find_code, presets); MCP tools 11–13; endpoints 9–11 and 13; CLI `impact`, `explain`, `find`; `get_context`'s code part on real data; doctor counts for tables; tests; spec edits; resolving D004.
- **Not in:** dashboard views (M05b), `sdd export --mermaid` (M06a), the static/WASM demo (M08).
- **Layering:** Cypher only in `graph/` and `service/`. **`service/impact.py` holds no Cypher at all** (SPEC-06 §1 rule 3): it calls named queries through `graph/queries.py`. Parsers stay pure. Only `store.py` imports `relate`. No new dependencies.
- **Probe the engine first (10 minutes, in-memory store, a throwaway script in the container, not committed):** list literals mixing strings and properties in `RETURN` (`[$id, '<-REFERENCES', c.id] AS via`), `coalesce`, `labels(n)[0]`, `toLower`, `CONTAINS`, `ENDS WITH`, `IN $list`, `ORDER BY … LIMIT`, untyped source nodes `(n)-[:MENTIONS]->(t:Table)`. If list literals do not work, return the node IDs and build `via` from a per-query template in Python. Note the outcome in the M04b.4 completion notes.

## 1. Schema tables (M04b.1)

`parse/schema_tables.py`, pure: `parse_tables(path, spec_id, toks, lines, sections) -> (nodes, rels)`, where `sections` is the spec parser's `(section_id, title, tok_index, next_heading_tok_index)` list. `parse_spec(path, text, *, schema: bool = False)` calls it only when `schema` is true.

- **Which specs:** the indexer passes `schema=True` when the path matches the `schema_specs` globs. Add `Classifier.is_schema(rel)`. `analyse()` builds one `Classifier(settings)` for it. The parse cache stays keyed by path; the flag is a function of the path.
- **Table section:** a Section whose `title` (already without its number), minus a trailing parenthetical (`\s*\([^)]*(\([^)]*\))?[^)]*\)\s*$`, which covers `([SPEC-18](../…))`), minus surrounding backticks, matches `^[A-Za-z_][A-Za-z0-9_]*$`. Between its heading and the **next heading of any level**, the first `table_open` token whose first header cell (text, backticks stripped, case-insensitive) is `Column`. Use the markdown-it tokens (`md.py` already enables `table`), so tables in code fences are ignored. `## 7. Table → milestone map` and `## 2. Files ([SPEC-18](../…))` (no Column table before `### attachments`) are not table sections.
- **Columns:** a header map by cell name (case-insensitive): `column`, `type`, and `rules` or `notes` (whichever exists; the third column otherwise). Per body row:
  - names: the first cell split on `,`, each stripped of spaces and backticks, kept when it matches the identifier regex (so `` `created_at`, `updated_at` `` gives two columns);
  - `flags_text` = Type cell + " " + Rules/Notes cell. `nullable`: `\bnot\s+null\b` (case-insensitive) → `False`, else `\bnull\b` → `True`, else omitted. `pk`: `\bPK\b` → `True`, else `False`;
  - `type`: the Type cell without backticks and without the words `not null` / `null`, whitespace collapsed (`text not null` → `text`); omitted if empty;
  - `notes`: the Rules/Notes cell text, omitted if empty;
  - references: every `(?:FK\s*)?→\s*`?([A-Za-z_][A-Za-z0-9_]*)` in `flags_text` → `REFERENCES` from the column to `table:<name>`.
- **IDs and nodes:** `table:<name>` with `{name, defined_in: <section id>, source_path, source_line}`; `column:<table>.<name>` with `{table, name, type, nullable, pk, notes, source_path, source_line}`. Build IDs with `ids.normalise` and skip a name it rejects. A column repeated in one table: keep the first.
- **Rels** (`Ref("id", …)` so the normal resolver handles them; a missing target table is `unresolved` on the Column): `DEFINES_TABLE` section → table, `HAS_COLUMN` table → column, `REFERENCES` column → table.
- A table defined in two schema specs is a plain `duplicate_id` (the first by path wins), as today.
- **Catalog:** add `"Table"` to `upsert.CATALOG_LABELS`, so a table that appears or disappears re-links every file (D003's fingerprint). `Column` does not need it.
- **Doctor:** `indexing.doctor`'s `counts` gains `tables`, `columns`, `references` (resolved REFERENCES). The text line prints them after `deviations`. Update SPEC-08's `sdd doctor` row to say the counts include tables, columns and references.

## 2. Features (M04b.2)

`parse_spec` already returns `result.features` (`FeatureLine`). It now also emits, for each feature line:
- `Node("Feature", "feature:<slug>", {name, slug, globs: list(implements)})` and, when there is a domain, `Node("Domain", "domain:<domain_slug>", {name, slug})`. **No `source_path` on either** (see below).
- Rels: `SPECIFIED_BY` feature → spec, `BELONGS_TO` feature → domain, `USES_TABLE` feature → `Ref("id", "table:<t>")` per table (normalised; a missing table goes to `unresolved`).

**Shared nodes.** A feature declared in two specs is one node with two `SPECIFIED_BY`, and a domain is normally shared by many specs. The per-file node ownership (`source_path`, first-by-path, `delete_file`) does not fit, so:
- `indexer._analyse_files` takes every `Feature`/`Domain` node out of the per-file node lists **before** `_drop_duplicates` (their rels stay with their file). It merges them by ID: the first by path gives `name`/`slug`, and `globs` is the sorted union over every declaration. The result is `Analysis.shared: list[NodeIn]`. Their IDs go into `catalog.ids`, so the rels resolve.
- A new `upsert.sync_shared_nodes(tx, nodes, *, now) -> NodeChanges` reads the stored `Feature` and `Domain` nodes, writes the ones that differ (`MERGE … SET n = props`, with `last_synced`), and `DETACH DELETE`s the ones no spec declares any more. `_apply` runs it in its own job **after phase 1 and removals, before phase 2** (phase 2 needs the endpoints), on every sync, `sync_tx` included. The changed IDs join `changed_ids`. No Events.
- When the owner of an unresolved rel would be a Feature (a `USES_TABLE` to an undefined table), record it on the declaring Spec instead (the file's primary node). `replace_file_rels` clears `unresolved` by `source_path`, so a Feature's list would never be cleared.

**Glob expansion** (`src = walker`), in `sync/files.py` + `graph/code.py`:
- `files.expand_features(store, state_code: CodeCache, result: CodeResult) -> dict[str, int]`: read every Feature's `(id, globs)` (`graph.code.read_features`), match each feature's globs against **every path in the code cache**, read the stored `IMPLEMENTED_IN` (`graph.code.read_implemented`), and for each feature whose wanted file set differs, rewrite it (`graph.code.replace_implemented(tx, feature_id, file_ids)`, `src: 'walker'`). Return `{feature_id: match count}`.
- **Glob semantics:** project-relative gitignore-style patterns, exactly like the config globs: reuse `indexer._spec` (rename it to a public `globspec()`; slash-less patterns are anchored at the root). One pathspec per feature.
- **Pipeline** (replace the `# M04b: feature glob re-expansion here.` hook): run it when `full`, when `code.written or code.removed`, or when any `feature:` ID is in `report.changed_ids`. It is a diff, so a no-op sync writes nothing (SPEC-04 §7 check 2 must still hold).
- **`feature_glob_empty`** (a new `warning` code: add it to `WARNING_CODES` and to the SPEC-03 §1 table, "a Feature's globs match no file; reported by `sync/`"): on every sync that ran the indexer (`report.indexed`), for each spec FeatureLine in the parse cache that has globs, if its feature matched 0 files, append `warn(path, line, "feature_glob_empty", "<name>: <globs> match no file")` to `report.warnings`.

## 3. Mentions and Affects (M04b.3)

The parsers already emit `MENTIONS` (sections, task lines, the whole deviation body) and `AFFECTS` (`strict`) as `Ref("mention", ident)`. Only resolution changes, in `indexer._resolve_file`:
- `ident` resolves to **`table:<ident>`** when that ID is in `catalog.ids`, and to **`file:<ident>`** when `ident` is an existing file path. Both can match; link both.
- "Existing file path" = a File node in the graph (the walker's, so code files and SDD documents), or a tracked SDD path. Add `upsert.read_file_paths(store | tx) -> set[str]` (every `File.path`). `sync` and `sync_tx` pass it in. Code phase 1 runs before the indexer, so new files already have nodes. **`analyse()` without a store (doctor)** uses `(root / p).is_file() and not rules.ignored(p)`. Pass a `file_exists: Callable[[str], bool]` down to `_resolve_file`.
- Non-strict mentions that resolve to nothing are dropped, as today. Strict ones (`AFFECTS`) go to `unresolved`, as today.
- **Code files appearing or disappearing.** A mention of `src/x.py` must follow the file. `indexer.sync(..., code_touched: frozenset[str] = frozenset())`: after analysis, every SDD file with a `mention` rel whose target is in `code_touched` joins phase 2 (relationships only), even if its hash is unchanged. In the pipeline: `code_touched = code.written | code.removed`. Run the indexer when `full`, when the batch has an SDD path (as now), **or** when `indexer.mentions(state.parse)` (a helper: `{target: {sdd paths}}` from the cached parse results) intersects `code_touched`. Replace the `# M04b: pass the code paths into link resolution here.` hook. Write this rule into SPEC-04 §4 (new bullet **Mentions**, see §10).
- **D004 is resolved here.** `log_deviation`'s `affects` check returns to the spec wording (SPEC-05 §5): an entry is valid when it names a File node's path or a Table node's name, otherwise `invalid_input`. Remove the "file exists in the project" fallback (find it in `sync/writeback.py` / `service/coordination.py`). Mark D004 resolved: `**Status:** Resolved (2026-11-22, M04b.3: Table and code File nodes exist, so the spec's rule holds)` in its file, and `Resolved` in its `docs/DEVIATIONS.md` row. Keep the spec note. Update the M03a test that relied on the fallback.

## 4. Named queries (M04b.4, part 1)

- `src/sdd/graph/queries/{resolve,impact,explain,find,presets}.cypher`. Each file holds several queries. Each one starts with a line `// name: <dotted.name>`, and the query runs until the next such line. Parameters only (`$id`, `$ids`, `$path`, `$text`…). No string formatting. Every query is read-only and stays inside the guard's limits (no `CALL`, fixed hops; no variable-length pattern needed).
- `graph/queries.py`: `load() -> dict[str, str]` (parse every `.cypher` file once, through `importlib.resources`; a duplicate name raises), `get(name) -> str`, `run(store: Store, name: str, **params) -> list[Row]` (= `store.read(get(name), params)`).
- **Packaging:** make sure the `.cypher` files ship in the wheel (hatchling includes package data under `src/sdd/` by default; verify with `uv build` + `unzip -l`, or add an explicit include). Add a test that `queries.load()` finds every name `impact.py` uses.
- **Row shape for traversal queries:** `id, label, title, status, via`, where `label = labels(x)[0]`, `title = coalesce(x.title, x.name, x.path, x.message, x.id)`, `status` (Tasks/Deviations, else null) and `via` = a list literal from the target to the item, e.g. `[$id, '<-REFERENCES', c.id, '<-HAS_COLUMN', d.id]`. `->T` / `<-T` follow the stored direction, read from the target.

## 5. impact (M04b.4, part 2)

**Target resolution** (`impact.resolve_target(store, raw) -> (id, label)`; explain uses its own, §6):
1. **Unambiguous forms**, by format: a spec reference (parse it with the existing spec-reference grammar, `ids.normalise`) → Section or Spec; a task or milestone ID; a prefixed ID `table:`, `column:`, `file:`, `feature:`, `domain:`. The node must exist, else `node_not_found`.
2. **Bare names**, looked up in every kind at once: Table `name`; `table.column` → Column; File `path`; Feature `name` (case-insensitive) or `slug`; Column `name` (bare, so a name shared by two tables is ambiguous); Section whose `id_slug(title)` equals `id_slug(raw)`. Exactly one → resolved. Several → `SddError("ambiguous_target", …, details={"candidates": [prefixed IDs / section IDs, sorted]})`. None → `node_not_found`.

**Traversals:** a Python table `TRAVERSALS: dict[str, list[tuple[str, str]]]` = label → `[(query name, group)]`. Data only; each query implements one row piece of the SPEC-06 §2 table. Starting points: **Column** → run Table's list from its table (the via starts at the column: `column:t.c <-HAS_COLUMN table:t …`), plus "Columns that reference the same table". **Spec** → the Section list over every section of the spec (via starts at the spec: `SPEC-02 ->HAS_SECTION SPEC-02#2 …`). **Feature** → its Files, Tables, Specs, Domain, then the Section traversal over its Specs' sections. Add two rows the spec's resolution step already admits but its table lacks (write them into SPEC-06 §2):
- **Task:** its Milestone; `GOVERNED_BY` sections; `BLOCKED_BY` both ways; Files it `TOUCHES`; Commits that `COMPLETES` it; Deviations `RAISED_IN` it.
- **Milestone:** Tasks it `INCLUDES` (open/done); `READS` sections and specs; `DEPENDS_ON` both ways; Deviations `RAISED_IN` it; Commits `PART_OF` it.

**Groups:** `specs, sections, milestones, tables, features, files, tasks_open, tasks_done, deviations, tests, commits`. **Add `milestones` to the SPEC-06 §2 output**: the Section traversal returns Milestones, and checks 2 and the walkthrough need them. Placement rules: Column items go in `tables`; Domain items in `features`; AcceptanceChecks and test Files reached through `TESTS` in `tests`; Tasks by `status == "done"` into `tasks_done`, else `tasks_open`. Every group is always present (empty list).

**Assembly** (`impact.impact(runtime, target, depth=3, agent=None)`):
- `hops(via)` = the number of relationships in the chain **not counting containment** (`HAS_SECTION`, `HAS_CHECK`, `HAS_COLUMN`). A section's spec is one `<-HAS_SECTION` step even when the section is nested (match it by `spec_id`). Drop items with `hops > depth`. `depth` must be 1–5 (else `invalid_input`). Write both rules into SPEC-06 §1 rule 2.
- The target itself is never an item. A node reached by several chains keeps the one with the fewest hops (ties: the first in traversal order). Within a group, sort by hops, then `id`. `counts[group]` = the full number before the 50-item cap, for **every** group. Then cap each group at 50.
- Item: `{id, label, title, via}` plus `status` for tasks and deviations. Result: `{target: {id, label, title}, groups, counts, synced_at}` (`synced_at` from the store, as other tools do). Call `coordination.seen(...)`/`agent_name` the way the other read tools do for `agent`.

## 6. explain and find_code (M04b.4, part 3)

**explain(path)**: resolve the path: exact `File.path` (after stripping `./` and converting `\` to `/`); else the files whose path ends with `/<input>` (one → it, several → `ambiguous_target` with `file:` candidates); else `file_not_found`. Write this resolution into SPEC-06 §3. Return:
```
{file: {id, path, language, is_test},
 features: [{id, name, domain, specs: [..], via}],
 sections: [{id, title, via}],                       # MENTIONS it
 tasks: [{id, title, status, milestone, notes, via}],# MENTIONS or TOUCHES it; one entry per task, shortest via
 commits: [{sha, short, message, at, tasks: [..], via}],  # 10 latest CHANGED it
 deviations: [{id, title, status, via}],             # AFFECTS it, or AMENDS a section of its features' specs; open first
 checks: [{id, spec_id, text, via}],                 # it TESTS
 summary, synced_at}
```
`summary` from a template, skipping empty parts: `"<path> implements feature <Name> (<domain>), specified by SPEC-02. Built by M02.1 and M02.3 (commits a1b2c3d, d4e5f6a). Shaped by D002 (open): <title>. Tests SPEC-02#ac1."` A file with every group empty: `"<path> has no recorded connections: no feature, spec, task, commit, deviation or check names it (orphan code)."`

**find_code(feature?, domain?, table?, spec?, text?)**: at least one, else `invalid_input`. Each given argument yields a set of files, each file with the via of its first route. The result is the intersection (via from the first argument, in the order feature, domain, table, spec, text):
- `feature` (slug, name or `feature:` ID): `IMPLEMENTED_IN`. `domain`: its features' files.
- `table`: files of the features that `USES_TABLE` it; **plus the Files named (`MENTIONS`) by the sections, tasks and deviations that mention the table**; plus files whose path has a `migrations` or `models` segment and contains the table name (case-insensitive). Write this reading of "Files that MENTIONS it from Markdown" into SPEC-06 §4.
- `spec` (a spec reference): files of the spec's features, plus Files its sections `MENTIONS`.
- `text`: `toLower(f.path) CONTAINS toLower($text)` (not the full-text index: it needs `CALL`, and substring is what the spec asks).
Result `{files: [{path, language, via}] (sorted by path, max 50), counts: {files: N}, synced_at}`.

**Presets** (`impact.presets()` list, `impact.preset(runtime, name)` graph): list = `[{name, params, description}]` for `schema`, `milestone:<id>`, `impact:<target>`, `explain:<path>`, `lineage:<section>`, `feature:<slug>`. A preset graph has the `/api/graph` shape `{nodes: [{id, label, title, props}], edges: [{source, target, type}]}`. Build it from via chains: every `(a, '<-T', b)` step is an edge `b -T-> a`, every `(a, '->T', b)` is `a -T-> b`. Load the nodes by ID with a named query, and shape them with `api_views`' node shaping (make `_shape` public as `shape_node`). `schema`: one node per label (`id` = the label, `label: "Label"`, `title: "Table (12)"`, `props: {count}`) and one edge per (from label, type, to label) with a `count` field. `milestone:<id>` = the Milestone traversal; `lineage:<section>` = Deviations `AMENDS` the section → the Tasks/Milestones they are `RAISED_IN` → the Files those tasks `TOUCHES`; `feature:<slug>` = feature → specs, files, tables. An unknown preset name is `node_not_found`. Write the list item shape and the schema graph shape into SPEC-06 §5.

## 7. Surfaces (M04b.5)

- **MCP** (`mcp/server.py`): tools `impact(target, depth=3, agent?)`, `explain(path, agent?)`, `find_code(feature?, domain?, table?, spec?, text?, agent?)` with docstrings in the style of the others; add them to `TOOLS`; update the module docstring ("Tools 11–13 arrive in M04b").
- **HTTP** (`web/api.py`): `GET /api/impact?target=&depth=`, `GET /api/explain?path=`, `GET /api/find?feature=&domain=&table=&spec=&text=`, `GET /api/presets`, `GET /api/presets/{name:path}` (percent-encoded). All public-safe reads (they must also be registered in whatever public route list exists or will exist; follow how endpoints 7/8 are marked).
- **CLI** (`cli.py` + `service/commands.py`, same daemon-or-snapshot routing as `context`): `sdd impact TARGET [--depth N]`, `sdd explain PATH`, `sdd find [--feature] [--domain] [--table] [--spec] [--text]`. Text output:
  - impact: `table:documents (Table) documents`, then per non-empty group `tables (2)` / `  table:chunks  chunks` / `      via table:documents <-REFERENCES column:chunks.document_id <-HAS_COLUMN table:chunks`, and `  … 50 of 120` when capped.
  - explain: the summary first, then the non-empty groups with their items and via.
  - find: one `path  (language)` line per file, then `N files`.
  - `--json` prints the result as is.
- Remove `impact`, `explain`, `find_code`, `find` from `PENDING_*` in `tests/invariants/test_inv06_drift.py`. Add the `sdd find` options to the SPEC-08 §2 row. Endpoint 13 in SPEC-07 §2 gets the list item shape.

## 8. get_context code part (M04b.6)

`service/context.py::_code` already queries Features, `IMPLEMENTED_IN`, `MENTIONS → Table` and commits. With real data:
- delete the `_feature` test helper in `tests/spec05/test_context.py` (sync now creates `feature:brewing`, so its `CREATE` would break the uniqueness constraint) and assert on the synced data: `M01.1`'s packet has `features == ["brewing"]`, `files` contains `src/kettle/brew.py`, and with `TOOL_STYLE_HISTORY` `recent_commits` holds `feat: brew model [M01.1]`;
- `M02.1` (mentions `` `documents` ``) has `tables == ["documents"]`, features `["ingestion"]`, the `src/ingest/` files;
- check the file cap (50) and the commit cap (5) still apply. Fix whatever the real data shows wrong. Keep the queries where they are (context.py is allowed Cypher; only impact.py is not).

## 9. Tests (M04b.7, M04b.8)

New `tests/spec06/` (and additions in `tests/spec03/`, `tests/spec02/`), named after the checks (SPEC-10 §1):
- `test_spec06_ac01_impact_documents`: tool_style + `TOOL_STYLE_HISTORY`. Expect section `SPEC-02#2`, table `table:chunks` (via `table:documents <-REFERENCES column:chunks.document_id <-HAS_COLUMN table:chunks`), feature `feature:ingestion` and its `src/ingest/*` files, task `M02.1` (`<-MENTIONS`), deviation `D002` (both `<-AFFECTS` and the AMENDS route; the 1-hop AFFECTS wins). Assert the exact `via` lists.
- `test_spec06_ac02_impact_section`: **the fixture has no SPEC-03 §5.2**, so use tool_style `SPEC-02 §2`, which has the same shape (M02 reads it, M02.1 is governed by it, D002 amends it). Tick M02.1 in the copy so both `tasks_open` and `tasks_done` are exercised (make a second task govern it if needed). Say so in the docstring.
- `test_spec06_ac03_explain_feature_file`: `src/ingest/loader.py` → feature ingestion, SPEC-02, task M02.1 (TOUCHES via the `[M02.1]` commit), the commit, D002, and a summary naming them.
- `test_spec06_ac04_explain_orphan`: `src/util/misc.py` → empty groups and the orphan summary. Make sure no commit touches it in `TOOL_STYLE_HISTORY`, or that it is not in the fixture's import commit's changed files. If the import commit makes every file "connected", test without history (the plain `project("tool_style")`) and say so.
- `test_spec06_ac05_find_code_intersection`, `test_spec06_ac06_ambiguous_target` (create a feature and a table with the same name, or a column name shared by `documents.id`/`chunks.id`: `impact("id")` → candidates `column:chunks.id`, `column:documents.id`), `test_spec06_ac07_group_limit` (write 120 files under `src/ingest/gen/` in the copy, sync, `impact("feature:ingestion")` → 50 files, `counts.files == 120 + existing`; assert exactly).
- `test_spec03_ac07_schema_tables` (rag_style `documents` with two columns from one cell, `loans.document_id` REFERENCES; suite_style `attachments`, `uploaded_by` → `users`, `ts` a column, `email` type `text` with `nullable == False`); `test_spec03_ac08_feature_line_graph` (graph side); `test_spec03_ac09_deviation_task_and_affects` (D002: RAISED_IN M02 + M02.1, AFFECTS `file:src/ingest/loader.py` + `table:documents`, all still there after `sdd sync --reset --yes`; a deviation without either field has no warning).
- Plain tests: mention of a code file added later gets its `MENTIONS` in the same batch, and loses it when the file is deleted; Feature declared in two specs = one node, two SPECIFIED_BY, union globs, survives removing one spec; `feature_glob_empty`; glob expansion on file add/remove; an unchanged re-sync writes nothing (extend SPEC-04 check 2's test if needed); impact depth cut; named queries load; MCP smoke for the three tools; HTTP endpoints 9–11 and 13 (including percent-encoded preset names); CLI text output; log_deviation rejects an Affects entry naming no File/Table (D004 resolved).
- **M04b.8:** extend `test_spec01_ac02_…` (through the daemon: `sdd impact documents` hits `GET /api/impact`) and `test_spec01_ac03_…` (without a daemon: `sdd impact documents` from a read-only snapshot, no file created). Rename them to describe the new content only if the check-number prefix stays.
- Counts and unresolved lists in existing tool_style tests will change (tables, features, `table:brews`/`table:teas` unresolved on SPEC-01). Update them to the new correct values; **never weaken an assertion**.

## 10. Spec edits (same change as the code)

- **SPEC-02 §3:** Feature props `name`, `slug`, `globs` (list); Table/Column carry `source_path`, `source_line`; a note that Feature and Domain nodes have no `source_path`, are written from every spec's Feature lines after phase 1, and are deleted when no spec declares them.
- **SPEC-03 §1:** the `feature_glob_empty` row. **§3.3:** globs are project-relative gitignore-style patterns like the config globs; a feature declared twice gets the union of its globs; an unresolved `USES_TABLE` is listed on the Spec. **§6:** the Type cell loses `null`/`not null` for `type`; the header cells are matched by name; a table section's table must come before the next heading of any level.
- **SPEC-04 §4:** new bullet **Mentions**: when a sync adds or removes a file that an SDD document mentions or names in Affects, that document's relationships are rebuilt (phase 2 only) in the same sync. The Feature-globs bullet gains "or when a Feature's globs changed", plus where `feature_glob_empty` is reported.
- **SPEC-06 §1** rule 2 (depth counting, containment hops, shortest chain wins); **§2** (Task and Milestone rows, `milestones` group, placement rules, counts for every group); **§3** (path resolution, output shape); **§4** (the `table` reading, `text` without the full-text index); **§5** (list item and schema graph shapes).
- **SPEC-07 §2** endpoint 13 shape. **SPEC-08 §2** `sdd find` options and doctor counts.
- **D004** resolved (§3).

## 11. Order and handoff

Work M04b.1 → .2 → .3 → .4 → .5 → .6 → .7 → .8, through the sdd tools as `sonnet-1`: `claim_task` → `get_context` → build + tests → `log_deviation` if needed → `complete_task(notes, files_touched)` **without `commit`**. **Do not commit**; Opus reviews, runs the gates, commits with every task ID. Run the full gates before reporting:
`docker compose -f docker-compose.dev.yml exec dev sh -c "uv run ruff check . && uv run ruff format --check . && uv run mypy src/sdd && uv run lint-imports && uv run pytest -q"`.
If the same test fails twice for a reason you do not understand, or a design question comes up that this plan does not answer, stop and report rather than guess.
