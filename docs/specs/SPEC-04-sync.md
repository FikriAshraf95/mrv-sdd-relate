# SPEC-04 — Sync

> **Status:** v1 (2026-11-21) · **Owner of:** the watcher, incremental sync, deletes and renames, the code walker, git sync, write-back, loop prevention
> Shapes: [SPEC-02](SPEC-02-graph-schema.md) · Parsing: [SPEC-03](SPEC-03-markdown-parsing.md) · Writes go through the queue in [SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)

## 1. Watcher

- `SDD_WATCH` = `poll` | `native` | `auto` (default). `auto` uses polling when `/.dockerenv` exists, else native events. **Polling is required in Docker on Windows**: inotify sees none of the host's edits through a bind mount; polling sees all of them (verified 2026-11-21).
- Two poll intervals, because every poll stats every watched file and stats through a Windows bind mount are slow: `SDD_POLL_INTERVAL` (default 1 s) for the SDD document globs ([SPEC-03 §1](SPEC-03-markdown-parsing.md#1-rules-and-configuration)), and `SDD_POLL_CODE_INTERVAL` (default 10 s, a minimum) for the rest of the tree. **Measured in M02 (task M02.8, 2026-11-22, `scripts/measure_poll.py` inside the dev container, tree in the bind mount):** one code poll of 20 000 files in 200 folders took **26.6 s (min) / 30.1 s (median)** of 5 runs, about 1.5 ms per file; one SDD poll of this repo took 38.5 ms (min) / 39.1 ms (median). So `SDD_POLL_INTERVAL` stays **1 s**, and the code poll **backs off**: after each poll it waits `max(SDD_POLL_CODE_INTERVAL, 10 × that poll's duration)`, i.e. 10 s on a small tree and about 300 s on a 20 000-file tree through the mount (at most ~10% of a core). The two polls run on separate threads, so a slow code poll never delays an SDD edit (the tests use 0.1 s for both). Native mode watches everything with one observer.
- **What each poll does** (poll mode keeps one snapshot of `(mtime, size)` per path). The **SDD poll** stats every known SDD file and lists the *glob base directories*, the literal folder prefix of each SDD document glob in `paths` (`docs/milestones/` for `docs/milestones/**/M*.md`, `docs/specs/` for `docs/specs/SPEC-*.md`, the project root for `HANDOFF.md`), to find new files without walking the tree. A base followed by `**` is walked recursively, any other base is listed one level, and a glob whose base is the project root (`**/CLAUDE.md`) only lists the root folder. Nested matches such as `src/x/CLAUDE.md` are therefore found by the **code poll**, which walks the whole tree (pruned by the ignore rule below) and also keeps the snapshot current. A file that vanishes mid-poll counts as deleted.
- Detection is one thread; batches are handled on one dedicated thread, so they never overlap. An error in a batch is logged (path count only) and the watcher keeps running.
- Events are debounced for 300 ms and processed as one **batch**.
- Ignored: `.sdd/`, `.git/` (the git poller covers it) and every path the code walker ignores ([§4](#4-code-walker)). Both polls and the native handler share the walker's ignore rules; **the code poll re-reads every ignore file on each poll**, so a `.gitignore` edit takes effect on the next code poll (a path that became ignored leaves the snapshot and is reported as deleted).

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

- Walks the project root. It skips paths matched by `.gitignore` files (via `pathspec`), `.sddignore`, and the built-in list: `.git`, `.sdd`, `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `bin`, `obj`, `.next`, `coverage`, `target` (any path segment). **Only that list is built in: there is no blanket "dot names are skipped" rule**, so `.claude/`, `.github/` and `.gitignore` itself are walked.
- **Ignore files.** Each folder's own `.gitignore` applies to the paths beneath it, relative to that folder; the project root also reads `.sddignore` (gitignore syntax). Negation works within one file; **a deeper file cannot un-ignore what a shallower file ignored**. Ignored folders are not entered. The files are read lazily and cached until the next sync or code poll.
- Creates Folder and File nodes with `CONTAINS`. `language` comes from an extension map (and the names `Dockerfile` and `Makefile`; no match leaves the property absent); `is_test` from the `tests` globs ([SPEC-03 §1](SPEC-03-markdown-parsing.md#1-rules-and-configuration)); `lines` is the newline count (plus one for a last line without a newline) for files under 2 MB with no NUL byte in their first 8 KB, else absent. File contents are never stored.
- **Folders.** `dir:<path>` for every folder on the path of a kept file. There is **no root Folder**: top-level files and folders have no parent. A Folder left with no children is deleted after each sync, repeatedly up the tree.
- **Ownership.** The walker writes a File node for **every** walked file, SDD documents included (`path`, `name`, `language`, `size`, `lines`, `is_test`, `last_synced`), but **never sets `content_hash` on an SDD document**: the indexer sets that hash in phase 2 as the "fully synced" marker, and a hash set earlier would make it skip a changed document. The walker deletes only the File nodes of non-SDD paths; the indexer removes SDD documents. The indexer's own state reads (`read_state`, the link catalog fingerprint) are scoped to SDD documents, so code Files are never "removed" by the Markdown sync.
- **Write only differences.** The runtime keeps a cache of what each File node holds. A full sync reads the stored code layer once and diffs the walk against it; a watcher batch re-reads only its paths and diffs them against the cache. Unchanged files are not written, so re-syncing an unchanged repo writes nothing (check 2).
- A soft cap of 20 000 files (`SDD_MAX_FILES`) logs one warning (counts only) and keeps the first 20 000 by path. It also applies to a batch: when it would push the total over the cap, the union is capped the same way and the evicted paths are deleted.
- **Feature globs** are re-expanded when any file is added or removed, rebuilding `IMPLEMENTED_IN` for every feature (cheap; a feature with no matches gets a `feature_glob_empty` warning).
- **TESTS:** changed test files (files under 2 MB, read as UTF-8 with replacement) are scanned for `spec(\d+)_ac(\d+)` (case-insensitive). Each match links the file to `SPEC-<nn>#ac<n>` when it exists, with the numbers read as integers: `spec5_ac03` and `spec05_ac3` both mean `SPEC-05#ac3`. A full sync scans every test file, and so does any sync that created or deleted an AcceptanceCheck, so a check added later still gets its tests. A file's `TESTS` are rewritten only when the wanted set differs from the stored one; they carry `src = 'walker'`.
- Relate's own `fs-to-graph` extension is evaluated in M04a (open item O8). The default is this walker, because extensions run under a Relate host that would have to own the store, and our daemon already does.

## 5. Write-back

`sdd/sync/writeback.py` is the only module that edits Markdown. Every edit runs **inside the write job** that changes the graph, so the file and the graph change together, serialized with every other write.

### 5.1 Edits
| Trigger | Edit |
|---|---|
| `complete_task` | Find the line with `**<task id>**`; replace `[ ]` with `[x]`. Nothing else on the line changes |
| `log_deviation` | (1) Next number = highest D-number in the files **and** the index, + 1 (computed inside the job, so parallel agents never collide). (2) Write `docs/deviations/D<nnn>-<kebab-title>.md` from the template in `DEVIATIONS.md` (or the built-in one), with the task after the milestone in **Date / milestone:** and the resolved `affects` entries in **Affects:** ([SPEC-03 §5.1](SPEC-03-markdown-parsing.md#51-deviation-files)), so the links are rebuildable. (3) Insert the index row at the **top** of the index table, replacing a `*(none yet)*` placeholder row. (4) Append `> **DEVIATION:** see [D<nnn>](…) — <summary>` as the last line of each amended section's own body (before its first child heading), preceded by a blank line so it never joins a table, list or paragraph above it. When the whole spec is amended, the note goes at the end of the header blockquote, as its own `>` line |
| `complete_milestone` | Replace the `**Status:**` paragraph with `**Status:** DONE (<date>). <verification> Deviations: <list or none>.`; move the file (and its plan file) to `done/` if that folder exists, and **rewrite every relative link to the moved files** in the SDD documents (path part only; text and anchor unchanged), and re-base the moved files' own relative links on their new folder, in the same job |
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

- On startup, and when `git rev-parse HEAD` changes (polled every 3 s, which works through bind mounts). No git binary, not a repository, no commit yet, or a project that is a sub-folder of a larger repository: git sync is skipped (`git` is `null` in the sync result), never an error. Every git call is `git -c core.quotepath=off --no-optional-locks -C <root> …` with a 30 s timeout and no terminal prompt.
- New commits: `git log --reverse -n <max> --name-status --format=%x1e%H%x1f%P%x1f%an%x1f%aI%x1f%s <last>..HEAD` (records split on `\x1e`, fields on `\x1f`). **`author` is the name only, never the email** (the graph can be public). `at` is the author date in UTC (`…Z`). `message` is the subject. Name-status letters `A`, `M`, `D` are kept; `R*` is `R` (the new path is linked, both paths go into `paths`), `C*` is `A`, `T` is `M`. Merge commits list no files. The first sync is limited to the newest `SDD_GIT_MAX_COMMITS` (default 2000). `Meta.last_git_sha` is stored after each sync.
- **History rewritten** (`last_git_sha` is not an ancestor of HEAD: rebase, reset, branch switch): delete Commit nodes no longer reachable within the limit (`git rev-list -n <max> HEAD`), with every relationship whose `src` is `git:<that sha>` (`TOUCHES` is Task to File, so detaching the Commit does not remove it), and add the new ones. **The deletes run in their own write job, before the job that adds commits**: the engine panics when one transaction deletes a relationship it created. Relationships with `src = "tool"` are never touched.
- **The code step runs first.** The new commits' paths that exist, are not ignored and are not known to the code walker yet go through it before linking, so `CHANGED` and `TOUCHES` find the File nodes of files created in the same commit (the code poll alone waits at least 10 s, and a commit must show its links within 3 s).
- Per commit (written in jobs of about 200 commits, oldest first; the last job stores `Meta.last_git_sha`): Commit node, `PARENT` to parents already in the graph, `CHANGED {change}` to files that still exist (all paths stay in `Commit.paths`), `COMPLETES` for each `[M02.3]`, `PART_OF` for `(M20f)` (or a bare `M20f`) when no task ID is present. Then `TOUCHES` from each completed task to the commit's changed files. Every relationship gets `src = "git:<sha>"`. **A Task or Milestone that does not exist at sync time gets no link and no `unresolved` entry.** Commits create no Events.
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
