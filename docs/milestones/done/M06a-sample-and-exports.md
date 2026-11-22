# M06a — Invented sample project and exports

> **Depends on:** [M04b](M04b-schema-features-impact.md), [M05b](M05b-dashboard-impact-explain.md) · **Blocks:** [M06b](M06b-public-replay-deploy.md)
> **Read first:** [SPEC-11 §5, §8](../../specs/SPEC-11-deployment-and-demo.md#5-sample-project) · [SPEC-08 §3](../../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots) · [SPEC-06 §5](../../specs/SPEC-06-code-context.md#5-presets) · [SPEC-10 §3](../../specs/SPEC-10-testing-and-benchmark.md#3-fixtures) · [DEC-004](../../decisions/DEC-004-sample-fallback.md)
> **Model:** Opusplan. The sample's story decides how good the demo looks; snapshots depend on open item O3. Write `M06a-plan.md` first. Plan: [M06a-plan](M06a-plan.md).
> **Split from:** M06 (2026-11-21)

## Goal
The project judges explore: an invented, believable SDD repo in the office-suite format, with a designed centrepiece table whose `impact` shows every kind of link. Plus the exports and snapshots that let judges read the graph without running anything. Nothing from office-suite-v2.

## Tasks
### Sample
- [x] **M06a.1** `samples/<name>/` docs: about 6 specs (one schema spec with 6–8 tables), 8 milestones (some done, some letter-suffixed, one with a plan file) with task IDs, about 6 deviations, Feature lines, and a story where one table is touched by several specs, milestones and deviations ([SPEC-11 §5](../../specs/SPEC-11-deployment-and-demo.md#5-sample-project)).
- [x] **M06a.2** The sample's placeholder code tree (small files grouped by feature, tests named after checks) and `scripts/make_sample.py`: a scripted linear git history as `samples/<name>.bundle` with commits naming tasks, then `sdd sync` and `sdd snapshot`. (after M06a.1, M06a.3)
### Exports
- [x] **M06a.3** `sdd export --mermaid | --cypher | --json | --claude-status`; endpoint 15. Resolve open item O3 and implement `sdd snapshot` ([SPEC-08 §3](../../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots)).
- [x] **M06a.4** Commit the sample's built store with its snapshot copies, and this repo's `sdd snapshot` output (never its live `.sdd/graph/`) ([SPEC-08 §3](../../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots)). (after M06a.2)
### Impact
- [x] **M06a.6** Table `impact` also returns the Commits that `COMPLETES` its Tasks, so the centrepiece shows every group ([SPEC-06 §2](../../specs/SPEC-06-code-context.md#2-impact)).
### Tests
- [x] **M06a.5** [SPEC-08 §4](../../specs/SPEC-08-cli-and-exports.md#4-acceptance-checks) checks 4–7.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** `sdd doctor --project samples/<name> --store :memory:` reports zero warnings; `sdd impact <centrepiece table>` on the sample returns every group (specs, sections, tables, features, files, open and done tasks, deviations, tests, commits) with `via` chains; the dashboard on the sample shows it; the Mermaid `schema` export renders on GitHub (checked by hand once pushed).
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-22). 617 tests and full gates green; walkthrough on Opus: sdd doctor on samples/courtside 0 warnings, sdd impact bookings fills all 10 groups (specs 5, sections 6, tables 11, features 5, files 16, tasks open 3/done 7, deviations 4, tests 4, commits 11) with via chains, dashboard Impact view on a sample copy shows it, /api/mermaid serves presets; O3 closed (relate CLI only); review fixed the bundle to carry HEAD. Mermaid render on GitHub pending the push. Deviations: none.
