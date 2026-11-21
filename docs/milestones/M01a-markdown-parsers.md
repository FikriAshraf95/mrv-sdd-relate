# M01a — Markdown parsers

> **Depends on:** [M00b](done/M00b-relate-access-layer.md) · **Blocks:** [M01b](M01b-graph-sync.md)
> **Read first:** [SPEC-03 (whole file)](../specs/SPEC-03-markdown-parsing.md) · [SPEC-02 §1–2](../specs/SPEC-02-graph-schema.md#1-ids-and-common-properties) · [SPEC-10 §3](../specs/SPEC-10-testing-and-benchmark.md#3-fixtures)
> **Model:** Opusplan. Two real formats and a reference grammar with ranges, slugs and code-span rules. Write `M01a-plan.md` first.
> **Split from:** M01 (2026-11-21)

## Goal
Pure parsers (text in, parsed objects and warnings out, no I/O, no graph) for specs, milestones, deviations, plans and docs, in both reference formats and this tool's own, tested against invented fixtures. Nothing touches the store yet (M01b).

## Tasks
### Fixtures
- [ ] **M01a.1** `tests/fixtures/rag_style/`, `suite_style/` and the docs part of `tool_style/`, written to mirror each format with invented content; nothing copied from the reference projects ([SPEC-10 §3](../specs/SPEC-10-testing-and-benchmark.md#3-fixtures)).
### Parsers
- [ ] **M01a.2** `parse/links.py`: relative links and anchors, the moved-file rule, the spec-reference grammar with ranges, title slugs (numbered or not), descendants and notes, and the code-span rule ([SPEC-03 §1–2](../specs/SPEC-03-markdown-parsing.md#2-links-and-spec-references)).
- [ ] **M01a.3** `parse/specs.py`: header, sections with own-text hashes, acceptance checks, DEVIATION notes at any depth (outside code), Feature lines kept raw ([SPEC-03 §3](../specs/SPEC-03-markdown-parsing.md#3-specs)). (after M01a.2)
- [ ] **M01a.4** `parse/milestones.py`: header lines, task IDs, legacy positional IDs, `(after …)`, groups, multi-line tasks, `checked`, goal, acceptance, status ([SPEC-03 §4](../specs/SPEC-03-markdown-parsing.md#4-milestones-and-tasks)). (after M01a.2)
- [ ] **M01a.5** `parse/deviations.py` (files with the optional task and **Affects:** fields, index cross-check) and `parse/docs.py` (docs and plans) ([SPEC-03 §5](../specs/SPEC-03-markdown-parsing.md#5-deviations-and-docs)). (after M01a.2)
### Tests
- [ ] **M01a.6** [SPEC-03 §7](../specs/SPEC-03-markdown-parsing.md#7-acceptance-checks) checks 1–6 and 8, parse side (the graph side follows in M01b, and for check 8 in M04b; checks 7 and 9 need tables and files, so they are tested in M04b).

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (read-only references):** a throwaway script (not committed) runs every parser over `/refs/office-rag/docs` and `/refs/office-suite/docs` and over this repo's `docs/`; zero `error` warnings, and the counts per warning code are recorded in the Status line (counts only, no reference content).
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
