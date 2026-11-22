# Rebuild the graph from scratch

> **For:** anyone whose graph looks wrong, or who changed the schema version or the config globs.

Because Markdown is the source of truth, the graph can always be rebuilt from your files and git history.

## What you lose

A rebuild **drops graph-only state**:

- all claims (every task goes back to `todo` or `done` according to its checkbox),
- agent records (so the next `what_changed(since="last_session")` of each agent counts as its first: the last 24 h),
- the event history (completion notes, files touched recorded by `complete_task`),
- `TOUCHES` and `COMPLETES` links added by tools (links from git commits come back from the history).

Everything else comes back: specs, sections, tasks and their ticks, deviations with `RAISED_IN` and `AFFECTS`, tables, features, files and commits.

So **before a rebuild**, let running agents finish or release their tasks.

## Steps

1. **Stop the daemon** (Ctrl+C, or `docker stop sdd-daemon`). A rebuild needs the store for writing, and the daemon owns it. With the daemon running, `sync` refuses with `daemon_running`.

2. **Rebuild:**

   ```bash
   sdd sync --reset
   ```

   It asks `Empty the store …? Claims, agents and events are lost.` Answer `y`, or pass `--yes`. (With `--json`, `--yes` is required.) The store is emptied in place, then a full sync runs: code walker, Markdown, git.

   **You should see** something like this (the numbers depend on your repo):

   ```
   initial sync: 214 files scanned, 214 changed, 0 removed, 0 re-linked
   nodes 1840 created, 0 updated, 0 deleted; events 0; store holds 1840 nodes and 5210 relationships
   warnings: 0 error, 0 warning, 0 info; unresolved links: 0
   ```

3. **Start the daemon again:** `sdd daemon`.

## A lighter option first

Often you don't need a reset:

- **Force a full scan without losing anything.** With the daemon running: `curl -X POST http://127.0.0.1:8770/api/sync` (add `-H "Authorization: Bearer $SDD_TOKEN"` if you use a token). Without a daemon: `sdd sync` (no `--reset`). Either compares every file's hash with the graph and re-parses what differs.
- **Restart the daemon.** Startup always runs a full scan.

## Deleting the folder instead

You can also stop the daemon and delete `.sdd/graph/`. The next `sdd daemon` or `sdd sync` creates a fresh store. That has the same effect as `--reset`.

## Check

```bash
sdd info       # node and relationship counts per label, schema version
sdd doctor     # parser warnings and unresolved links
```
