# Snapshot the graph and share it

> **For:** anyone who wants to commit a copy of the graph, hand it to someone, or load it elsewhere.

**Never commit the live store** (`.sdd/graph/`). A store the daemon writes would keep your working tree dirty, conflict on every merge and change under `git checkout`. `sdd init` gitignores it. Commit **snapshots** instead.

## `sdd snapshot`: committed copies of the store

```bash
sdd snapshot                         # writes to .sdd/snapshots/
sdd snapshot --out some/folder
```

It writes three copies:

| Copy | What | Opens with |
|---|---|---|
| `graph/` | a consistent copy of the directory store | `sdd public --store …/graph`, Python `relate.connect(path, read_only=True)` |
| `graph.rl` | Relate's single-file store | the `relate` CLI, Python `relate` |
| `graph-json/` | the same graph in Relate's readable JSON codec | any text editor; diffs cleanly in git |

Then it opens the live store and every copy read-only and compares node and relationship counts per label and type. A mismatch is an error.

**You should see** something like this (your counts will differ):

```
graph      written
graph_rl   written
graph_json written
out        /path/to/repo/.sdd/snapshots
1840 nodes, 5210 relationships
```

Notes:

- `graph.rl` and `graph-json/` need the **`relate` CLI** on your `PATH` (Relate's Python package can't make them). Without it, both are `skipped` and only `graph/` is written, which also requires that no daemon runs. With a daemon running and no CLI, the command fails with `daemon_running`. Install the CLI ([Install](install.md)) or stop the daemon.
- With the CLI, snapshots work **beside a running daemon**: the clone reads every committed transaction.
- The copies keep the `.cypherlite.lock` marker files, because a read-only open needs them. Commit them too.
- Run it on purpose (before a release, a demo, or a review). The committed copy lags your docs until you run it again.

## Exports: Cypher and JSON

For loading the graph somewhere else, or reading it in code:

```bash
sdd export --cypher --out graph.cypher    # the whole graph as an idempotent Cypher script
sdd export --json   --out graph.json      # {nodes, edges} in the dashboard's /api/graph shape
```

- **Cypher:** one statement per line, each ending in `;`: `MERGE` per node sorted by ID, then `MATCH … MERGE` per relationship. Re-running it changes nothing. Map properties stay as stored JSON strings (`header_json`). The static demo loads this file into Relate's WebAssembly build in the browser.
- **JSON:** every node `{id, label, title, props}` and edge `{source, target, type}`, sorted, with no limit.

Both read the store files directly and work with or without a daemon.

## Share a browsable copy

- **Someone with Docker:** give them the repo (with a snapshot committed) and they run `sdd public --store .sdd/snapshots/graph --project .` for a read-only dashboard ([Public mode](public-mode.md)).
- **No server at all:** `sdd site` builds a static dashboard folder (precomputed answers and a WebAssembly query tab) from a sample's committed store. It's built for the bundled sample (`--sample samples/courtside`) and is how the GitHub Pages demo is made. See the [CLI reference](../reference/cli.md#sdd-site).
- **A picture:** `sdd export --mermaid …` renders a diagram GitHub shows inline ([Export diagrams](export-diagrams-and-status.md)).
