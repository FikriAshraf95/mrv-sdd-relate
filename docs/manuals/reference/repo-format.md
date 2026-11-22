# Repo format and parsing rules

> What SDD Graph reads from your Markdown, and how. The source of truth is [SPEC-03](../../specs/SPEC-03-markdown-parsing.md).

**Parsers are tolerant.** Bad Markdown never crashes a sync; it produces a warning that `sdd doctor` lists. **Code is not prose:** links, spec references, task IDs and `**DEVIATION:**` notes inside inline code or code blocks are ignored, so specs can show examples. Two exceptions: the backticked identifier in a spec reference (``SPEC-02 `bookings` ``) and backticked names that create `MENTIONS`.

The only convention SDD Graph **adds** is the task ID. The Feature line is optional.

## Files and IDs

| Document | File name | ID | Default glob |
|---|---|---|---|
| Spec | `SPEC-<digits>-<name>.md` | `SPEC-03` | `docs/specs/SPEC-*.md` |
| Milestone | `M<digits>[a-z]-<name>.md` | `M05a` | `docs/milestones/**/M*.md` |
| Plan | `M<digits>[a-z]-plan.md` | `doc:<path>` | `docs/milestones/**/M*-plan.md` |
| Deviation | `D<3+ digits>-<name>.md` | `D006` | `docs/deviations/D*.md` |
| Deviation index | any | (no node) | `docs/DEVIATIONS.md` |
| Other docs | any | `doc:<path>` | `**/CLAUDE.md`, `docs/IDEA.md`, `docs/design-system.md`, `HANDOFF.md`, `README.md` |

IDs come from the **file name** and are normalised: prefixes upper-case, milestone letters lower-case, spec and milestone numbers zero-padded to 2 digits, deviations to 3 (`M2-x.md` → `M02`, `d12` → `D012`). Moving a file (e.g. to `done/`) keeps its ID, its tasks and their claims. Change any glob in [`.sdd/config.toml`](configuration.md).

## Specs

