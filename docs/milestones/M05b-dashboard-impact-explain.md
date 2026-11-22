# M05b — Dashboard: Impact and Explain

> **Depends on:** [M04b](done/M04b-schema-features-impact.md), [M05a](done/M05a-dashboard-core.md) · **Blocks:** [M06a](M06a-sample-and-exports.md)
> **Read first:** [SPEC-07 §4–5](../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views) · [SPEC-06 §2–3, §5](../specs/SPEC-06-code-context.md#2-impact)
> **Model:** Sonnet. Two views over the M04b endpoints.
> **Split from:** M05 (2026-11-21)

## Goal
The two views that show what only a graph can: Impact draws every affected item around a target with the chain that connects it, and Explain shows why a file exists. Together with the Board, these are the demo's key screens. The named presets join the Graph and Query tabs.

## Tasks
- [ ] **M05b.1** Impact: target autocomplete (tables, sections, files, features), `ambiguous_target` candidates as choices, grouped lists, centred graph, chain highlight on click.
- [ ] **M05b.2** Explain: searchable file tree, summary, layered chain graph.
- [ ] **M05b.3** Presets (endpoint 13) in the Graph tab (opening on `schema` or a milestone) and the Query tab (as examples, and the presets-only mode for `SDD_PUBLIC_QUERY=presets`). (after M05b.1)
- [ ] **M05b.4** Tests: the static smoke test covers the new files; [SPEC-07 §5](../specs/SPEC-07-dashboard-and-api.md#5-acceptance-checks) check 4 by hand.
- [ ] **M05b.5** Dashboard under `SDD_TOKEN` ([SPEC-09 §2](../specs/SPEC-09-security.md#2-local-daemon) rule 2, [SPEC-07 §1](../specs/SPEC-07-dashboard-and-api.md#1-rules) rule 5): `api.js` sends `Authorization: Bearer` from `sessionStorage` (try/catch) and skips `EventSource` when a token is set, so the Board polls; on `unauthorized` the shell shows one password field and re-renders; a "Forget token" link clears it. Tests: with a token, `/` and the static files return 200 and `/api/board` returns 401 (SPEC-09 §6 check 2), plus source pins for the header and the polling switch.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** daemon on the `tool_style` fixture → Impact on `documents`, click a chain → Explain a file → the `lineage:` preset on a section with a deviation. Check light and dark and a 360 px window. Take screenshots of all five tabs for the README.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
