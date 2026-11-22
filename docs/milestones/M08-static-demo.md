# M08 — Static demo on GitHub Pages *(cut first if late)*

> **Depends on:** [M06b](done/M06b-public-replay-deploy.md) · **Blocks:** nothing (M99 links it if it exists)
> **Read first:** [SPEC-11 §6](../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages) · [SPEC-07 §1, §4](../specs/SPEC-07-dashboard-and-api.md#1-rules) · [SPEC-08 §3](../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots)
> **Model:** Opusplan. Relate's WASM build is unverified (open item O2); the fallback must be ready first.

## Goal
A zero-install demo that is always up: judges click a README link and explore the sample graph in the browser, with Relate running in WebAssembly where possible and precomputed answers otherwise.

## Tasks
- [x] **M08.1** Precomputed answers for the presets and demo targets, and a `static` adapter backend that serves them. This is the fallback, built first.
- [x] **M08.2** GitHub Actions workflow: build `site/` (dashboard + exports + precomputed answers) and publish to Pages. (after M08.1)
- [x] **M08.3** Resolve open item O2: find the Relate WASM package, measure loading the sample's Cypher and JSON exports; record the result in SPEC-00 §8.
- [x] **M08.4** WASM adapter backend running the shared `graph/queries/*.cypher`; the Query tab runs guarded Cypher in the browser. (after M08.3)
- [x] **M08.5** Board *Replay* button animating the recorded events.
- [x] **M08.6** Tests: [SPEC-11 §9](../specs/SPEC-11-deployment-and-demo.md#9-acceptance-checks) check 5 (by hand on the published site).

## Acceptance criteria
1. The Pages site loads on desktop and phone, and the Impact view works for the centrepiece target with no backend.
2. Which backend runs (WASM or precomputed) is visible in the footer and stated in the README.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
