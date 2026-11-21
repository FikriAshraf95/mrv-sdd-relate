# SPEC-04 — Sync

> **Status:** v1 (2026-11-21) · **Owner of:** the watcher, incremental sync, deletes and renames, the code walker, git sync, write-back, loop prevention
> Shapes: [SPEC-02](SPEC-02-graph-schema.md) · Parsing: [SPEC-03](SPEC-03-markdown-parsing.md) · Writes go through the queue in [SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)

## 1. Watcher

- `SDD_WATCH` = `poll` | `native` | `auto` (default). `auto` uses polling when `/.dockerenv` exists, else native events. **Polling is required in Docker on Windows**: inotify sees none of the host's edits through a bind mount; polling sees all of them (verified 2026-11-21).
- Two poll intervals, because every poll stats every watched file and stats through a Windows bind mount are slow: `SDD_POLL_INTERVAL` (default 1 s) for the SDD document globs ([SPEC-03 §1](SPEC-03-markdown-parsing.md#1-rules-and-configuration)), and `SDD_POLL_CODE_INTERVAL` (default 10 s) for the rest of the tree. M02 (task M02.8) measures one poll of a 20 000-file tree through the mount and adjusts the defaults. Native mode watches everything with one observer.
- Events are debounced for 300 ms and processed as one **batch**.
- Ignored: `.sdd/`, `.git/` (the git poller covers it) and every path the code walker ignores ([§4](#4-code-walker)).

## 2. Incremental sync

The per-file state is `File.content_hash`: every tracked file, Markdown included, has a File node (SDD documents from M01b, code files from M04a, [SPEC-02 §7](SPEC-02-graph-schema.md#7-label--milestone-map)).

The **initial sync** is any sync that runs while `Meta.last_full_sync` is unset (a new or reset store). It records state but emits no Events and sets no `changed_at` or `done_at`: history from before the tool existed is unknown, and a flood of "changes" would bury real ones in `what_changed`.

1. For each changed path, hash it. Equal to the stored hash → skip (this is also how write-back avoids loops, [§5.4](#54-loop-prevention)).
2. Classify: spec, milestone, plan, deviation, deviation index, doc, test file, other.
3. **If the set of SDD document IDs changed** (a spec, milestone or deviation was added, removed or renamed), re-parse **all** SDD Markdown, so links that were unresolved can resolve. Otherwise only changed files are re-parsed. Parsing a few hundred files takes well under a second, so this stays simple and correct.
4. **Phase 1, nodes:** for each parsed file (specs → milestones → plans → deviations → docs), one transaction upserts its nodes by `id`, following the property rules below and in [§2.1](#21-task-upsert-rules). Folder and File nodes for changed code files are upserted in this phase too, so Markdown can link to them (`MENTIONS`, `AFFECTS`).
5. **Phase 2, relationships:** for each parsed file, one transaction deletes the relationships it owns (`src = path`, [SPEC-02 §4](SPEC-02-graph-schema.md#4-relationships)) and creates the new ones. Because every node of the batch already exists, links between files of the same batch resolve regardless of order (a spec linking to another spec, `Blocks:` pointing at a later milestone). Targets still missing go to `unresolved`.
6. Then the walker's relationships: `CONTAINS`, feature glob re-expansion, `TESTS` scan of changed test files.
7. After the initial sync: a Section whose `content_hash` changed, or a new Section in a spec that already existed, gets `changed_at = now` and a `section_changed` Event. A new spec gets `spec_added` (its sections keep `changed_at = null`); a removed one gets `spec_removed`.
8. After the batch: `checkpoint()`, update `Meta.last_full_sync` for full scans, and publish one SSE `graph_changed` event listing the changed IDs ([SPEC-07 §3](SPEC-07-dashboard-and-api.md#3-live-events)).

> **DEVIATION:** see [D003](../deviations/D003-relink-on-catalog-change.md) — step 3 re-links every file when anything links resolve against changes (IDs, anchors, title slugs, document paths), not only when the set of document IDs changes

**Startup** runs a full scan through the same path, as one batch: every file's hash against the graph, removed files deleted, then git sync.

### 2.1 Task upsert rules
An upsert sets `checked`, `title`, `group`, `order` and `stable_id` from Markdown and then recomputes the derived `status` ([SPEC-02 §2](SPEC-02-graph-schema.md#task)). The graph-only properties (`claimed_by`, `claimed_at`, `completed_by`, `done_at`, `notes`) change **only** in these cases:

| Case | Effect |
|---|---|
| New task (any sync) | Graph-only properties empty; no Event, even if it is already ticked |
| `checked` unchanged | Graph-only properties untouched |
| Ticked by hand (`false` → `true`), after the initial sync | `done_at = now` if empty; the claim is cleared (`claimed_by`, `claimed_at`, the `CLAIMED` relationship); a `task_completed` Event with `actor = human` |
| Unticked by hand (`true` → `false`) | `done_at` and `completed_by` cleared; `notes` kept (the Events keep the history) |
| The tick written by a tool's own write-back | Handled by that write job: the re-parse in [§5.4](#54-loop-prevention) sees no hand transition, and the Event names the agent, not `human` |

With `writeback = false`, `complete_task` sets `completed_by` and `done_at` without touching Markdown; the derived status counts that as `done`, so a later sync of the unticked line does not revert it.

## 3. Deletes and renames

- A removed file: delete its File node and every node whose `source_path` is that file, **unless the same `id` is produced by another file in the same batch**. So moving `M17-file-sharing.md` to `done/` (a delete plus an add) keeps M17, its tasks and their claims; only `path` and `source_path` change.
- Deleting a node uses `DETACH DELETE`, so its relationships go too. Stale data is worse than none, because agents trust it.
- Two files producing the same ID: the first by path wins; the other gets a `duplicate_id` warning.
- A Task deleted while claimed emits `task_released` with `actor = sync`.

## 4. Code walker

- Walks the project root. It skips paths matched by `.gitignore` files (via `pathspec`), `.sddignore`, and the built-in list: `.git`, `.sdd`, `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `bin`, `obj`, `.next`, `coverage`, `target`.
- Creates Folder and File nodes with `CONTAINS`. `language` comes from an extension map; `is_test` from the `tests` globs ([SPEC-03 §1](SPEC-03-markdown-parsing.md#1-rules-and-configuration)); `lines` is counted for text files under 2 MB.
- A soft cap of 20 000 files (`SDD_MAX_FILES`) logs a warning and keeps the first 20 000 by path.
- **Feature globs** are re-expanded when any file is added or removed, rebuilding `IMPLEMENTED_IN` for every feature (cheap; a feature with no matches gets a `feature_glob_empty` warning).
- **TESTS:** changed test files are scanned for `spec(\d+)_ac(\d+)` (case-insensitive). Each match links the file to `SPEC-<nn>#ac<n>` when it exists, with the numbers read as integers: `spec5_ac03` and `spec05_ac3` both mean `SPEC-05#ac3`.
- Relate's own `fs-to-graph` extension is evaluated in M04a (open item O8). The default is this walker, because extensions run under a Relate host that would have to own the store, and our daemon already does.

## 5. Write-back

`sdd/sync/writeback.py` is the only module that edits Markdown. Every edit runs **inside the write job** that changes the graph, so the file and the graph change together, serialized with every other write.

### 5.1 Edits
| Trigger | Edit |
|---|---|
| `complete_task` | Find the line with `**<task id>**`; replace `[ ]` with `[x]`. Nothing else on the line changes |
| `log_deviation` | (1) Next number = highest D-number in the files **and** the index, + 1 (computed inside the job, so parallel agents never collide). (2) Write `docs/deviations/D<nnn>-<kebab-title>.md` from the template in `DEVIATIONS.md` (or the built-in one), with the task after the milestone in **Date / milestone:** and the resolved `affects` entries in **Affects:** ([SPEC-03 §5.1](SPEC-03-markdown-parsing.md#51-deviation-files)), so the links are rebuildable. (3) Insert the index row at the **top** of the index table, replacing a `*(none yet)*` placeholder row. (4) Append `> **DEVIATION:** see [D<nnn>](…) — <summary>` as the last line of each amended section's own body (before its first child heading), preceded by a blank line so it never joins a table, list or paragraph above it. When the whole spec is amended, the note goes at the end of the header blockquote, as its own `>` line |
| `complete_milestone` | Replace the `**Status:**` paragraph with `**Status:** DONE (<date>). <verification> Deviations: <list or none>.`; move the file (and its plan file) to `done/` if that folder exists, and **rewrite every relative link to the moved files** in the SDD documents (path part only; text and anchor unchanged), in the same job |
| `sdd export --claude-status` | Replace the text between `<!-- sdd:status -->` and `<!-- /sdd:status -->` in CLAUDE.md; nothing outside the markers |

### 5.2 Safety
- Writes are atomic: write a temp file in the same folder, then rename. Line endings (LF or CRLF), the final newline and UTF-8 encoding are preserved.
- Before editing, the file is re-read and the target re-located by ID or heading, never by a cached line number. If the target is gone (a human edited it away), the job fails with `source_changed` and the graph is not changed.
- **Order inside a job:** check → change the graph (uncommitted) → write the Markdown files (atomic renames) → re-parse them ([§5.4](#54-loop-prevention)) → `commit()`. Markdown goes last because it cannot be rolled back. If the commit still fails after the files were written, Markdown is ahead of the graph; the watcher's next batch reconciles it, since Markdown is the source of truth.
- **Edits are idempotent**, because a retried job runs again ([SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)): a box already `[x]` is left alone, a deviation file or index row that already exists for this job is reused, a status line already `DONE` is not written twice.
- The daemon **never commits** to git. People and agents commit.
- `writeback = false` in config turns write-back off. `complete_task` still works and completion lives only in the graph ([§2.1](#21-task-upsert-rules)); `sdd status` says so. `log_deviation` and `complete_milestone` fail with `writeback_disabled`, because a deviation or a DONE status that exists only in the graph would contradict the Markdown.

### 5.3 Graph-only state
Defined once, in [SPEC-02 §2](SPEC-02-graph-schema.md#graph-only-state-canonical-list). A full rebuild (`sdd sync --reset`) drops it; a normal sync keeps it.

### 5.4 Loop prevention
After writing a file, the same job re-parses it and stores its new `content_hash`. When the watcher then reports the change, the hash matches and nothing happens. For a move, the job also deletes the old path's File node and updates `path` / `source_path` on the moved nodes itself, rather than leaving it to a later delete-plus-add batch.

## 6. Git sync

- On startup, and when `git rev-parse HEAD` changes (polled every 3 s, which works through bind mounts).
- New commits: `git log --reverse --name-status --format=<sha, parents, author, ISO date, subject> <last>..HEAD`. The first sync is limited to the newest `SDD_GIT_MAX_COMMITS` (default 2000). `Meta.last_git_sha` is stored after each sync.
- **History rewritten** (`last_git_sha` is not an ancestor of HEAD: rebase, reset, branch switch): delete Commit nodes no longer reachable within the limit, with every relationship whose `src` is `git:<that sha>`, and add the new ones. Relationships with `src = "tool"` are never touched.
- Per commit: Commit node, `PARENT`, `CHANGED` to files that still exist (all paths stay in `Commit.paths`), `COMPLETES` for each `[M02.3]`, `PART_OF` for `(M20f)` when no task ID is present. Then `TOUCHES` from each completed task to the commit's changed files.
- A commit never changes a task's status. Markdown stays the source of truth; a `COMPLETES` link on an unticked task is shown as a warning in `sdd status`.
- Docker: the image sets `git config --global --add safe.directory '*'`, because the bind-mounted repo is owned by another user.

## 7. Acceptance checks

1. With `SDD_WATCH=poll`, editing a spec section on the host updates that Section's `text` and `changed_at` within 3 s, and no other Section's `changed_at`.
2. Re-syncing an unchanged repo writes nothing (no `changed_at` moves, no Events).
3. Moving a milestone file to `done/` keeps its ID, its tasks and an active claim; only `path` changes.
4. Deleting a spec file removes its Spec, Sections and checks, and the READS/GOVERNED_BY relationships pointing at them; the referring milestones list the links as `unresolved`.
5. Adding a spec that an existing milestone already links to resolves that link in the same batch.
6. `complete_task` ticks exactly one line, preserving CRLF line endings, and the watcher does not trigger a second sync of that file.
7. Two concurrent `log_deviation` calls produce D-numbers n and n+1, two files, two index rows at the top and two spec notes.
8. A `.gitignore`d path and `node_modules/` produce no File nodes.
9. A commit `feat: walker [M04.2]` yields COMPLETES to M04.2 and TOUCHES to its changed files; a later `git reset --hard HEAD~1` removes that Commit node.
10. Editing a task line by hand between a claim and `complete_task` (ID kept) still ticks the right line; removing the line makes `complete_task` fail with `source_changed`.
11. The initial sync of a fresh store resolves links between files of the same batch whatever the order (a spec linking to a later spec, a `Blocks:` link to a later milestone), and records zero Events and no `changed_at` / `done_at`; a pre-ticked task is `done` with `done_at = null`.
12. `complete_milestone` on a milestone that another milestone links to moves the file to `done/`, rewrites that link, and the next sync shows zero unresolved links and zero `link_moved` warnings.
13. Hand-ticking a claimed task clears the claim; with `writeback = false`, a `complete_task` stays `done` after the file is re-synced.
