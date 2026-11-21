# SPEC-02 — Graph schema

> **Status:** v1 (2026-11-21) · **Owner of:** every node label, property, relationship type, ID format and index
> Parsing rules that fill these: [SPEC-03](SPEC-03-markdown-parsing.md) · Sync rules: [SPEC-04](SPEC-04-sync.md)

This spec is the **single source of truth for graph shapes**. Other specs link here instead of repeating properties.

## 1. IDs and common properties

| Label | `id` format | Example |
|---|---|---|
| Spec | `SPEC-NN` from the file name | `SPEC-03` |
| Section | `<spec>#<number>` if numbered, else `<spec>#<slug>` (deduped with `-2`, `-3`; this ID slug is ours, the GitHub `anchor` property is separate) | `SPEC-03#5.2`, `SPEC-02#attachments` |
| AcceptanceCheck | `<spec>#ac<n>` | `SPEC-03#ac6` |
| Milestone | `M<digits>[a-z]?` from the file name | `M02`, `M20f`, `M100` |
| Task | `<milestone>.<n>` from the inline ID | `M02.3`, `M20f.12` |
| Deviation | `D<nnn>` | `D012` |
| Doc | `doc:<path>` | `doc:docs/IDEA.md`, `doc:CLAUDE.md` |
| Folder / File | `dir:<path>` / `file:<path>` | `file:src/sdd/cli.py` |
| Commit | `commit:<full sha>` | |
| Table / Column | `table:<name>` / `column:<table>.<name>` | `column:attachments.owner_id` |
| Feature / Domain | `feature:<slug>` / `domain:<slug>` | `feature:file-sharing` |
| Agent | `agent:<name>` | `agent:sonnet-2` |
| Event | `event:<ulid>` | |
| Meta | `meta` (one node) | |

`ids.normalise()` accepts the forms people type: `SPEC-03 §5.2`, `SPEC-03§5.2`, `spec-03#5.2`, `SPEC-3 5.2`, `m2.3`. Rules: prefixes are upper-cased (`SPEC`, `M`, `D`) and milestone letter suffixes lower-cased; spec and milestone numbers are zero-padded to at least 2 digits (`SPEC-3` → `SPEC-03`, `m2.3` → `M02.3`, `M100` stays), deviation numbers to 3 (`d12` → `D012`); `§`, `#` or a space separates a spec from its section number, with or without spaces around `§` and `#` (`SPEC-03§5.2`, `SPEC-03 § 5.2`); a number glued straight to the spec number (`SPEC-035.2`) is rejected as ambiguous. A section slug or acceptance check takes the same separators (`SPEC-02 §attachments`, `SPEC-03 ac6`). IDs taken from file names are padded the same way, so a file `M2-x.md` is `M02`.

**Common properties** on every parsed node: `id` (unique), `source_path`, `source_line` (1-based, where applicable), `content_hash` (sha256 of the parsed text), `last_synced` (UTC ISO). Code-layer nodes have `last_synced` but no `source_line`.

## 2. Planning layer

### Spec
| Property | Type | Rules |
|---|---|---|
| title | string | H1 without the `SPEC-NN —` prefix |
| status | string null | From the header line `**Status:**` |
| owner_of | string null | From `**Owner of:**` (or `**Spec ID:**`-style headers: kept in `header` raw) |
| header | map | Every `**Key:** value` pair of the header blockquote. Stored as a JSON string if Relate has no map properties (open item O10); `store.py` decodes it, so callers always see a map |

