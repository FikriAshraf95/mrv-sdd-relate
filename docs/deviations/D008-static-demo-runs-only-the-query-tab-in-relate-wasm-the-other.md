# D008 — Static demo runs only the Query tab in Relate WASM; the other views use build-time answers

- **Date / milestone:** 2026-11-22 · M08 · M08.4
- **Spec:** [SPEC-11 §6](../specs/SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)
- **Affects:** `src/sdd/web/static/static.js`, `src/sdd/web/static/relate-worker.js`, `src/sdd/site.py`
- **Status:** Open

## Spec says
The dashboard's data adapter loads the graph into Relate's WASM build in memory and runs the same named Cypher queries the daemon uses (all of service/impact.py's Cypher lives in graph/queries/*.cypher, so both share it).

## Implementation does
The WASM backend (a worker) serves the Query tab only: guarded Cypher, the examples and Show as graph. Impact, Explain, presets, Board and Graph read answers that sdd site computed at build time with the daemon's own service code and graph/queries/*.cypher.

## Why
The impact and explain assembly is Python; a JavaScript port would duplicate it, and the graph is static, so the answers are identical.

## Consequences
Impact and Explain work for the indexed targets only (every Table, Feature, File and Section of the sample); a typed name outside them answers node_not_found with a message saying so.
