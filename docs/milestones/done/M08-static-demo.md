# M08 — Static demo on GitHub Pages *(cut first if late)*

> **Depends on:** [M06b](M06b-public-replay-deploy.md) · **Blocks:** nothing (M99 links it if it exists)
> **Read first:** [SPEC-11 §6](../../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages) · [SPEC-07 §1, §4](../../specs/SPEC-07-dashboard-and-api.md#1-rules) · [SPEC-08 §3](../../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots)
> **Model:** Opusplan. Relate's WASM build is unverified (open item O2); the fallback must be ready first.

## Goal
A zero-install demo that is always up: judges click a README link and explore the sample graph in the browser, with Relate running in WebAssembly where possible and precomputed answers otherwise.

## Tasks
- [x] **M08.1** Precomputed answers for the presets and demo targets, and a `static` adapter backend that serves them. This is the fallback, built first.
- [x] **M08.2** GitHub Actions workflow: build `site/` (dashboard + exports + precomputed answers) and publish to Pages. (after M08.1)
- [x] **M08.3** Resolve open item O2: find the Relate WASM package, measure loading the sample's Cypher and JSON exports; record the result in SPEC-00 §8.
- [x] **M08.4** WASM adapter backend running the shared `graph/queries/*.cypher`; the Query tab runs guarded Cypher in the browser. (after M08.3)
- [x] **M08.5** Board *Replay* button animating the recorded events.
- [x] **M08.6** Tests: [SPEC-11 §9](../../specs/SPEC-11-deployment-and-demo.md#9-acceptance-checks) check 5 (by hand on the published site).

## Acceptance criteria
1. The Pages site loads on desktop and phone, and the Impact view works for the centrepiece target with no backend.
2. Which backend runs (WASM or precomputed) is visible in the footer and stated in the README.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-22). Live at https://fikriashraf95.github.io/mrv-sdd-relate/ (pages.yml run on push): the user saw the Board load with the footer "Static demo · Relate WASM 1.2.0 · 282 nodes loaded in 2081 ms"; Opus fetched data/index.json and the Impact answer for table:bookings from Pages (11 groups, 72 items) and the 7.2 MB relate_bg.wasm. Before the push, a headless Chromium (Playwright 1.49) check under the /mrv-sdd-relate/ sub-path at 1280x800 and 390x844 covered Impact for table:bookings, the Query tab in WASM (count 282, writes rejected, 5 s timeout with worker respawn), Replay, and the fallback without WASM (footer "precomputed answers", Impact still works). README states the backend rule. Gates green, 678 tests passed. Planned on Opus, built on Sonnet, reviewed on Opus (one fix: Cypher moved out of site.py into the what_changed service call). Deviations: D008, D009.