```markdown
# SPEC-03 — Booking rules

> **Spec ID:** SPEC-03 · **Consumed by:** SPEC-04, SPEC-05
> **Status:** v1 · **Owner of:** slots, overlap, cancellation
> **Feature:** Booking · **Domain:** Courts · **Implements:** `src/booking/**` · **Tables:** bookings, courts

## 1. Slots and opening hours
…
### 1.1 Holidays
…
## Acceptance checks
1. Two bookings of one court never overlap.
2. …
```

- **H1:** `# SPEC-NN — Title` (em dash, en dash or hyphen). The ID in the file name wins if they differ (`h1_id_mismatch`).
- **Header:** the blockquote right after the H1. Every `**Key:** value` pair, split on ` · ` and across lines, goes into `Spec.header`; `Status` and `Owner of` also get their own properties.
- **Sections:** every `##`, `###`, `####` heading. A leading number (`5.2`, `6.`) becomes the section's number, so the ID is `SPEC-03#5.2`. Unnumbered headings get a slug ID (`SPEC-02#bookings`). A section's text runs until the next heading of the same or higher level, **without** its child sections. Editing §5.2 marks only §5.2 as changed.
- **Acceptance checks:** a heading titled *Acceptance checks* (any level, number optional). Each top-level numbered item becomes `SPEC-03#ac1`, `#ac2`, … Name tests after them (`test_spec03_ac2_…`) and the walker links the test file to the check.
- **Links:** Markdown links and spec references in a section's text become `LINKS_TO`. Backticked identifiers that exactly match a table name or an existing file path become `MENTIONS`.
- **Deviation notes:** a line containing `**DEVIATION:**` (at any blockquote depth) links each `[Dnnn]` on it to that section with `AMENDS`.

### Feature lines

Optional, in the spec header, one line per feature:

```markdown
> **Feature:** File sharing · **Domain:** Files · **Implements:** `backend/**/FileShares/**`, `frontend/src/features/files/**` · **Tables:** file_shares, attachments
```

Creates a Feature (slug from the name), a Domain, `SPECIFIED_BY` → this spec, `BELONGS_TO` → the domain, `IMPLEMENTED_IN` → every file matching the globs (re-expanded as files come and go), and `USES_TABLE` → each table. Globs are project-relative and gitignore-style. A feature declared in two specs is one node with both specs and the union of the globs. A glob matching nothing gives `feature_glob_empty`.

### Schema tables

In `schema_specs` only (default: specs whose file name contains `schema`). A **table section** is a heading whose title is one identifier, optionally backticked, after removing its number and any trailing parenthetical. Before the next heading it must contain a Markdown table whose first header cell is `Column`:

```markdown
### bookings
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| member_id | uuid not null | → members [restrict] |
| starts_at, ends_at | timestamptz not null | |
```

- Header cells are matched by name: `Column`, `Type`, and `Rules` or `Notes`.
- `a, b` in one cell gives two columns.
- `not null` → `nullable = false`; `null` as a word → `true`; else unknown.
- `PK` → `pk = true`.
- `→ name` or `FK → name` → `REFERENCES` that table.

Creates Table, Column, `DEFINES_TABLE`, `HAS_COLUMN`, `REFERENCES`.

## Spec references

One grammar everywhere: *Read first* lines, task lines, the deviation **Spec:** field, and prose.

| Form | Resolves to |
|---|---|
| `SPEC-03 §2` | §2 **and its subsections** (readers expand the subtree) |
| `SPEC-03 §4.6–4.7`, `SPEC-03 §4–§6` | the sibling sections between both ends, inclusive |
| `SPEC-03 §2, §5`, `SPEC-03 §2 and §5` | several sections |
| ``SPEC-02 `bookings` `` | the section whose title slug is `bookings`, numbered or not |
| `SPEC-03`, `SPEC-03 (whole file)` | the Spec node |
| `SPEC-03 §2 (whole section)` | same as `SPEC-03 §2` |
| `SPEC-03 §7 step 1` | `#7`, with `step 1` kept as a note |
| `SPEC-04 §4 checks 1–3` (in a task line) | `VERIFIES` → `SPEC-04#ac1`, `#ac2`, `#ac3` |

Typed forms are forgiving: `SPEC-03§5.2`, `spec-03#5.2`, `SPEC-3 5.2` all work. `SPEC-035.2` is rejected as ambiguous. When a link has both an anchor and `§` text, **the text wins**. A link to a file that moved still resolves by its ID, with a `link_moved` info warning.

## Milestones and tasks

```markdown
# M05a — Waitlist

> **Depends on:** [M04](done/M04-payments.md)
> **Read first:** [SPEC-05 §1–2](../specs/SPEC-05-waitlist.md#1-joining) · [SPEC-02 `waitlist_entries`](../specs/SPEC-02-database-schema.md#waitlist_entries)
> **Model:** Opusplan. Promotion touches the booking rules.

## Goal
Members can queue for a taken slot.

## Tasks
### Backend
- [ ] **M05a.1** Join the waitlist for a taken slot ([SPEC-05 §1](…))
- [ ] **M05a.2** Promote the oldest entry ([SPEC-05 §2](…)) (after M05a.1)
### Tests
- [ ] **M05a.4** [SPEC-05 §4](…) checks 1–2 (after M05a.2)

## Acceptance criteria
1. A member cannot join the waitlist for a free slot.

**Status:**
```

| Element | Becomes |
|---|---|
| `# M05a — Title` | Milestone `M05a`, `title` |
| `**Depends on:**` | `DEPENDS_ON` to every milestone linked or named. `—` or `nothing` gives none |
| `**Blocks:**` | `DEPENDS_ON` in reverse |
| `**Read first:**` | `READS` for every spec reference (may span several `>` lines; `·` or `→` separators). `(whole file)` sets `whole: true` |
| `**Model:**` | `model` = the first word (`Opus`, `Sonnet`, `Opusplan`) |
| `## Goal` | `goal` |
| `## Acceptance criteria` | `acceptance` (numbered items) |
| `### Backend` above tasks | the tasks' `group` |
| `**Status:**` paragraph | `status_text`. `DONE (2026-11-07)` at its start → `status = done` and `done_date`. Otherwise `in_progress` if any task is done or claimed, else `todo`. Bold may wrap the whole sentence: `**Status: DONE (…), with one open item.**` |

### Task lines

```
^\s*[-*] \[( |x|X)\] \*\*(M\d+[a-z]?\.\d+)\*\*\s+(.*)
```

- `**M05a.2**` right after the checkbox is the stable ID. Its milestone part must match the file (`task_id_mismatch` otherwise).
- **Numbers are never reused.** A new task takes the next free number wherever it is inserted.
- `(after M05a.1)` or `(after M05a.1, M04.3)` at the end → `BLOCKED_BY`.
- Links and spec references in the line → `GOVERNED_BY`. `checks 1–3` next to a spec reference → `VERIFIES`.
- Backticked file paths and table names → `MENTIONS`.
- Continuation lines and nested plain bullets belong to the task. A nested checkbox is its own task.
- **Legacy lines without an ID** get a positional ID (`M17.p3`, `stable_id = false`) and a `task_unstable_id` warning. `sdd ids --write` gives them real IDs.
- `[x]` / `[X]` is `checked`, the only status that comes from Markdown. `todo` / `claimed` / `done` is derived.

Plan files (`M05a-plan.md`) become Docs with `PLANS` → the milestone.

## Deviations

```markdown
# D006 — A promoted waitlist entry holds the slot for 15 minutes

- **Date / milestone:** 2026-11-12 · M05a · M05a.2
- **Spec:** [SPEC-05 §2](../specs/SPEC-05-waitlist-and-reminders.md#2-promotion)
- **Affects:** `bookings`, `waitlist_entries`, `src/waitlist/promote.py`
- **Status:** Open

## Spec says
## Implementation does
## Why
## Consequences
```

| Field | Becomes |
|---|---|
| **Date / milestone:** `date · milestone · task` | `date`, `RAISED_IN` → milestone and (optional) task |
| **Spec:** spec references | `AMENDS` (so do `> **DEVIATION:** see [D006]` notes in specs) |
| **Affects:** backticked paths and tables (optional) | `AFFECTS` → File / Table, or `unresolved` |
| **Status:** `Open` / `Resolved → spec updated` | `status` = `open` / `resolved` (anything starting `Open` is `open`) |
| `## Spec says`, `## Implementation does`, `## Why`, `## Consequences` | properties of the same names. A missing one is a warning |

Deviation numbers in a milestone's **Status:** text also add `RAISED_IN`. **The index** (`DEVIATIONS.md`) is only cross-checked: a file without a row, or a row without a file, is `deviation_index_mismatch`. `log_deviation` inserts rows at the top of the table whose first header cell is `#`, and copies the fenced template under `## Template`.

## Commits

| In the commit message | Becomes |
|---|---|
| `[M05a.2]` (one or more) | `COMPLETES` → the task, and `TOUCHES` from the task to the commit's changed files |
| `(M05a)` or a bare `M05a`, when no task ID | `PART_OF` → the milestone |

Author **names** only, never emails. A commit never changes a task's status; an unticked task with a `COMPLETES` commit is flagged in `sdd status`.

## Warning codes

| Code | Severity | When |
|---|---|---|
| `bad_filename` | error | a file matched a glob but its name has no Spec, Milestone or Deviation ID |
| `task_duplicate_id` | error | two tasks with the same ID in one file (the second becomes positional) |
| `missing_h1` | warning | no H1 |
| `h1_id_mismatch` | warning | the H1's ID differs from the file name's (the file name wins) |
| `task_id_mismatch` | warning | a task ID's milestone part differs from the file's milestone |
| `task_unstable_id` | warning | a task line without an ID (run `sdd ids --write`) |
| `task_bad_after` | warning | `(after …)` names something that isn't a task ID |
| `ref_bad_range` | warning | a `§` range that can't be expanded (both ends kept as plain references) |
| `ac_duplicate_number` | warning | two acceptance checks with one number (the second is skipped) |
| `feature_bad_line` | warning | a Feature line without a name |
| `feature_glob_empty` | warning | a Feature's globs match no file |
| `deviation_missing_section` | warning | a deviation file lacks one of the four sections |
| `deviation_bad_field` | warning | an unparsable **Date / milestone:** date |
| `deviation_index_mismatch` | warning | a deviation file without an index row, or the other way round |
| `duplicate_id` | warning | two files produce the same node ID; the first by path wins |
| `section_duplicate_id` | info | two headings map to one section ID (the second gets `-2`) |
| `link_moved` | info | a link to a moved file resolved by its ID |

`sdd doctor` exits 1 on any `error`.
