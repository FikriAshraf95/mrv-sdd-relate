# SPEC-06 — Code context: impact, explain, find_code

> **Status:** v1 (2026-11-21) · **Owner of:** target resolution, the traversal rules and output shape of `impact`, `explain` and `find_code`
> Shapes: [SPEC-02 §3–4](SPEC-02-graph-schema.md#3-codebase-layer) · Exposed as MCP tools ([SPEC-05 §2](SPEC-05-agent-tools.md#2-tool-index)), HTTP ([SPEC-07](SPEC-07-dashboard-and-api.md)), CLI ([SPEC-08](SPEC-08-cli-and-exports.md))

## 1. Rules

1. These are the queries that need a graph: multi-hop, mixed-type and explained. **Every returned item carries `via`**, the chain of relationships that connects it to the target, so a person or agent can see why it is there.
2. Traversals are fixed per target kind (no free path expansion), bounded by `depth` (default 3) and by 50 items per group (`counts` gives the full numbers).
3. Every traversal is a named query in `src/sdd/graph/queries/*.cypher`, loaded by `graph/queries.py` ([SPEC-01 §2](SPEC-01-architecture.md#2-repo-layout)), so the static demo can run the same files ([SPEC-11 §6](SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)). `service/impact.py` calls them by name and assembles groups and `via` chains; it holds no Cypher of its own. Results are sorted by group, then by relevance (fewer hops first), then by ID.

## 2. `impact`

`impact(target, depth=3)`: if this changes, what else is affected?

**Target resolution** (after `ids.normalise`), in two steps:
1. **Unambiguous forms** resolve directly, by their format: a spec reference → Section or Spec; a task or milestone ID; a prefixed ID (`table:x`, `column:t.c`, `file:p`, `feature:s`, `domain:s`).
2. **Bare names** are looked up in every kind at once: table name, `table.column`, existing file path, feature name or slug, section title slug. Exactly one match resolves. More than one (a table and a feature both called `attachments`; a column name shared by two tables) returns `ambiguous_target` with the candidates as prefixed IDs, so the caller can repeat with one of them. None is `node_not_found`.

**Traversals:**

| Target | Follows |
|---|---|
| Table | its Columns · Columns elsewhere that `REFERENCES` it (dependent tables) · the defining Section and its Spec · Sections, Tasks and Deviations that `MENTIONS` it or `LINKS_TO` the defining section · Features that `USES_TABLE` it → their Files and Specs · Tasks `GOVERNED_BY` those sections · Deviations that `AMENDS` those sections or `AFFECTS` the table · Tests of the defining spec's checks |
| Column | as Table, starting from its table, plus Columns that reference the same table |
| Section | child Sections · Sections that `LINKS_TO` it · Milestones that `READS` it · Tasks `GOVERNED_BY` it, open and done · Deviations that `AMENDS` it · Tables it defines or mentions · Features of its Spec → Files · Checks of its Spec → test Files |
| Spec | as Section, for every section of the spec |
| File | Features `IMPLEMENTED_IN` it → their Specs · Sections and Tasks that `MENTIONS` it · Tasks that `TOUCHES` it · the 10 latest Commits that `CHANGED` it → the Tasks they `COMPLETES` · Deviations that `AFFECTS` it or amend its features' specs · Checks it `TESTS` |
| Feature | its Files, Tables, Specs, Domain, and the Section traversal over its Specs |

**Output:**

```json
{
  "target": {"id": "table:attachments", "label": "Table"},
  "groups": {
    "specs": [], "sections": [], "tables": [], "features": [], "files": [],
    "tasks_open": [], "tasks_done": [], "deviations": [], "tests": [], "commits": []
  },
  "counts": {"files": 37},
  "synced_at": "…"
}
```

Each item: `{id, label, title, via: ["table:attachments", "<-DEFINES_TABLE", "SPEC-02#attachments", "<-LINKS_TO", "SPEC-18#2"]}`. `via` uses `->TYPE` and `<-TYPE` for direction.

## 3. `explain`

`explain(path)`: why does this file exist, and what shaped it?

Returns, for one File:
- `features` (via `IMPLEMENTED_IN`) with their `domain`, and the `specs` that specify them;
- `sections` and `tasks` that `MENTIONS` it;
- `tasks` that `TOUCHES` it, with their milestone and completion notes;
- `commits`: the 10 latest that changed it, with the tasks they complete;
- `deviations` that `AFFECTS` it or amend its specs, open first;
- `checks` it `TESTS` (for test files) and the specs those checks belong to;
- `summary`: a short generated paragraph from a template, e.g. `"src/billing/invoice.py implements feature Billing (payments), specified by SPEC-04. Built by M03.2 and M03.5 (commits a1b2c3d, d4e5f6a). Shaped by D007 (open): invoices keep a currency column."`

A file with no connections returns empty groups and a summary saying so, which is itself useful (orphan code).

## 4. `find_code`

`find_code(feature?, domain?, table?, spec?, text?)`: at least one argument; several are intersected.
- `feature` / `domain`: Files via `IMPLEMENTED_IN` (domain through its features).
- `table`: Files of features that use it, plus Files that `MENTIONS` it from Markdown and files whose path contains the table name in a migrations or models folder.
- `spec`: Files of the spec's features, plus Files that `MENTIONS`-linked sections name.
- `text`: case-insensitive substring of `File.path` (a full-text index on paths if Relate has one, open item O6).

Returns `{files: [{path, language, via}], counts}`.

## 5. Presets

Named queries used by the dashboard, `sdd export --mermaid <preset>` and the README:

| Preset | Shows |
|---|---|
| `schema` | Labels and relationship types with counts (the meta-graph) |
| `milestone:<id>` | The milestone, its tasks, READS sections, and deviations raised in it |
| `impact:<target>` | The `impact` result as a graph |
| `explain:<path>` | The `explain` result as a graph |
| `lineage:<section>` | Deviations amending the section → the tasks they were raised in → the files those tasks touched |
| `feature:<slug>` | Feature → specs, files, tables |

## 6. Acceptance checks

1. On the fixture project, `impact("documents")` returns the defining section, the chunks table (it references documents), the feature that uses it and its files, the tasks mentioning it, and the deviation amending its section, each with a correct `via`.
2. `impact("SPEC-03 §5.2")` returns the milestone that reads it, the tasks governed by it (open and done), and the deviation that amends it.
3. `explain` on a file implemented by a feature and touched by a completed task returns the feature, spec, task, commit and summary.
4. `explain` on an unconnected file returns empty groups and an orphan summary.
5. `find_code(table="documents", feature="ingestion")` returns the intersection.
6. An ambiguous target returns `ambiguous_target` with candidates.
7. Group limits: a target with 120 files returns 50 items and `counts.files = 120`.
