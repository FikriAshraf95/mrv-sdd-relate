# M01a — Markdown parsers

> **Depends on:** [M00b](M00b-relate-access-layer.md) · **Blocks:** [M01b](M01b-graph-sync.md)
> **Read first:** [SPEC-03 (whole file)](../../specs/SPEC-03-markdown-parsing.md) · [SPEC-02 §1–2](../../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties) · [SPEC-10 §3](../../specs/SPEC-10-testing-and-benchmark.md#3-fixtures)
> **Model:** Opusplan. Two real formats and a reference grammar with ranges, slugs and code-span rules. Write `M01a-plan.md` first.
> **Split from:** M01 (2026-11-21)

## Goal
Pure parsers (text in, parsed objects and warnings out, no I/O, no graph) for specs, milestones, deviations, plans and docs, in both reference formats and this tool's own, tested against invented fixtures. Nothing touches the store yet (M01b).

## Tasks
### Fixtures
- [x] **M01a.1** `tests/fixtures/rag_style/`, `suite_style/` and the docs part of `tool_style/`, written to mirror each format with invented content; nothing copied from the reference projects ([SPEC-10 §3](../../specs/SPEC-10-testing-and-benchmark.md#3-fixtures)).
### Parsers
- [x] **M01a.2** `parse/links.py`: relative links and anchors, the moved-file rule, the spec-reference grammar with ranges, title slugs (numbered or not), descendants and notes, and the code-span rule ([SPEC-03 §1–2](../../specs/SPEC-03-markdown-parsing.md#2-links-and-spec-references)).
- [x] **M01a.3** `parse/specs.py`: header, sections with own-text hashes, acceptance checks, DEVIATION notes at any depth (outside code), Feature lines kept raw ([SPEC-03 §3](../../specs/SPEC-03-markdown-parsing.md#3-specs)). (after M01a.2)
- [x] **M01a.4** `parse/milestones.py`: header lines, task IDs, legacy positional IDs, `(after …)`, groups, multi-line tasks, `checked`, goal, acceptance, status ([SPEC-03 §4](../../specs/SPEC-03-markdown-parsing.md#4-milestones-and-tasks)). (after M01a.2)
- [x] **M01a.5** `parse/deviations.py` (files with the optional task and **Affects:** fields, index cross-check) and `parse/docs.py` (docs and plans) ([SPEC-03 §5](../../specs/SPEC-03-markdown-parsing.md#5-deviations-and-docs)). (after M01a.2)
### Tests
- [x] **M01a.6** [SPEC-03 §7](../../specs/SPEC-03-markdown-parsing.md#7-acceptance-checks) checks 1–6 and 8, parse side (the graph side follows in M01b, and for check 8 in M04b; checks 7 and 9 need tables and files, so they are tested in M04b).

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (read-only references):** a throwaway script (not committed) runs every parser over `/refs/office-rag/docs` and `/refs/office-suite/docs` and over this repo's `docs/`; zero `error` warnings, and the counts per warning code are recorded in the Status line (counts only, no reference content).
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-21). Built by a Sonnet subagent from [M01a-plan.md](M01a-plan.md), reviewed by Opus. Verified in the dev container: `ruff check`, `ruff format --check`, `mypy --strict src/sdd`, `lint-imports` (13 contracts kept) and `pytest -q` (267 passed, 72 in `tests/spec03/`; checks 1–6 and 8 are `test_spec03_ac0N_*`). A 7-word overlap scan of the fixtures against both reference projects found only shared conventions; one office-suite phrase was reworded. Walkthrough (throwaway script, counts only), zero `error` everywhere: office-rag: 12 specs, 11 milestones, 3 docs, index; `task_unstable_id` 98; 6 unresolved (3 to unparsed files, 3 dangling in the reference itself). office-suite: 27 specs, 29 milestones, 4 plans, 23 deviations, 3 docs, index; `task_unstable_id` 491; no `deviation_index_mismatch`; 5 unresolved (4 to unparsed files, 1 slug). This repo: 12 specs, 16 milestones, 1 plan, 1 deviation, 4 docs, index; no warnings; 18 unresolved, all links to code and decision files (File nodes, M04a). Review fixes: example references in SPEC-02/03/05/10 used backslash-escaped backticks inside code spans (not valid Markdown), so they leaked as links; now double-backtick spans. Spec additions (not deviations): the warning-code table in SPEC-03 §1, and `Doc` as a `LINKS_TO` source in SPEC-02 §4. Deviations: none.
