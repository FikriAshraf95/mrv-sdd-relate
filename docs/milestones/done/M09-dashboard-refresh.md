# M09 — Dashboard refresh and 3D graph

> **Depends on:** [M08](M08-static-demo.md) · **Blocks:** [M99](../M99-release-and-submission.md) (its README GIF and screenshots show this dashboard)
> **Read first:** [SPEC-07 §1, §4, §5](../../specs/SPEC-07-dashboard-and-api.md#1-rules) · [SPEC-09 §4](../../specs/SPEC-09-security.md#4-public-mode) · [SPEC-11 §6](../../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages) · [SPEC-01 §6](../../specs/SPEC-01-architecture.md#6-dependencies)
> **Model:** Opusplan. A visual design pass plus a WebGL renderer under the public CSP; the plan is [M09-plan.md](M09-plan.md).

## Goal
A dashboard that looks finished: dark by default with a light theme, a calmer layout, a livelier Board, and a Graph tab that opens on a 3D view of the whole graph (three.js, force layout in a worker) with a 2D toggle. Still no framework and no build step: libraries are vendored files under `web/static/vendor/`, so the daemon, `sdd public` and the static demo serve the same folder as before.

## Tasks
### Foundations
- [x] **M09.1** `scripts/vendor_web.sh`: fetch pinned npm tarballs in the dev container, check each sha512, copy three.js (core, `OrbitControls`, `CSS2DRenderer`), d3-force-3d and its d3 dependencies, and the Inter and JetBrains Mono woff2 files into `vendor/`, rewriting bare imports to relative paths, with every licence and a `vendor/MANIFEST.json` (package, version, sha512, files). Update the dashboard dependency line of [SPEC-01 §6](../../specs/SPEC-01-architecture.md#6-dependencies).
- [x] **M09.2** Design tokens and the page shell: dark default plus light (`prefers-color-scheme` only picks light when the user has not toggled), one palette per label shared by every view, typography from the vendored fonts, header, tabs, side panel, footer, empty and loading states, `prefers-reduced-motion`. Update the *Look* paragraph of [SPEC-07 §4](../../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views). (after M09.1)
### Views
- [x] **M09.3** Graph tab in 3D: `graph3d.js` (three.js scene, instanced nodes sized by degree and coloured by label, edges as line segments, orbit controls, hover label, click opens the side panel, double-click flies to the node and expands its neighbours, search flies to a match, label filter) and `graph-layout.worker.js` (d3-force-3d, positions posted as a `Float32Array`). A 2D/3D toggle keeps the Cytoscape view, which is also the fallback without WebGL. Update item 2 of [SPEC-07 §4](../../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views). (after M09.2)
- [x] **M09.4** Board: a progress bar per milestone, agent chips with a stable colour per agent name, cards that move with a short transition, a clearer event ticker; the Replay button of the static demo still drives it ([SPEC-07 §4](../../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views) item 1). (after M09.2)
- [x] **M09.5** Impact, Explain and Query restyled on the new tokens: Cytoscape styles read the shared label palette, grouped lists and the results table get the new type scale ([SPEC-07 §4](../../specs/SPEC-07-dashboard-and-api.md#4-dashboard-views) items 3–5). (after M09.2)
### Checks
- [x] **M09.6** Every mode works: the daemon, `sdd public` under its CSP ([SPEC-09 §4](../../specs/SPEC-09-security.md#4-public-mode)) with no console errors, and `sdd site` under the Pages sub-path with both backends ([SPEC-11 §6](../../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)); 1280x800 and 390x844; WebGL turned off falls back to 2D. (after M09.3, M09.4, M09.5)
- [x] **M09.7** Tests: [SPEC-07 §5](../../specs/SPEC-07-dashboard-and-api.md#5-acceptance-checks) checks 6 and 7 still pass with the new modules; every vendored file is listed in `MANIFEST.json` with a licence; the own-files CSP rules cover `graph3d.js` and the worker; gates green. (after M09.3, M09.4, M09.5)
- [x] **M09.8** Screenshots: retake `docs/screenshots/` and `docs/manuals/images/` with Playwright on the sample, and update the manual pages that describe the Graph tab ([02-quick-start](../../manuals/02-quick-start.md), [01-introduction](../../manuals/01-introduction.md)). (after M09.6)

## Acceptance criteria
1. On the sample, the Graph tab opens in 3D within 2 s, stays smooth while orbiting, and a click on a node opens its properties; the 2D toggle and the no-WebGL fallback show the Cytoscape view.
2. The dashboard works in daemon mode, in public mode with no CSP errors in the console, and on the static site under its sub-path, at desktop and phone width.
3. No new network origin and no build step: every vendored file is pinned by version and sha512 and ships with its licence.
4. Dark is the default; the light theme and the toggle still work.
5. Screenshots in `docs/screenshots/` and `docs/manuals/images/` show the new dashboard.
6. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-22). Planned on Opus, built on Sonnet, reviewed on Opus (the review's findings were all fixed). Acceptance verified in headless Chromium on the sample and on this repo's graph:
1. The Graph tab opens in 3D on the whole graph (about 2 s for 281 nodes, 3 s for the layout to settle), orbit and click work, the 2D toggle and the no-WebGL fallback show Cytoscape.
2. Daemon, `sdd public` (CSP header, no console violations) and `sdd site` under `/mrv-sdd-relate/` with and without WASM all work (Graph, Query example, Replay moving cards and the progress bar), at 1280x800, 390x844 and 360 px.
3. Every vendored file is pinned by version and sha512 in `vendor/MANIFEST.json` with its licence (cytoscape included, 3.30.2); `scripts/vendor_web.sh` stages and swaps; no new network origin and no build step. three.js 0.187 ships no minified build, so `three.module.js` and `three.core.js` are vendored unminified (about 2 MB, loaded only when the Graph tab opens).
4. Dark is the default, light and the toggle work.
5. All 13 names in `docs/screenshots/` and the manuals' images retaken on the sample (new `graph-3d.png`, `graph-2d.png`, `graph-presets.png`, `board-start.png`; `graph-milestone.png` removed); quick-start and introduction updated.
6. Gates green: ruff, format, mypy, lint-imports (13 kept), pytest 682 passed.

Beyond the task list: 2D graphs keep nodes apart (declutter: small nodes, labels on hubs, hover and selection) and zoom smoothly (`smoothZoom` in `cystyle.js`); the Presets value box is a searchable combobox of valid IDs. SPEC-01 §6 and SPEC-07 §1 and §4 updated. Deviations: none.
