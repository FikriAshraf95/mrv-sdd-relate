# D006 — Guarded queries run in a killable worker process with a memory cap

- **Date / milestone:** 2026-11-22 · M06b · M06b.6
- **Spec:** [SPEC-09 §3](../specs/SPEC-09-security.md#3-query-guard) · [SPEC-01 §4](../specs/SPEC-01-architecture.md#4-relate-access-and-concurrency)
- **Affects:** `src/sdd/graph/store.py`, `src/sdd/service/query_guard.py`, `src/sdd/service/runtime.py`, `src/sdd/config.py`, `deploy/docker-compose.yml`
- **Status:** Open

## Spec says
The guarded query runs on a worker thread; after 5 s the request fails with query_timeout while the thread runs on, abandoned (Python cannot kill it).

## Implementation does
On a store on disk the query runs in one long-lived worker process per server process (graph.store.QueryProcess, started with spawn on first use and reused). The worker opens a fresh read_only connection per query, rolls back, and runs under an address-space cap SDD_QUERY_MEMORY_MB (default 1024; the hosted public service sets 384). At the time limit, or if the worker dies at its cap, it is killed and the request fails with query_timeout (retryable); the next query starts a new worker. In-memory stores keep the thread path. Relate path values are now converted to plain {nodes, relationships} so they can be sent back.

## Why
In the M06b walkthrough, MATCH (a),(b),(c),(d) RETURN count(*) on the public service used more than 512 MB in under 2 s. The container was OOM-killed and restarted before the 5 s timeout fired, so the user got no answer instead of query_timeout. A thread can bound neither time nor memory; a process can be killed and capped. In the daemon the same query would have killed the store's only writer.

## Consequences
About 0.3 s to start the worker on the first guarded query per process; later queries reuse it. After a timeout the gate is free at once, because the query is killed rather than abandoned. SPEC-09 §3 step 3 and SPEC-01 §4 (guarded queries) are to be rewritten when M99 folds the deviations.
