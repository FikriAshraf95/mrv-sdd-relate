# D007 — Sample's graph packet is 61% smaller than the Markdown rule, not 70%

- **Date / milestone:** 2026-11-22 · M07 · M07.1
- **Spec:** [SPEC-00 §7](../specs/SPEC-00-overview.md#7-success-criteria)
- **Affects:** `bench/results/2026-11-22.json`, `bench/results/self/2026-11-22.json`
- **Status:** Open

## Spec says
Success criterion 4: on the sample project the average get_context packet is at least 70% smaller than the Markdown an agent reads by the token rule.

## Implementation does
sdd bench context on samples/courtside measures 61.2% (30 tasks, 8034 chars of Markdown vs 3118 per task packet; the milestone-detail packet is 40.2% smaller). The same bench on this repo's own M04b, M05a and M06b gives 71.9% (52954 vs 14854 chars). Nothing was tuned to move the number.

## Why
Courtside's specs are short (a few KB each), so the Markdown baseline is only about 8 KB and the packet's fixed parts (task, milestone goal, checks, code, JSON framing) are a larger share of it. The saving grows with spec size.

## Consequences
The README quotes both numbers and says which project each is from. The 70% claim holds only for projects with larger specs.
