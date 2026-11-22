# M07 — Benchmark

> **Depends on:** [M06b](done/M06b-public-replay-deploy.md) · **Blocks:** [M99](M99-release-and-submission.md)
> **Read first:** [SPEC-10 §5, §7](../specs/SPEC-10-testing-and-benchmark.md#5-benchmark) · [SPEC-05 §4](../specs/SPEC-05-agent-tools.md#4-get_context) · [SPEC-00 §7](../specs/SPEC-00-overview.md#7-success-criteria)
> **Model:** Sonnet. A measurement script over existing tools.

## Goal
Numbers for the README's opening: how much less an agent reads per task and per session restart, and how many write collisions disappear, measured reproducibly on the sample project.

## Tasks
- [ ] **M07.1** `sdd bench context`: the three variants per task, chars and estimated tokens, `--exact` with the token-counting API ([SPEC-10 §5.1](../specs/SPEC-10-testing-and-benchmark.md#51-context-per-task)).
- [ ] **M07.2** `sdd bench restart` with the scripted edit set ([SPEC-10 §5.2](../specs/SPEC-10-testing-and-benchmark.md#52-session-restart)).
- [ ] **M07.3** `sdd bench collisions` ([SPEC-10 §5.3](../specs/SPEC-10-testing-and-benchmark.md#53-parallel-collisions)).
- [ ] **M07.4** Results to `bench/results/<date>.json` and `.md`; a README table draft. (after M07.1, M07.2, M07.3)
- [ ] **M07.5** Tests: [SPEC-10 §7](../specs/SPEC-10-testing-and-benchmark.md#7-acceptance-checks) checks 3–4.
- [ ] **M07.6** *(optional)* The live run ([SPEC-10 §5.4](../specs/SPEC-10-testing-and-benchmark.md#54-live-run-optional-stretch)).

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** run all three benches on the committed sample; success criterion 4 ([SPEC-00 §7](../specs/SPEC-00-overview.md#7-success-criteria)) is met, or the gap is explained and logged as a deviation. Results committed.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
