# M04a — Code and git layer

> **Depends on:** [M03b](M03b-context-and-integration.md) · **Blocks:** [M04b](M04b-schema-features-impact.md)
> **Read first:** [SPEC-02 §3–4, §7](../../specs/SPEC-02-graph-schema.md#3-codebase-layer) · [SPEC-04 §2, §4, §6](../../specs/SPEC-04-sync.md#2-incremental-sync) · [SPEC-03 §1](../../specs/SPEC-03-markdown-parsing.md#1-rules-and-configuration)
> **Model:** Opusplan. Ignore rules, git history rewrites and `src = git:<sha>` ownership. Write `M04a-plan.md` first.
> **Split from:** M04 (2026-11-21)

## Goal
The graph knows the code and its history: folders and files (no contents), git commits linked to the tasks and milestones they complete, and test files linked to the spec checks they test. The schema, feature and impact layer follows in M04b.

## Tasks
### Fixture
- [x] **M04a.1** Complete the `tool_style` fixture for M04a and M04b: a code tree, tests named after checks, a scripted git history with task IDs in messages, and a schema spec with tables `documents` and `chunks` (`chunks.document_id → documents`) plus a Feature `ingestion` whose globs match part of the code tree. SPEC-06's checks run on it.
### Code layer
- [x] **M04a.2** `sync/files.py`: walker with `.gitignore`, `.sddignore` and the built-in skips; Folder/File (in sync phase 1); `language`; `is_test`; soft cap; the code poll interval ([SPEC-04 §4](../../specs/SPEC-04-sync.md#4-code-walker)). Evaluate Relate's `fs-to-graph` (open item O8) and record the decision in SPEC-00 §8. (after M04a.1)
- [x] **M04a.6** Keep the SDD indexer from treating code Files as its own: M01b's `upsert.read_state` takes every `File` with a `content_hash` as an SDD document, so the Markdown full sync would delete code Files as "removed". Scope `read_state` / removals to the SDD globs (or the walker's set) before code Files carry hashes. (after M04a.2)
- [x] **M04a.3** `TESTS` scan of test files, numbers read as integers ([SPEC-04 §4](../../specs/SPEC-04-sync.md#4-code-walker)). (after M04a.2)
- [x] **M04a.4** `sync/git.py`: incremental log, history rewrite handling, `COMPLETES`, `PART_OF`, `TOUCHES` (all `src = git:<sha>`), HEAD polling ([SPEC-04 §6](../../specs/SPEC-04-sync.md#6-git-sync)). (after M04a.2)
### Tests
- [x] **M04a.5** [SPEC-04 §7](../../specs/SPEC-04-sync.md#7-acceptance-checks) checks 8–9; [SPEC-02 §8](../../specs/SPEC-02-graph-schema.md#8-acceptance-checks) check 5; a tool-owned `TOUCHES` survives a `git reset --hard` that removes the commit-owned one.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (this repo):** `sdd info` shows Folder, File and Commit counts; a commit named `[M04a.4]` yields COMPLETES to M04a.4 and TOUCHES to its files within 3 s of the commit; `node_modules/` and `.venv/` produce no File nodes.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-21). Built by sonnet-1 from M04a-plan.md and reviewed by Opus (files.py, git.py, pipeline.py, graph/code.py, indexer scoping, runtime, watcher, daemon, spec edits). Gates: ruff check, ruff format --check, mypy, lint-imports (13 kept) and pytest (535 passed), including SPEC-04 checks 8–9, SPEC-02 check 5 and tool-owned TOUCHES surviving git reset --hard. Walkthrough on this repo with the restarted daemon: sdd info shows Folder 32, File 172, Commit 10. node_modules/ and .venv/ created live produced no File nodes (a control file was indexed in about 2 s). Commit 64eec36 [M04a.1]…[M04a.6] was committed at 23:39:36Z and linked at 23:39:39Z (Commit.last_synced) with COMPLETES to all six tasks and 38 git-owned TOUCHES. Deviations: none.
