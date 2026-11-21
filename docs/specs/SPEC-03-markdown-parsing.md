# SPEC-03 — Markdown parsing

> **Status:** v1 (2026-11-21) · **Owner of:** which files are parsed, the spec-reference grammar, what each document type yields, task IDs, the Feature line, schema tables
> Produces the nodes in [SPEC-02](SPEC-02-graph-schema.md). Reference formats: office-rag and office-suite-v2 (read-only; fixtures in `tests/fixtures/`).

## 1. Rules and configuration

1. **Parsers are pure and tolerant.** They take `(path, text)` and return parsed objects plus `warnings` (`{path, line, code, message}`). They never raise on bad Markdown. `sdd doctor` lists the warnings.
2. Parsing uses `markdown-it-py` tokens (which carry line numbers) plus small regexes for header lines. No HTML rendering.
3. **No new conventions are required except stable task IDs** ([§4.2](#42-task-ids)). The Feature line ([§3.3](#33-feature-line)) is optional.
4. Both reference formats must parse with zero warnings of severity `error`.
5. **Code is not prose.** Markdown links, spec references, task-ID mentions and `**DEVIATION:**` notes inside inline code spans and fenced or indented code blocks are ignored, so specs can show examples without creating links. Two uses of inline code are deliberate and still apply: the backticked identifier `part` of a spec reference (§2.2), and `MENTIONS` (§3.2).
6. **Warning codes.** Every warning has a `code` and a severity; `sdd doctor` exits 1 on any `error`. The complete list (`parse/model.py` `WARNING_CODES` builds every warning from it, so a typo fails fast):

| Code | Severity | When |
|---|---|---|
| `bad_filename` | error | the file name has no Spec, Milestone or Deviation ID, so the parser cannot build the node |
| `task_duplicate_id` | error | two tasks with the same stable ID in one file (the second becomes positional) |
| `missing_h1` | warning | no H1 |
| `h1_id_mismatch` | warning | the H1's ID differs from the file name's (the file name wins) |
| `task_id_mismatch` | warning | [§4.2](#42-task-ids) |
| `task_unstable_id` | warning | [§4.2](#42-task-ids) |
| `task_bad_after` | warning | `(after …)` names something that is not a task ID |
| `ref_bad_range` | warning | a `§` range that cannot be expanded (both ends are kept as plain section references) |
| `ac_duplicate_number` | warning | two acceptance checks with one number (the second is skipped) |
| `feature_bad_line` | warning | a Feature line without a name |
| `deviation_missing_section` | warning | [§5.1](#51-deviation-files) |
| `deviation_bad_field` | warning | an unparsable **Date / milestone:** date |
| `deviation_index_mismatch` | warning | [§5.2](#52-deviation-index) |
| `section_duplicate_id` | info | two headings map to one section ID (the second gets `-2`) |
| `link_moved` | info | [§2.1](#21-markdown-links) (reported by the resolver) |

Default paths, overridable in `.sdd/config.toml`:

| Key | Default |
|---|---|
| `specs` | `docs/specs/SPEC-*.md` |
| `milestones` | `docs/milestones/**/M*.md` whose file name matches `M\d+[a-z]?-.+\.md`, excluding `*-plan.md` |
| `plans` | `docs/milestones/**/M*-plan.md` whose file name matches `M\d+[a-z]?-plan\.md` |
| `deviations` | `docs/deviations/D*.md` |
| `deviation_index` | `docs/DEVIATIONS.md` |
| `docs` | `**/CLAUDE.md`, `docs/IDEA.md`, `docs/design-system.md`, `HANDOFF.md`, `README.md` |
| `schema_specs` | specs whose file name contains `schema` |
| `tests` | `tests/**`, `**/*Tests/**`, `**/*.test.ts`, `**/test_*.py`, `**/*_test.go` |

## 2. Links and spec references

### 2.1 Markdown links
A relative link is resolved against the linking file's folder to a path, then to the node with that `source_path` (Spec, Milestone, Deviation, Doc, or File). Its anchor, if any, is matched against `Section.anchor` in that spec. External links (`http…`) are ignored.

**Moved files.** If no node has that path, but the link's file name starts with a spec, milestone or deviation ID (`M00-foundation.md`, `SPEC-04-sync.md`, `D012-….md`), the link resolves to the node with that ID wherever its file now lives, with a `link_moved` warning (severity `info`). This keeps links working after `complete_milestone` moves a file to `done/`, while write-back repairs the Markdown itself ([SPEC-04 §5.1](SPEC-04-sync.md#51-edits)).

### 2.2 Spec-reference grammar
Section references in **link text and plain text** are parsed with one grammar, used everywhere (Read first, task lines, deviation **Spec:** fields, prose):

```
ref     := "SPEC-" digits [ ws? sections ] [ "(whole file)" | "(whole section)" ]
sections:= part ( ws? ("," | "and") ws? part )*
part    := "§" num [ ws? ("–" | "-") ws? "§"? num ]  |  "`" identifier "`"
num     := digits ( "." digits )*
```

- **A reference to a section includes its descendants.** `SPEC-00 §6` means §6 and §6.1–6.7. `READS`, `GOVERNED_BY` and `LINKS_TO` point at the named section only; every reader (`get_context`, `read_section`, the benchmark) expands it to the subtree. "(whole section)" is accepted and means the same as no suffix.
- A range expands to the sibling sections between both ends, inclusive: `§3–4` → `#3`, `#4`; `§4.6–4.7` → `#4.6`, `#4.7`; `§4–§6` → `#4`, `#5`, `#6`.
- A backticked identifier names a section by the slug of its **title, numbered or not**: `` SPEC-02 `file_shares` `` → the section titled `file_shares`; `` SPEC-02 `documents` `` → the section `` ## 2. `documents` `` (ID `SPEC-02#2`). No match is an unresolved link.
- Trailing words such as `step 1` or `invariant 1` are kept in the relationship's `note` property, not resolved.
- **When a link has both an anchor and § references in its text, the text wins** (an anchor can only point at the first section of a range).
- `SPEC-NN` alone (or "(whole file)") targets the Spec node.
- References to non-spec docs (`design-system §1`) resolve to the Doc and are recorded with `note`.

## 3. Specs

### 3.1 Header
The H1 is `# SPEC-NN — Title` (em dash, en dash or hyphen). The blockquote right after it is the **header**: every `**Key:** value` pair, split on ` · ` and across `>` lines, goes into `Spec.header`; `Status` and `Owner of` also go into their own properties. Both reference styles parse (`**Status:** v1 (…) · **Owner of:** …` and `**Spec ID:** SPEC-02 · **Consumed by:** …`).

### 3.2 Sections
- Every H2–H4 is a Section. A leading number (`5.2`, `6.`, `10.`) becomes `number`; the rest is `title`. `anchor` follows GitHub's slug rules.
- `text` is the body until the next heading of the same or a higher level, **excluding** child sections (they are their own nodes, linked by `HAS_SECTION`).
- A Section's `content_hash` covers its own text only, so editing §5.2 changes §5.2, not §5.
- Markdown links and spec references in the text become `LINKS_TO`. Backticked identifiers that exactly match a known table name or an existing file path become `MENTIONS` ([SPEC-02 §4](SPEC-02-graph-schema.md#4-relationships)).
- A line containing `**DEVIATION:**` (at any blockquote depth, outside code) links every `[Dnnn]` on it to this section with `AMENDS` (from the deviation).
- A section titled *Acceptance checks* (any level, number optional) yields one AcceptanceCheck per top-level numbered list item.

### 3.3 Feature line
Optional, in the header blockquote, one line per feature:

```markdown
> **Feature:** File sharing · **Domain:** Files · **Implements:** `backend/**/FileShares/**`, `frontend/src/features/files/**` · **Tables:** file_shares, attachments
```

Yields Feature (slug from the name), Domain, `SPECIFIED_BY` this spec, `BELONGS_TO`, `IMPLEMENTED_IN` (globs expanded by sync, [SPEC-04 §4](SPEC-04-sync.md#4-code-walker)) and `USES_TABLE`. A feature declared in two specs is one node with two `SPECIFIED_BY` relationships.

## 4. Milestones and tasks

### 4.1 Header lines
In the blockquote after the H1 (`# M02 — Title`; `M` + digits + optional letter):
- `**Depends on:**` → `DEPENDS_ON` to every milestone linked or named in that segment (`[M02](…) technically (scheduled after [M16](…))` yields M02 and M16). `—` or `nothing` yields none.
- `**Blocks:**` → `DEPENDS_ON` in reverse. Duplicates merge.
- `**Read first:**` → `READS` for every spec reference in the segment, which may span several `>` lines and use `·` or `→` separators. "(whole file)" sets `whole: true`.
- `**Model:**` → `model` (first word: `Opus`, `Sonnet`, `Opusplan`), the rest is kept in `header`.

### 4.2 Task IDs
The one convention this tool adds:

```markdown
- [ ] **M02.3** Hash and re-parse only changed files (after M02.1)
```

- Regex: `^\s*[-*] \[( |x|X)\] \*\*(M\d+[a-z]?\.\d+)\*\*\s+(.*)`. The ID's milestone part must match the file's milestone, or it is a warning (`task_id_mismatch`).
- `(after M02.1)` or `(after M02.1, M01.4)` at the end yields `BLOCKED_BY`.
- Numbers are never reused within a milestone. A new task takes the next free number, wherever it is inserted.
- **Legacy lines without an ID** get a positional ID `M17.p3` with `stable_id = false` and a `task_unstable_id` warning. `sdd ids --write` rewrites the file once, numbering them after the highest existing number ([SPEC-08 §2](SPEC-08-cli-and-exports.md#2-commands)).
- A task's text includes its continuation lines and nested plain bullets. A nested checkbox is its own task.
- Links and spec references in the task text yield `GOVERNED_BY`; "checks 3–9", "check 6", "checks 1, 3" next to a spec reference yield `VERIFIES` to those AcceptanceChecks.
- The `###` heading above the task becomes `group`.

### 4.3 Other sections
*Goal* → `goal`. *Acceptance criteria* → `acceptance` (numbered items). A *Checks finished in later milestones* table is kept as raw text in `header.later_checks`.

### 4.4 Status
The paragraph starting `**Status:**` or `**Status:` (bold may wrap the whole sentence, as in `**Status: DONE (2026-11-01), with one open item.**`) is `status_text`, with following bullets included.
- `DONE` (case-insensitive) at its start → `status = done`, and `done_date` from `(YYYY-MM-DD)`.
- Otherwise `in_progress` if any task is done or claimed, else `todo`.
- Deviation numbers in the status text (`D021`) link to the deviation with `RAISED_IN` if not already linked.

## 5. Deviations and docs

### 5.1 Deviation files
`# D012 — Title`, then the bullet fields `**Date / milestone:**` (`2026-10-29 · M04`, optionally followed by the task: `2026-10-29 · M04 · M04.2`), `**Spec:**` (spec references by §2.2, linked or plain), the optional `**Affects:**` (backticked file paths and table names, comma-separated) and `**Status:**`, then the H2 sections *Spec says*, *Implementation does*, *Why*, *Consequences*. Missing sections are warnings, not errors. The task yields `RAISED_IN` → Task (besides the milestone); each `Affects` entry yields `AFFECTS` to the File or Table it names, or goes to `unresolved` (File nodes for code exist from M04a, Table nodes from M04b). Both fields are optional, so the reference formats, which lack them, parse without warnings.

### 5.2 Deviation index
`DEVIATIONS.md` is parsed only to cross-check: a file without an index row, or a row without a file, is a `deviation_index_mismatch` warning. The index is also where write-back inserts rows ([SPEC-04 §5](SPEC-04-sync.md#5-write-back)).

### 5.3 Docs
CLAUDE.md files, IDEA, design system, HANDOFF and README become Doc nodes with their links as `LINKS_TO`. Plan files (`M20f-plan.md`) become Docs with `kind = plan` and `PLANS` → the milestone.

## 6. Schema tables

In `schema_specs` only. A **table section** is a heading whose title, after removing its number and any trailing parenthetical (`(append-only)`, `([SPEC-18](…))`), is one identifier, optionally backticked. It must be followed, before the next heading, by a Markdown table whose first header cell is `Column`. Both reference layouts qualify:

```markdown
## 2. `documents`                    ### attachments
| Column | Type | Rules |          | Column | Type | Notes |
```

Per row: `name` from the first cell (backticks stripped; `created_at`, `updated_at` in one cell yield two columns); `type` from the Type cell. From the Type and Rules/Notes cells:
- `not null` → `nullable = false`; otherwise `null` as a word → `true`; otherwise unknown (`null`).
- `PK` → `pk = true`.
- `→ name` or `FK → name` → `REFERENCES` that table (unresolved if it is not defined).

Yields Table, Column, `DEFINES_TABLE` from the section, `HAS_COLUMN`, `REFERENCES`.

## 7. Acceptance checks

1. The office-rag fixture (SPEC-00, SPEC-02, M00, M02, DEVIATIONS) parses with zero `error` warnings; M02's Read first yields READS to `SPEC-03` (whole), `SPEC-02#3`, `SPEC-02#4`, `SPEC-06#2`, `#4`, `#5`, `#6`, `SPEC-08#4.6`, `#4.7`, `SPEC-11#2`.
2. The office-suite fixture (SPEC-02 excerpt, M17, D012, D018 notes) parses with zero `error` warnings; M17 is `done` with `done_date = 2026-11-01` and RAISED_IN from D021.
3. Grammar: `SPEC-19 §4–§6` → 3 sections; `SPEC-02 §3–4` → 2; `` SPEC-02 `file_shares` `` → the slug section; `SPEC-06 §7 step 1` → `#7` with `note = "step 1"`.
4. A link `[SPEC-02 §3–4](…#3-chunks)` yields both `#3` and `#4` (text beats anchor).
5. Task lines: `**M02.3**` parses with `stable_id = true`; a legacy line gets `M17.p3`, `stable_id = false` and a warning; `(after M02.1)` yields BLOCKED_BY.
6. A nested `> > **DEVIATION:** see [D018](…)` note yields AMENDS from D018 to its section.
7. Schema tables: office-rag `documents` and office-suite `attachments` both yield Table + Columns; `uploaded_by | → users [restrict]` yields REFERENCES to `users`; `ts` stays a column.
8. The Feature line yields Feature, Domain, SPECIFIED_BY, BELONGS_TO, USES_TABLE, and stores the globs.
9. A deviation with `**Date / milestone:** … · M04 · M04.2` and `**Affects:**` naming an existing file and a defined table yields RAISED_IN to M04 and M04.2 and AFFECTS to both, and all of them survive `sdd sync --reset`; a deviation without either field parses with no warning.
