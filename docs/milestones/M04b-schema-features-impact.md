# M04b — Schema tables, features and impact

> **Depends on:** [M04a](done/M04a-code-and-git.md) · **Blocks:** [M05b](M05b-dashboard-impact-explain.md), [M06a](M06a-sample-and-exports.md)
> **Read first:** [SPEC-06 (whole file)](../specs/SPEC-06-code-context.md) · [SPEC-03 §3.3, §5.1, §6](../specs/SPEC-03-markdown-parsing.md#33-feature-line) · [SPEC-02 §3–4](../specs/SPEC-02-graph-schema.md#3-codebase-layer) · [SPEC-05 §4](../specs/SPEC-05-agent-tools.md#4-get_context)
> **Model:** Opusplan. Glob expansion and the fixed traversals with `via` chains. Write `M04b-plan.md` first.
> **Split from:** M04 (2026-11-21)

## Goal
Tables and columns from the schema spec, author-declared features and domains, backticked mentions and deviation `AFFECTS` links join the graph. `impact`, `explain` and `find_code` answer the multi-hop questions with the chain that connects each result, and `get_context` gains its code part.

## Tasks
### Layer
- [ ] **M04b.1** `parse/schema_tables.py` + upsert: Table, Column, `DEFINES_TABLE`, `HAS_COLUMN`, `REFERENCES` for both layouts ([SPEC-03 §6](../specs/SPEC-03-markdown-parsing.md#6-schema-tables)).
- [ ] **M04b.2** Feature lines into the graph, glob expansion on file add/remove (`src = walker`) ([SPEC-03 §3.3](../specs/SPEC-03-markdown-parsing.md#33-feature-line)).
- [ ] **M04b.3** `MENTIONS` from backticked table names and file paths in sections, tasks and deviations, and resolution of deviation **Affects:** entries ([SPEC-03 §3.2, §5.1](../specs/SPEC-03-markdown-parsing.md#32-sections)). (after M04b.1)
### Queries
- [ ] **M04b.4** `service/impact.py` over named queries in `graph/queries/*.cypher` (shared later with the static demo): target resolution, `impact`, `explain`, `find_code`, the presets ([SPEC-06](../specs/SPEC-06-code-context.md)). (after M04b.1, M04b.2, M04b.3)
- [ ] **M04b.5** MCP tools 11–13, endpoints 9–11 and 13, CLI `impact`, `explain`, `find`. (after M04b.4)
- [ ] **M04b.6** `get_context` code part: features, files, tables, recent commits ([SPEC-05 §4](../specs/SPEC-05-agent-tools.md#4-get_context) item 5). (after M04b.4)
### Tests
- [ ] **M04b.7** [SPEC-06 §6](../specs/SPEC-06-code-context.md#6-acceptance-checks) checks 1–7; [SPEC-03 §7](../specs/SPEC-03-markdown-parsing.md#7-acceptance-checks) checks 7, 8 (graph side) and 9.
- [ ] **M04b.8** Extend `test_spec01_ac02` and `test_spec01_ac03` to `sdd impact` (M02 tested them with `sdd status`). (after M04b.5)

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** on the fixture, `sdd impact documents` prints every group with `via` chains. On this repo, `sdd explain src/sdd/sync/git.py` names M04a.4 and its commit, and `sdd impact "SPEC-04 §6"` lists M04a and M04a.4. `sdd doctor --project /refs/office-suite --store :memory:` parses its schema tables with their `REFERENCES` (counts only in the Status line).
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
