# M01b — Graph upsert and full sync

> **Depends on:** [M01a](M01a-markdown-parsers.md) · **Blocks:** [M02](../M02-sync-daemon.md)
> **Read first:** [SPEC-02 §1–2, §4–5, §7](../../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties) · [SPEC-04 §2–3](../../specs/SPEC-04-sync.md#2-incremental-sync) · [SPEC-08 §1–2](../../specs/SPEC-08-cli-and-exports.md#1-rules) · [SPEC-10 §4](../../specs/SPEC-10-testing-and-benchmark.md#4-invariant-suite)
> **Model:** Opusplan. Two-phase transactional upserts, `src` ownership and the Task upsert rules that keep graph-only state. Write `M01b-plan.md` first.
> **Split from:** M01 (2026-11-21)

## Goal
`sdd sync` turns the parsed documents into the planning layer of the graph for both reference formats and this repo's own docs, with deletes, renames and re-linking handled. `sdd doctor` reports what it could not parse or resolve. No watcher and no daemon yet.

## Tasks
### Graph and sync
- [x] **M01b.1** `graph/upsert.py`: two phases per batch (nodes, then relationships, one transaction per file each), `src`-owned relationships replaced, the Task upsert rules for graph-only properties, File nodes for SDD documents, `unresolved` lists, Meta node ([SPEC-02 §4–5](../../specs/SPEC-02-graph-schema.md#4-relationships), [SPEC-04 §2.1](../../specs/SPEC-04-sync.md#21-task-upsert-rules)).
- [x] **M01b.2** `sync/indexer.py`: full scan of SDD Markdown, the initial-sync rule (no Events), re-link everything when the ID set changes, deletes and renames that keep IDs produced elsewhere in the batch ([SPEC-04 §2–3](../../specs/SPEC-04-sync.md#2-incremental-sync)). (after M01b.1)
### CLI
- [x] **M01b.3** `sdd sync [--reset]`, `sdd status`, `sdd doctor`, with `--store :memory:` ([SPEC-08 §1–2](../../specs/SPEC-08-cli-and-exports.md#1-rules)). (after M01b.2)
- [x] **M01b.4** `sdd ids --write` for legacy task lines (through `sync/writeback.py`'s atomic write helper, which M02 extends). (after M01b.3)
### Tests
- [x] **M01b.5** [SPEC-03 §7](../../specs/SPEC-03-markdown-parsing.md#7-acceptance-checks) checks 1–6, graph side (check 8's graph side needs Feature nodes: M04b); [SPEC-02 §8](../../specs/SPEC-02-graph-schema.md#8-acceptance-checks) checks 2–4; [SPEC-04 §7](../../specs/SPEC-04-sync.md#7-acceptance-checks) checks 2–5 and 11 (through `sdd sync`); [SPEC-08 §4](../../specs/SPEC-08-cli-and-exports.md#4-acceptance-checks) check 3; invariants 2 and 3.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (read-only references):** `sdd doctor --project /refs/office-rag --store :memory:` and the same for `/refs/office-suite` report zero `error` warnings; record the counts (specs, sections, milestones, tasks, deviations, legacy task lines, unresolved links) in the Status line. `sdd sync` on **this repo** reports zero warnings, and `sdd status` lists every milestone (M00a to M99) with its tasks.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-22). Built on Sonnet from [M01b-plan](M01b-plan.md), reviewed on Opus (the File hash now moves in phase 2, so a sync stopped between the phases redoes the file; regression test added). Verified: 317 tests and all gates green; `sdd doctor --store :memory:` on office-rag: 12 specs, 125 sections, 11 milestones, 98 tasks, 0 deviations, 98 legacy task lines, 6 unresolved links, 0 errors; on office-suite: 27 specs, 419 sections, 29 milestones, 491 tasks, 23 deviations, 491 legacy task lines, 4 unresolved links, 0 errors (all warnings `task_unstable_id`); `sdd sync` on this repo: 0 warnings, 20 unresolved links (code files, decisions and folders, which get nodes from M04a), a second sync relinks nothing; `sdd status` lists M00a to M99 with their tasks. Deviations: [D002](../../deviations/D002-reset-empties-store-in-place.md), [D003](../../deviations/D003-relink-on-catalog-change.md).
