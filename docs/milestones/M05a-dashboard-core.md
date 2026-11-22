# M05a — Dashboard: shell, Board, Graph and Query

> **Depends on:** [M03b](done/M03b-context-and-integration.md) · **Blocks:** [M05b](M05b-dashboard-impact-explain.md)
> **Read first:** [SPEC-07 (whole file)](../specs/SPEC-07-dashboard-and-api.md) · [SPEC-11 §6](../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)
> **Model:** Sonnet. Plain static UI over existing endpoints. Can run in a parallel session with M04a/M04b once M03b is done.
> **Split from:** M05 (2026-11-21)

## Goal
A static dashboard served by the daemon that judges understand in seconds: a live milestone Board (the demo video's main shot), an explorable Graph and a read-only Query box. No build step, no framework, no external requests. Impact and Explain follow in M05b, once M04b provides their endpoints.

## Tasks
- [x] **M05a.1** `web/static/`: shell with five tabs (Impact and Explain as placeholders), hash routing with encoded IDs, colour tokens, light and dark themes, works from 360 px; vendored `cytoscape.min.js` ([SPEC-07 §1, §4](../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views)).
- [x] **M05a.2** `api.js` data adapter with the HTTP backend (the static and WASM backends come in M08). (after M05a.1)
- [x] **M05a.3** Board: milestone picker, three columns, agent chips, live moves over SSE with highlight, polling fallback, event ticker. (after M05a.2)
- [x] **M05a.4** Graph over `/api/graph`: label filter, search, side panel, expand on double-click, *Reset* (presets come with endpoint 13 in M05b). (after M05a.2)
- [x] **M05a.5** Query: Cypher box, a few built-in example queries, results table, *Show as graph* (presets and presets-only mode in M05b). (after M05a.2)
- [x] **M05a.6** Tests: [SPEC-07 §5](../specs/SPEC-07-dashboard-and-api.md#5-acceptance-checks) checks 2, 3, 5, 6 and 7 (deep-link part); the static smoke test ([SPEC-10 §6](../specs/SPEC-10-testing-and-benchmark.md#6-gates)).

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** daemon on the `tool_style` fixture → open `http://localhost:8770` → claim and complete a task with `sdd claim` / `sdd done` and watch the card move → explore the graph → run an example query. Check light and dark and a 360 px window.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
