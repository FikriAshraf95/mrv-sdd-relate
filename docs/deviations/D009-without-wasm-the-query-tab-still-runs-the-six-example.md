# D009 — Without WASM the Query tab still runs the six example queries

- **Date / milestone:** 2026-11-22 · M08 · M08.4
- **Spec:** [SPEC-11 §6](../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)
- **Affects:** `src/sdd/web/static/query.js`, `src/sdd/web/static/static.js`
- **Status:** Open

## Spec says
If the WASM build is unavailable or too slow, the adapter serves the precomputed answers, and the Query tab offers presets only.

## Implementation does
The precomputed backend also answers the Query tab's six example queries (exact text match, run through the query guard at build time) and the two follow-up queries behind Show as graph; any other Cypher is refused with query_rejected. The presets work as before.

## Why
Presets-only would hide the Run button and make the examples unusable, although their answers are in data/ and cost nothing; the Query tab stays useful without WebAssembly.

## Consequences
The Query tab in the precomputed fallback shows a note that only the examples and presets run; health.json keeps public_query presets, and the adapter reports guarded once WASM is up.
