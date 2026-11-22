# M09 plan — Dashboard refresh and 3D graph

> Plan for [M09](M09-dashboard-refresh.md). Decisions taken with the user on 2026-11-22: **no framework, no build step** (vendored libraries only); the Graph tab **opens in 3D with a 2D toggle**; **dark by default**, light kept. Visual reference: the mcp-vault desktop app's galaxy view and tokens (three.js + d3-force-3d, layout in a worker, dark neutral ramp with a single accent).

## 1. What stays the same

- `src/sdd/web/static/` is still the one folder the daemon, `sdd public` and `sdd site` serve or copy. No Python change is needed to serve new files: `api.py` serves the folder, `site.py` copies it with `copytree`.
- `api.js` stays the single data facade over the `http`, `static` and `wasm` backends. New modules call `api.*`, never `fetch`.
- SPEC-07 §1 rule 5 holds: plain HTML + ES modules + vendored libraries, no build step, no framework.
- The public CSP (`default-src 'self'`) holds: no inline `<script>` or `<style>`, no `style="…"` attributes, no `innerHTML`, no `data:` URLs. Setting `element.style.x` through the CSSOM is allowed by CSP and is what `CSS2DRenderer` does. The own-files tests in `tests/spec07/test_dashboard.py` keep scanning every non-vendor file.
- Impact and Explain stay in Cytoscape: radial and left-to-right layered layouts read better in 2D.

## 2. Vendoring (M09.1)

`scripts/vendor_web.sh`, run in the dev container (`docker compose -f docker-compose.dev.yml exec dev sh scripts/vendor_web.sh`). For each pinned package it downloads the npm tarball from `registry.npmjs.org`, checks its sha512 against the pin in the script (the same pattern as `RELATE_WASM_SHA512` in `pages.yml`), and copies the needed files. The output is committed; nothing is fetched at runtime or in CI.

| Package | Pin (confirm the latest patch at vendoring time) | Files into `vendor/` | Licence |
|---|---|---|---|
| `three` | 0.186.x (mcp-vault uses ^0.186.0) | `build/three.module.min.js` (plus `three.core.min.js` if this version splits it), `examples/jsm/controls/OrbitControls.js`, `examples/jsm/renderers/CSS2DRenderer.js` | MIT |
| `d3-force-3d` | 3.0.6 | `src/*.js` as ESM | MIT |
| its dependencies `d3-binarytree`, `d3-dispatch`, `d3-octree`, `d3-quadtree`, `d3-timer` | as resolved by d3-force-3d 3.0.6 | `src/*.js` | ISC / MIT |
| `@fontsource/inter`, `@fontsource/jetbrains-mono` | latest 5.x | latin 400/500/600 woff2 only | OFL-1.1 |

- **Bare imports are rewritten** to relative paths (`from 'three'` → `from './three/three.module.min.js'`, `from 'd3-quadtree'` → `from '../d3-quadtree/index.js'`). An import map would be an inline `<script>`, which the public CSP blocks.
- `vendor/MANIFEST.json`: `[{package, version, sha512, files, licence_file}]`. A test checks that every file under `vendor/` is listed and that each package has its licence file.
- Fonts are loaded by `@font-face` in `style.css` with relative `url(vendor/fonts/…)`, which already passes the `url(...)` rule of check 6.
- Size budget: about 180 KB gzipped extra (three.js is most of it). It loads only when the Graph tab opens (dynamic `import()`), so the Board stays light.
- SPEC-01 §6, dashboard line: "vendored `cytoscape.min.js`, three.js, d3-force-3d (with its d3 dependencies) and the Inter and JetBrains Mono fonts, pinned in `vendor/MANIFEST.json`; no CDN at runtime".

## 3. Tokens and shell (M09.2)

- `style.css` gets one token block: a neutral ramp (`--bg-0…4`, `--line`, `--fg-0…2`), one accent, semantic `--ok/--warn/--err`, `--font-ui`, `--font-mono`, an 8 px spacing unit and radii, plus the label palette `--l-<Label>` that `dom.js` `labelColor()` already reads (one source for Cytoscape and three.js). Light values live under `[data-theme="light"]`.
- **Theme rule:** dark unless the user chose light with the toggle, or has never toggled and the system prefers light. The choice is kept in `localStorage` (wrapped in try/catch, per-viewer only). `theme.js` sets `data-theme` on `<html>` before first paint from the module at the top of `app.js` (no inline script).
- Shell: a slimmer header (brand, tabs, project name, sync state, theme toggle), tabs as a segmented control that collapses to the existing select below 640 px, a side panel that slides over the view on phones, and consistent empty, loading and error states (one `state.js` helper).
- Motion: 150–200 ms transitions; everything off under `prefers-reduced-motion`.
- SPEC-07 §4 *Look* paragraph: "dark by default with a light theme (toggle, remembered per browser; the system preference applies until the user toggles), Inter and JetBrains Mono vendored, colour tokens as CSS custom properties, one accent colour per label shared by every view, sentence case, no emoji. Layout works from 360 px wide."

## 4. The 3D graph (M09.3)

**Files:** `graph3d.js` (scene and interaction), `graph-layout.worker.js` (module worker, d3-force-3d), `graph.js` (the tab: data loading, label filter, search, side panel, the 2D/3D toggle; the Cytoscape code moves to `graph2d.js` unchanged in behaviour).

**Data:** `api.graph({labels, limit: 2000})`, the same endpoint and static answer as today, with the default labels (everything except Event, Meta, Agent). On the sample that's 282 nodes and about 800 edges. Above 2 000 nodes, the endpoint's cap applies and the panel says "showing 2,000 of N; filter labels to see more".