### Section
| Property | Type | Rules |
|---|---|---|
| spec_id | string | |
| number | string null | `5.2`; null for unnumbered headings |
| title | string | Heading text without the number |
| anchor | string | GitHub anchor (`#52-chunking`), used for links back to the file |
| level | int | 2–4 (H1 is the spec) |
| line_start, line_end | int | Inclusive range in the file |
| text | string | Body up to the next heading of the same or higher level, without child sections. A *reference* to a section always means the section **and its descendants** ([SPEC-03 §2.2](SPEC-03-markdown-parsing.md#22-spec-reference-grammar)); readers join the subtree's `text` in document order |
| changed_at | string null | Last time `content_hash` changed. Null for sections created by the store's initial sync or with a new spec; set when a section is added to an existing spec or its hash changes ([SPEC-04 §2](SPEC-04-sync.md#2-incremental-sync)) |

### AcceptanceCheck
`spec_id`, `number` (int), `text`.

### Milestone
| Property | Type | Rules |
|---|---|---|
| title | string | H1 without `M02 —` |
| order | string | Sort key: zero-padded number + suffix (`0002`, `0020f`, `0100`) |
| status | string | `todo` \| `in_progress` \| `done` (derived, [SPEC-03 §4.4](SPEC-03-markdown-parsing.md#44-status)) |
| status_text | string null | The raw `**Status:**` paragraph |
| done_date | string null | From `DONE (YYYY-MM-DD)` |
| model | string null | From `**Model:**` |
| goal | string | The *Goal* section text |
| acceptance | list<string> | Numbered acceptance criteria |
| path | string | Current path (moves to `done/` keep the same ID) |

### Task
| Property | Type | Rules |
|---|---|---|
| milestone_id | string | |
| title | string | The line text without the ID and markers, links rendered as text |
| group | string null | The `###` heading above it (`Backend`, `Tests`) |
| order | int | Position in the milestone |
| checked | bool | The Markdown checkbox (`[x]` / `[X]`). The only status input that comes from Markdown |
| status | string | `todo` \| `claimed` \| `done`, **derived, never parsed**: `done` if `checked` (or, with `writeback = false`, if `completed_by` is set); else `claimed` if `claimed_by` is set; else `todo`. Recomputed by every upsert and every write job that touches the task |
| stable_id | bool | False when the ID was derived from position ([SPEC-03 §4.2](SPEC-03-markdown-parsing.md#42-task-ids)) |
| claimed_by, claimed_at | string null | Graph-only |
| completed_by | string null | Graph-only. Agent that called `complete_task` |
| done_at, notes | string null | Graph-only. Set by `complete_task`; `done_at` is also set when a box is ticked by hand after the initial sync. The upsert rules are in [SPEC-04 §2.1](SPEC-04-sync.md#21-task-upsert-rules) |

### Deviation
| Property | Type | Rules |
|---|---|---|
| title | string | |
| date | string null | |
| status | string | `open` \| `resolved` (from `Open` / `Resolved → spec updated`; a status with extra text after `Open` is `open`) |
| status_text | string | Raw status |
| spec_says, implementation_does, why, consequences | string | The four template sections |

### Doc
`kind` (`idea`, `claude_md`, `plan`, `design_system`, `handoff`, `readme`, `other`), `title`, `path`. Plan files (`M20f-plan.md`) are Docs with `kind = plan`.

### Meta
One node, `id = "meta"`: `schema_version` (int, starts at 1), `last_git_sha`, `last_full_sync`, `project_name`.

### Agent, Event (graph-only)
- **Agent**: `name`, `first_seen`, `last_seen` (any tool call with `agent`; decides stale claims, [SPEC-05 §3](SPEC-05-agent-tools.md#3-claims)), `last_changes_at` (time of this agent's last `what_changed` call; defines `since="last_session"`, [SPEC-05 §7](SPEC-05-agent-tools.md#7-what_changed)).
- **Event**: `at`, `kind` (`task_claimed`, `task_released`, `task_completed`, `deviation_logged`, `section_changed`, `spec_added`, `spec_removed`, `milestone_done`, `sync`), `actor` (agent name or `human` or `sync`), `target_id`, `summary`, `data` (map: completion notes, files touched, commit; a JSON string if O10 says no maps). Append-only.

### Graph-only state (canonical list)
Everything below is lost by `sdd sync --reset` and is excluded from rebuild equivalence ([SPEC-10 §4](SPEC-10-testing-and-benchmark.md#4-invariant-suite) invariant 2). Everything else must be reproducible from Markdown, code and git.
- Nodes: Agent, Event.
- Task properties: `claimed_by`, `claimed_at`, `completed_by`, `done_at`, `notes`.
- Relationships: `CLAIMED`, `ABOUT`, and every relationship with `src = "tool"` (§4): `TOUCHES` from `files_touched`, `COMPLETES` from `complete_task(commit=…)`.

`RAISED_IN` → Task and `AFFECTS` are **not** graph-only: `log_deviation` writes them into the deviation file, so a rebuild reproduces them ([DEC-002](../decisions/DEC-002-graph-only-links.md)).

## 3. Codebase layer

| Label | Properties |
|---|---|
| Folder | `path`, `name` |
| File | `path`, `name`, `language` (by extension), `size`, `lines`, `content_hash`, `is_test` |
| Commit | `sha`, `short`, `message` (first line), `author`, `at`, `paths` (list, every path in the diff including deleted ones) |
| Table | `name`, `defined_in` (section id) |
| Column | `table`, `name`, `type`, `nullable` (bool), `pk` (bool), `notes` |
| Feature | `name`, `slug` |
| Domain | `name`, `slug` |

File contents are **never** stored. The graph holds connections and intent; agents still read and grep files.

## 4. Relationships

| Type | From → To | Source |
|---|---|---|
| `HAS_SECTION` | Spec → Section, Section → Section (nesting) | headings |
| `HAS_CHECK` | Spec → AcceptanceCheck | *Acceptance checks* section |
| `LINKS_TO` | Section → Section \| Spec \| Milestone \| Deviation \| Doc | Markdown links in section text |
| `DEPENDS_ON` | Milestone → Milestone | *Depends on* (and reversed *Blocks*) |
| `READS` | Milestone → Section \| Spec | *Read first* line; `{whole: true}` on Spec targets marked "(whole file)" |
| `INCLUDES` | Milestone → Task | checkboxes |
| `BLOCKED_BY` | Task → Task | `(after M02.1)` |
| `GOVERNED_BY` | Task → Section \| Spec | links inside the task line |
| `VERIFIES` | Task → AcceptanceCheck | "SPEC-03 §10 checks 3–9" in the task line |
| `PLANS` | Doc(plan) → Milestone | `M20f-plan.md` |
| `AMENDS` | Deviation → Section \| Spec | the **Spec:** field and every `> **DEVIATION:** see [Dnnn]` note |
| `RAISED_IN` | Deviation → Milestone \| Task | **Date / milestone:** field (milestone, then an optional task ID: `2026-11-25 · M02 · M02.3`) |
| `AFFECTS` | Deviation → File \| Table | the optional **Affects:** field (backticked file paths and table names) |
| `MENTIONS` | Section \| Task \| Deviation → Table \| File | a backticked identifier that exactly matches a table name or an existing file path |
| `CLAIMED` | Agent → Task | graph-only; `{at}` |
| `ABOUT` | Event → any | graph-only |
| `CONTAINS` | Folder → Folder \| File | walker |
| `PARENT` | Commit → Commit | git |
| `CHANGED` | Commit → File | git; `{change: A\|M\|D\|R}`; only to files that still exist |
| `COMPLETES` | Commit → Task | `[M02.3]` in the message, or `complete_task(commit=…)` |
| `PART_OF` | Commit → Milestone | `(M20f)` or `M20f` as a word in the message, when no task ID is present |
| `TOUCHES` | Task → File | `complete_task(files_touched)` and files changed by commits that complete the task |
| `TESTS` | File → AcceptanceCheck | test names matching `spec(\d+)_ac(\d+)` (case-insensitive) in test files |
| `DEFINES_TABLE` | Section → Table | schema tables ([SPEC-03 §6](SPEC-03-markdown-parsing.md#6-schema-tables)) |
| `HAS_COLUMN` | Table → Column | |
| `REFERENCES` | Column → Table | `→ users`, `FK → documents` |
| `SPECIFIED_BY` | Feature → Spec | Feature line |
| `BELONGS_TO` | Feature → Domain | Feature line |
| `IMPLEMENTED_IN` | Feature → File | Feature line globs, re-expanded on file add/remove |
| `USES_TABLE` | Feature → Table | Feature line |

**Every relationship carries `src`**, which says who owns it and who may delete it:

| `src` | Owner | Deleted when |
|---|---|---|
| a project-relative file path | the parser of that file | that file is re-synced (all its relationships are deleted and recreated in one transaction, [SPEC-04 §2](SPEC-04-sync.md#2-incremental-sync)) or removed |
| `walker` | the code walker (`CONTAINS`, `IMPLEMENTED_IN`, `TESTS`) | the walker rebuilds them |
| `git:<sha>` | git sync (`PARENT`, `CHANGED`, `COMPLETES`, `PART_OF`, commit-derived `TOUCHES`) | that commit becomes unreachable ([SPEC-04 §6](SPEC-04-sync.md#6-git-sync)) |
| `tool` | a write tool (graph-only) | never by sync; only by `sdd sync --reset` or `DETACH DELETE` of an endpoint |

The same type may have several owners (`TOUCHES` from a tool and from git); each owner only ever deletes its own.

## 5. Unresolved links

A link whose target does not exist yet (a spec not written, a section renamed) creates no relationship. It is recorded on the source node as `unresolved: list<string>` and reported by `sdd doctor` and `sdd status`.

## 6. Indexes and constraints

- Unique `id` on every label. If Relate lacks uniqueness constraints (open item O6), `store.py` upserts with `MERGE` on `id` only, and `sdd doctor` checks for duplicates.
- Property indexes on `Task.status`, `Task.milestone_id`, `File.path`, `Section.spec_id`, `Event.at` (if supported).
- Full-text (stretch, if supported): `Section.title + text`, `File.path`.

## 7. Label → milestone map

| Labels / relationships | Created in |
|---|---|
| Meta, Spec, Section, AcceptanceCheck, Milestone, Task, Deviation, Doc, every planning relationship | M01b (parsed in M01a) |
| File for SDD documents (`path`, `name`, `content_hash`; incremental sync needs the hash) | M01b |
| Agent, Event, CLAIMED, ABOUT, Task.claimed_*, Task.completed_by | M03a |
| Folder, File for code (the walker), Commit, CONTAINS, PARENT, CHANGED, COMPLETES, PART_OF, TOUCHES, TESTS | M04a |
| Table, Column, Feature, Domain and their relationships, MENTIONS, AFFECTS | M04b |

## 8. Acceptance checks

1. Every ID in §1 round-trips through `ids.normalise()` from each typed form listed.
2. Syncing the same unchanged repo twice produces identical node and relationship counts (idempotent upserts).
3. Removing a link from a section and re-syncing removes exactly that `LINKS_TO` relationship.
4. A link to a missing section is listed in `unresolved` and creates no relationship.
5. No File node has a property holding file contents.
