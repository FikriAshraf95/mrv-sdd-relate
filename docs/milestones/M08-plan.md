# M08 implementation plan (Opus plan → Sonnet build)

Source of truth: [SPEC-11 §6, §9](../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages), [SPEC-07 §1, §4](../specs/SPEC-07-dashboard-and-api.md#1-rules), [SPEC-08 §2–3](../specs/SPEC-08-cli-and-exports.md#2-commands), [SPEC-06 §5](../specs/SPEC-06-code-context.md#5-presets), [SPEC-11 §4](../specs/SPEC-11-deployment-and-demo.md#4-sprint-replay), [SPEC-00 §8](../specs/SPEC-00-overview.md#8-schedule-and-open-items) (O2). Milestone: [M08](M08-static-demo.md). Previous plan: [M06b-plan](done/M06b-plan.md).
Follow `CLAUDE.md`. **D007 is the highest deviation.** This plan expects **one** new deviation, D008 (§7). Log anything else you knowingly depart from with `sdd deviation …` (D009…).

## 0. Scope and boundaries

- **In:** `sdd site` (build `site/` from the sample), a static data adapter in the dashboard (precomputed backend + Relate WASM backend in a worker), Board *Replay*, `.github/workflows/pages.yml`, O2 measurement, tests, spec edits.
- **Not in:** pushing, enabling Pages in the GitHub settings, and the by-hand check on the published site (the human does those after the Opus review). README (M99) gets only the one line in §6.
- **Layering:** `sdd site` is CLI → one function `service/site.py::build_site(...)`. It reuses the existing service functions (board, milestones, impact, explain, presets, graph, node, exports, demo replay). **No new Cypher** unless a service function is missing; then add it in `service/` with its Cypher in `graph/queries/`. Only `config.py` reads `os.environ`. No new Python dependencies. **The dashboard stays no-build, no-framework** (SPEC-07 §1 rule 5): plain ES modules; the builder only copies files and writes JSON.
- **Tests never touch the network** (SPEC-00 §6.6). `sdd site` never downloads; the WASM files are passed in with `--wasm-dir` (the workflow fetches them). Without them the site runs on precomputed answers — that *is* the fallback path.
- **Do not commit.** Leave the work tree for the Opus review.
- Work through the sdd CLI in the dev container (the daemon is running): `sdd claim M08.N --agent sonnet-1`, `sdd context M08.N`, `sdd section "SPEC-11 §6"`, `sdd done M08.N --agent sonnet-1 --notes … --files …`, `sdd deviation …`. Don't edit task boxes by hand.
- Order: **M08.1 → M08.2 → M08.3 → M08.4 → M08.5 → M08.6** (fallback first, per the milestone).

## 1. Facts verified (2026-11-22, Opus, from the npm registry)

- Package **`@relate/relate-wasm` 1.2.0** (Apache-2.0), tarball `https://registry.npmjs.org/@relate/relate-wasm/-/relate-wasm-1.2.0.tgz`, integrity `sha512-RmJq36laQNR2mgI13x9ZYi9rfPEPallFUYG2lTLi7ERfeMULYf3tpo/aA4cPBEs68s9STX9EtMJvx1NpyPb2nQ==`. Files that matter: `relate.js` (26 KB, ES module, no bundler needed), `relate_bg.wasm` (7.2 MB), `trap.js`, `snippets/` (keep the directory: `relate.js` imports from it — check), `LICENSE`/README.
- API: `import init, { RelateDb } from "./relate.js"; await init();` (fetches `relate_bg.wasm` next to the module, or `init({module_or_path: url})`). `new RelateDb()` is in-memory and writable; `new RelateDb(true)` is read-only and empty (useless for us). `db.execute(cypher, paramsJson|null)` → JSON string `{columns, rows: [ {col: value} ], stats, error}`; engine errors come back in `error`, they don't throw. `db.executeScript(script)` → one envelope per statement, stops at the first error. A Rust panic surfaces as `WebAssembly.RuntimeError` (`isWasmTrap` in `trap.js`); the instance is then dead.
- **Node values in the wire envelope are not yet known** (shape of a node/relationship in `rows`). Find out in M08.3 and normalise them in the worker to the shape `POST /api/query` returns today (read `service/query_guard.py` / the store's result decoding: nodes as maps with `id`, `*_json` decoded, rows as arrays in column order).
- There is **no Node.js in the dev image.** For M08.3 measurements use a throwaway container: `docker run --rm -v <scratch>:/w -w /w node:22-slim node measure.mjs` (put the downloaded package in its own directory, the script in another; see the env note on untrusted downloads). Don't add Node to the dev image.
- `demo/replay.py::Replay` can be driven without sleeping: `start()`, then `tick()` until it returns `False`; `self.actions` records `(tick, agent, action, target)` deterministically for a seed.

## 2. `sdd site` (M08.1)

`sdd site [--sample samples/courtside] [--out site] [--wasm-dir DIR] [--seed 1]` → `service/site.py::build_site`. Result `{out, backend_files: {wasm: bool}, answers: <count>, nodes, relationships, replay_events}`. Add the SPEC-08 §2 row and a SPEC-08 §3 bullet (rules below) in the same change. `out` is deleted and rewritten (refuse an `out` that is the repo root, `src/`, or not empty and lacking a previous `site/data/manifest.json`: `invalid_input`). Add `/site/` to `.gitignore`.

It opens the **sample's committed store read-only** (`samples/<name>/.sdd/graph`, the same way `sdd public` does), so no sync and no write. Layout:

```
site/
  index.html            # copy of web/static/index.html with one added line:
                        #   <meta name="sdd-backend" content="static">   (string insert, no templating engine)
  *.js *.css vendor/    # web/static as is
  static.js             # new, the static adapter (§3)  — lives in web/static/, copied like the rest
  relate-worker.js      # new, the WASM worker (§4)     — idem
  wasm/                 # only with --wasm-dir: relate.js, relate_bg.wasm, trap.js, snippets/, LICENSE
  data/
    manifest.json       # {project, generated_at (from the store's synced_at, not wall clock), schema_version,
                        #  counts, files: {...}, centrepiece: "table:bookings", wasm: true|false}
    graph.json          # sdd export --json (whole graph)
    graph.cypher        # sdd export --cypher
    health.json milestones.json presets.json
    board/<n>.json      # one per milestone + "default" (= /api/board with no milestone)
    impact/<n>.json     # every Table, Feature, File, Section target, depth 3 (the dashboard's default)
    explain/<n>.json    # every File
    preset/<n>.json     # schema; milestone:<id> each; impact:<t> each target above; explain:<path> each
                        # file; lineage:<section> each section a deviation amends; feature:<slug> each
    query/<n>.json      # the Query tab's six EXAMPLES, run through the query guard
    replay.json         # §5
    index.json          # {impact: {id: "n12.json"}, explain: {...}, preset: {...}, board: {...}, query: {cypher: "n3.json"}}
```

- File names are `n<counter>.json` assigned in sorted-id order and looked up through `index.json` — no ID ever becomes a path (IDs hold `#`, `/`, `:`, `§`).
- Every answer is the **exact JSON the HTTP endpoint returns** — call the same service function the route calls, not a re-implementation. Errors are not stored.
- `health.json` = `{ok: true, mode: "static", synced_at, schema_version, instance: "static", project, public_query: "presets", base_url: null}`; the adapter overwrites `public_query` with `"guarded"` when WASM is up (§4).
- Deterministic: two runs over the same store produce byte-identical `data/` (sorted keys, no wall-clock time). Test it.
- Size guard: the sample is small; if `data/` exceeds ~15 MB, stop and report instead of trimming silently.
- Keep the Query tab's EXAMPLES in one place: move them to a small JSON (`web/static/examples.json`) that `query.js` fetches and `sdd site` reads, or have `site.py` parse them — pick the simpler; don't duplicate the strings.

## 3. Static adapter (M08.1, dashboard side)

- `api.js` keeps the HTTP backend as is and becomes a facade: at load it reads `<meta name="sdd-backend">`. Absent → HTTP (daemon and `sdd public` unchanged; **no behaviour change there**, re-run the existing dashboard tests). `static` → `await import("./static.js")`. Every `api.*` method awaits the chosen backend, so view modules don't change their calls. Export the backend name (`api.backend()` → `"http" | "precomputed" | "wasm"`).
- `static.js` fetches **relative** URLs (`data/…`; Pages serves under `/<repo>/`). It implements every `api` member:
  - `health, milestones, presets, preset(name), impact(target), explain(path), board(m)`: look up `index.json`. `impact` resolves the typed target the way the dashboard sends it: exact id first, else a unique case-insensitive match on id suffix or title among the indexed targets; none → error `node_not_found` with the message *"The static demo has answers for the listed targets only. Pick one from the list."*; several → `ambiguous_target` with `details.candidates`, matching what the daemon returns (check `service/impact.py`'s error shape).
  - `graph({labels, focus, depth, limit})`, `node(id)`, `targets()`: computed in JS from `graph.json` with the same semantics as `/api/graph` and `/api/nodes/{id}` (read `service/graph.py` or wherever they live; mirror ordering, `limit`, and the node-with-relationships-grouped-by-type shape). This is plain data filtering, not Cypher.
  - `query(cypher, params)`: precomputed backend → only an exact match of a precomputed example (whitespace-normalised) answers; anything else → `query_rejected` *"Only the presets run in the static demo."* WASM backend → §4.
  - `events(onEvent, onState)`: no stream. Register the listener (used by Replay, §5), call `onState(false)`, return an unsubscribe.
  - Tokens: no-ops.
- **Footer** (acceptance 2): `app.js` shows, for the static site, `Static demo · Relate WASM 1.2.0 · <n> nodes loaded in <ms> ms` or `Static demo · precomputed answers` (plus the WASM error reason in a `title` attribute when it fell back). Text only, never markup. The header `#sync` shows `<project> · static`.
- Board in static mode: the live indicator says `static` instead of `polling`, and the poll timer is not started (no point re-reading the same JSON every 5 s).
- Query tab: the presets-only switch keys off `public_query === "presets"` when `mode` is `public` **or** `static`.
- Phone: SPEC-07 §4 says the layout works from 360 px. Don't restyle; just check nothing in the new footer/Replay button breaks it.

## 4. WASM backend (M08.3, M08.4)

**M08.3 — O2.** In a `node:22-slim` container: load `relate_bg.wasm` with `initSync`, then time (median of 5): (a) `executeScript(graph.cypher)` whole; (b) the same split on newlines, one `execute` per line; (c) loading `graph.json` with two parameterised `UNWIND $rows … MERGE` statements per label/type (only if (a)/(b) fail or are slow). Also record node/relationship counts after load vs `manifest.json`, and the wire shape of a node and a relationship in `rows`. **Gate:** pick the fastest correct path; WASM is "available" if counts match and load is under ~3 s in Node for the sample. Write the result into SPEC-00 §8 O2 (status **Closed (date)** + numbers + chosen format), and put the measuring script under `bench/wasm/measure.mjs` with a one-line README (it is run by hand, not by pytest). If WASM fails the gate, stop after recording O2: the site ships precomputed-only, M08.4 is done as "not applicable" and that is a deviation (log it).

**M08.4 — worker.** `web/static/relate-worker.js` (dedicated module worker, `new Worker(url, {type: "module"})`):
1. `import init, { RelateDb } from "./wasm/relate.js"`; `await init()`; fetch `data/graph.cypher` (or the chosen format); load; verify counts against `manifest.json`; post `{ready, nodes, relationships, ms, version: "1.2.0"}`.
2. On `{id, cypher, params}`: run the guard (below), `db.execute`, normalise the envelope to `{columns, rows (arrays), truncated}` with node/relationship values shaped like the daemon's, cap at 100 rows (`truncated: true`), map `error` to `{code: "query_rejected"|"invalid_input", message}`.

`static.js` starts the worker only when `manifest.wasm` is true and `WebAssembly` + module workers exist; it waits up to 15 s for `ready`, else terminates it and stays precomputed (reason shown in the footer's title). **Timeout:** each query gets 5 s; on expiry the page terminates the worker, returns `query_timeout`, and starts a fresh one in the background (same idea as D006). A wasm trap → same respawn.

**Guard in the browser** (SPEC-09 §3 rules, as far as they apply): reuse the *rules* of `service/query_guard.py` — read the Python and port the checks for write clauses (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `LOAD CSV`, …), `CALL`, more than one statement, and variable-length patterns over `*..4`, with the same error codes and messages. Writes can't reach anything (the store is an in-memory copy in the visitor's tab), but the Query tab should behave like the hosted one. Keep the port small and say in a comment which Python function it mirrors.

**What runs where** (this is D008, §7): with WASM up, the **Query tab** (including *Show as graph* and the examples) runs in Relate WASM. Impact, Explain, presets, Board and Graph keep the build-time answers (same service code and the same `graph/queries/*.cypher`, run by Python at build time). Porting `service/impact.py`'s assembly logic to JS would duplicate it for no visible gain.

## 5. Replay (M08.5)

- **Recording at build time** (`site.py`): copy the sample with the existing `demo/prepare.py` into a temp dir, construct `Replay` with `--seed` (default 1), `start()`, then before the first tick save `board` for every `run.milestones` entry (the start state); `tick()` until `False` (cap 2000 ticks → `invalid_input` if hit). Convert `actions` into `replay.json`:
  `{seed, start: {<milestone>: <board JSON>}, events: [{tick, type: "task"|"deviation"|"milestone", data}]}` where `data` has the fields the SSE events carry today (read `service/follow.py` / `web/api.py` events: task `{id, status, claimed_by}`, deviation `{id, title}`, milestone `{id, status}`). Deviation ids/titles come from the replay's store after the run. `*_failed:*` actions are skipped. Delete the temp dir. No wall-clock time in the file.
- **Playback** (`static.js` + `board.js`): `api.replay` exists only in the static backend. Board shows a **Replay** button when it exists. Pressing it: the adapter switches its board answers to the recorded start state, then every 600 ms applies the next tick's events to its in-memory boards (move the task between columns, set `claimed_by` / `completed_by`, milestone counts in `milestones()`), and calls the registered listeners with each event — so `board.js` runs its normal `note()` + `refresh()` path and cards flash as they do live. Button becomes **Stop**; at the end (or Stop) a **Back to the sample** state restores the precomputed boards. Changing tab stops it. If the picked milestone isn't in the replay, the button switches the picker to the first replay milestone.
- The replay is cosmetic: it changes only the Board/milestones answers, never Impact/Explain/Graph.

## 6. Workflow and README (M08.2)

`.github/workflows/pages.yml`:
- `on: push: branches: [main]` + `workflow_dispatch`; `permissions: contents: read, pages: write, id-token: write`; `concurrency: pages`.
- Build the dev image exactly like `ci.yml` (same cache scope). Fetch the tarball with `curl`, **verify the sha512 integrity above** (`openssl dgst -sha512 -binary | base64`), unpack into `/tmp/relate-wasm`, then `docker run … uv run sdd site --sample samples/courtside --out site --wasm-dir /tmp/relate-wasm/package`. Then `actions/configure-pages@v5`, `actions/upload-pages-artifact@v3` (path `site`), `actions/deploy-pages@v4`. Add a `.nojekyll` in `site/` (from `sdd site`).
- A pinned version in one place (workflow `env: RELATE_WASM_VERSION`, `RELATE_WASM_SHA512`).
- README: one line under the demo links: the Pages URL `https://fikriashraf95.github.io/mrv-sdd-relate/` and *"runs Relate in WebAssembly in your browser; if your browser can't, it shows answers precomputed from the same graph (the footer says which)."* (acceptance 2). M99 polishes the README; don't rewrite it.

## 7. Expected deviation (log it with `sdd deviation`, task M08.4)

**D008 — Static demo runs only the Query tab in Relate WASM; the other views use build-time answers.** Amends SPEC-11 §6. Spec says the adapter loads the graph into Relate's WASM build and runs the same named Cypher queries the daemon uses. Does: the WASM backend serves the Query tab (guarded Cypher, examples, *Show as graph*); Impact, Explain, presets, Board and Graph read answers that `sdd site` computed at build time with the daemon's own service code and `graph/queries/*.cypher`. Why: the daemon's impact/explain assembly is Python; a JS port would duplicate it, and the graph is static so the answers are identical. Consequences: Impact works only for the indexed targets (all Tables, Features, Files, Sections of the sample). Affects `src/sdd/web/static/static.js`, `src/sdd/web/static/relate-worker.js`, `src/sdd/service/site.py`.

## 8. Spec edits in the same change

- **SPEC-08 §2** row for `sdd site`; **SPEC-08 §3** bullet with §2's rules (layout, `index.json`, determinism, `--wasm-dir`, no network).
- **SPEC-11 §6**: the site layout in one paragraph, the workflow, the fallback rule (WASM if the worker is ready within 15 s and counts match, else precomputed; footer says which), Replay recording. The D008 note is written by `sdd deviation`.
- **SPEC-07 §1 rule 5**: adapter backends `http | precomputed | wasm`, chosen by `<meta name="sdd-backend">`; **SPEC-07 §4**: Board Replay button (static only), footer backend line.
- **SPEC-00 §8 O2**: closed with the M08.3 numbers.
- **SPEC-10**: list the new tests where the spec lists test files, if it does.

## 9. Tests (M08.6, pytest, no network)

Under `tests/spec11/test_site.py` (and `tests/spec08/` if that is where command tests live), against the committed sample store, `--out` in `tmp_path`, no `--wasm-dir`:
- `test_spec11_ac05_static_site_impact_centrepiece`: the site's impact answer for `table:bookings` equals `impact("table:bookings", depth 3)` from the service; its `preset/impact:table:bookings` exists; `index.html` carries the meta tag; every file `index.json` names exists; `manifest.wasm` is false.
- determinism: two builds → identical `data/` bytes.
- with a fake `--wasm-dir` (tmp dir holding stub `relate.js`, `relate_bg.wasm`, `trap.js`) → copied, `manifest.wasm` true; a missing file → `invalid_input`.
- `replay.json`: events non-empty, start boards all `todo` for `run.milestones`, final event is a `milestone` completion, same seed → same file.
- refusing a dangerous `--out` (repo root) → `invalid_input`.
- the drift/invariant suites still pass (new CLI command in SPEC-08 §2).
- Static adapter JS has no test runner here; instead run the browser check below.

**Browser check by hand (before handing back):** build the site with the real WASM (download as in §1 into scratch), serve it from the dev container (`python -m http.server` on a free port bound to `0.0.0.0`, published or via `docker run --network container:…`), and drive it with `mcr.microsoft.com/playwright:v1.49.0-jammy` (or similar) from a scratch script: load `#impact/table%3Abookings` at 1280×800 and 390×844, wait for the result, screenshot both, read the footer text; run `MATCH (n) RETURN count(n)` in the Query tab; press Replay and screenshot after ~5 s. Then repeat with the site built **without** `--wasm-dir` (footer must say precomputed, Impact still works, Query presets-only). Save screenshots in the scratchpad and list their paths in your report. Don't commit them.

Gates: `ruff check`, `ruff format --check`, `mypy src/sdd`, `lint-imports`, `pytest -q` all green.

## 10. Report back

Per task: what was built, files, test names, the O2 numbers, D008 (and any other deviation), screenshot paths, anything you could not verify. Leave the tasks `done` through `sdd done`; leave the milestone open for the Opus review.