**Layout worker:** receives `{ids, labels, edges}` as typed arrays, runs `forceSimulation` in 3 dimensions with link, many-body, collide and a weak centre force, and posts `positions: Float32Array` (transferable) every few ticks until `alpha < 0.01`. Under reduced motion it runs to rest and posts once. The main thread never simulates. Deterministic seed positions (by node index), so two loads look the same.

**Renderer:**
- `WebGLRenderer` (antialias, `devicePixelRatio` capped at 2), a dark background from `--bg-0`, light fog for depth.
- Nodes: one `InstancedMesh` of low-poly spheres per label, radius `2 + 1.5·log2(1 + degree)`, colour from `labelColor()`.
- Edges: one `LineSegments` with a position buffer updated from the worker's batches, `--line` at 35% opacity. Edges of the hovered or selected node go to the accent colour.
- `OrbitControls` with damping, auto-rotate slowly until the first interaction (off under reduced motion).
- Labels: `CSS2DRenderer` for the hovered node, the selected node and the 12 highest-degree nodes only. Labels are DOM, so they stay sharp and need no font atlas.
- Render on demand: a frame only while the layout moves, the camera is damping or a transition runs. Idle tabs cost nothing.

**Interaction:** a raycaster on the instanced meshes; hover shows the label and highlights neighbours; click opens the existing side panel (`api.node`); double-click tweens the camera to the node and loads its neighbourhood (`api.graph({focus, depth: 1})`, merged into the scene and fed back to the worker); the search box flies to an exact ID or the best title match; label checkboxes hide instances without re-running the layout; *Reset* returns to the start view.

**2D/3D toggle and fallback:** the toggle swaps `graph3d` and `graph2d` in the same container and keeps the selection. When `WebGLRenderingContext` is missing or context creation fails, the tab opens in 2D and the toggle is disabled with a tooltip saying why. The URL hash keeps the mode (`#graph/3d`, `#graph/2d`), and README deep links keep working.

**SPEC-07 §4 item 2** becomes: "**Graph:** opens in 3D on the whole graph (three.js, force layout in a worker; up to 2 000 nodes, the endpoint's cap) with a 2D/3D toggle; 2D is the Cytoscape view, and the fallback without WebGL. Label filter (colour per label), search box (ID or title) that flies to the node, click to show properties in a side panel, double-click to expand neighbours, *Reset*. The presets open in 2D."

## 5. Board, Impact, Explain, Query (M09.4, M09.5)

- **Board:** a thin progress bar per milestone in the picker row and on the header counts; agent chips get a stable hue from a hash of the agent name (same agent, same colour, everywhere); a card animates to its new column (FLIP with transforms, 180 ms), and the highlight on change stays; the ticker shows the last five events with relative times. Replay (static demo) uses the same event path, so it needs no change.
- **Impact and Explain:** `cystyle.js` reads the new tokens; node sizes and edge widths tuned for the dark background; group lists get counts as pills and the `via` chain as monospace breadcrumbs.
- **Query:** the results table gets sticky headers, monospace values and zebra rows; the example and preset menus sit together above the editor.

## 6. Checks (M09.6, M09.7)

- **By hand with Playwright** (headless Chromium, as in M08): daemon (`localhost:8770`), `sdd public` on the sample's snapshot (console must show no CSP violations), `sdd site` served under `/mrv-sdd-relate/` with the WASM backend and with WASM disabled; 1280x800 and 390x844; WebGL disabled (`--disable-webgl`) falls back to 2D.
- **Tests:**
  - `test_vendor_manifest_lists_every_file_with_a_licence` (new).
  - The own-files rules of `test_dashboard_is_ready_for_the_public_csp` and `test_spec07_ac06_no_request_outside_the_own_origin` already cover new files; extend the adapter allow-list only if a new module reads files (the worker receives data by message, so it shouldn't).
  - `test_every_asset_the_page_references_is_served` must also follow `import()` and `new Worker(new URL(…))` references, so the lazily loaded graph modules are covered.
  - `tests/spec11/test_site.py`: the built site contains `vendor/MANIFEST.json` and the graph modules.
- Gates: `ruff`, `mypy`, `lint-imports`, `pytest -q`.

## 7. Screenshots (M09.8)

Retake with Playwright on the sample (local `docker compose up`; stop the dev container's daemon first, since both use :8770, or use `--port`):

| File | Shot |
|---|---|
| `docs/manuals/images/board.png` | Board, M05a with a claimed card (claim one by CLI first) |
| `docs/manuals/images/graph-3d.png` (new), `graph-milestone.png` | Graph tab in 3D; Graph tab in 2D on a milestone |
| `docs/manuals/images/impact-bookings.png`, `explain-overlap.png`, `query-open-tasks.png` | as before |
| `docs/screenshots/*` | the same 13 names, in dark and light where the name says so |

Then update the Graph steps in `docs/manuals/02-quick-start.md` (3D, the toggle) and the image list in `01-introduction.md`.

## 8. Risks

| Risk | Answer |
|---|---|
| A vendored file trips the public CSP (inline style, `eval`) | three.js and d3-force-3d use neither; verified in public mode in M09.6 with the console open |
| WebGL missing (old phones, locked-down browsers, headless CI) | 2D fallback; tests never need WebGL |
| The 3D view is pretty but hard to read | 2D is one click away; presets open in 2D; labels shown only on hover, selection and hubs |
| Deadline (submit by 11 Dec) | the refresh lands view by view; M09.3 can ship last, and without it the dashboard is still restyled. Cut order if late: Board motion, then 3D search fly-to, then the 3D view itself |
| Pinned versions drift | the script pins version and sha512; upgrading is an edit to the script and a re-run |
