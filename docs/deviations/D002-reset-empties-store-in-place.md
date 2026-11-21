# D002 — `sdd sync --reset` empties the store in place

- **Date / milestone:** 2026-11-22 · M01b · M01b.3
- **Spec:** [SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands)
- **Affects:** `src/sdd/sync/indexer.py`, `src/sdd/service/indexing.py`
- **Status:** Resolved → spec updated

## Spec says
`sdd sync [--reset]`: "`--reset` deletes the store first (graph-only state is lost; asks unless `--yes`)".

## Implementation does
`--reset` opens the store writable (which fails with `daemon_running` if another process holds it), deletes every node with `MATCH (n) DETACH DELETE n` in one job, then runs the sync as an initial sync. The store directory is never removed.

## Why
Deleting a directory that a daemon may hold open is unsafe on Linux: the daemon keeps writing to unlinked files. Emptying in place is equivalent for every reader and goes through the single writer.

## Consequences
- Graph-only state (claims, agents, events, tool-owned links) is lost, as before.
- The store files keep their size until Relate compacts them.
- `--json` without `--yes` is an `invalid_input` error (no prompt).
