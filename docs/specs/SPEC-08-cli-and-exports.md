# SPEC-08 — CLI and exports

> **Status:** v1 (2026-11-21) · **Owner of:** every `sdd` command, Mermaid / Cypher / JSON exports, snapshots of the store, the CLAUDE.md status block

## 1. Rules

1. `sdd` is a Typer app. Commands call the daemon API when a daemon runs for the project ([SPEC-01 §1](SPEC-01-architecture.md#1-process-model) rule 3), otherwise `service/` directly on a read-only snapshot (reads) or the store (writes). Exports and `snapshot` read the store files directly, daemon or not: a `read_only` open works beside a running writer (O12) and there is no endpoint for a full dump.
2. Every command takes `--project PATH` (default: walk up from the current folder to the first folder containing `.sdd/` or `docs/specs/`), `--store PATH` (default `<project>/.sdd/graph`; `:memory:` parses into a throwaway in-memory store and writes nothing, which is how `sdd doctor` and `sdd status` run against a read-only checkout such as the reference projects) and `--json` (the result or error as JSON). Human output is plain text tables, no colour when not a TTY.
3. Exit codes: 0 ok, 1 any other error, 2 usage (`invalid_input`, `ambiguous_target`), 3 not found (`*_not_found`, `unknown_section`), 4 conflict (the 409 codes of [SPEC-07 §1](SPEC-07-dashboard-and-api.md#1-rules), and `daemon_running`), 5 `write_conflict`.
4. Write commands that edit Markdown or open the store writable (`sync`, `ids --write`) refuse with `daemon_running` while a daemon runs; the coordination commands (`claim`, `done`, …) go through its API instead.

## 2. Commands

| Command | Does |
|---|---|
| `sdd init` | Create `.sdd/config.toml` (detected paths), `.sdd/.gitignore` (locks, `daemon.json`), `.mcp.json`, `.claude/skills/sdd/SKILL.md`; print the CLAUDE.md snippet ([SPEC-05 §9](SPEC-05-agent-tools.md#9-claude-code-integration)). Never overwrites without `--force`; an existing `.mcp.json` gets the `sdd` server merged in |
| `sdd --version` | Print the `sdd` and `relate-db` versions |
| `sdd info` | Project root, store path, whether a daemon runs (and its port), node and relationship counts per label and type, schema version |
| `sdd daemon [--host 127.0.0.1] [--port 8770]` | Run the daemon ([SPEC-01 §5](SPEC-01-architecture.md#5-daemon-lifecycle)) |
| `sdd public --store PATH [--port 8780]` | Run the read-only public server ([SPEC-09 §4](SPEC-09-security.md#4-public-mode)) |
| `sdd sync [--reset]` | One full sync without a daemon (code walker, Markdown, git; [SPEC-04 §2, §4, §6](SPEC-04-sync.md)); `--reset` empties the store first, in place (graph-only state is lost; asks unless `--yes`; `--json` needs `--yes`). The `--json` result adds `code` (`added`, `updated`, `removed`, `folders`, `tests_links`, `capped`) and `git` (`added`, `removed`, `head`; `null` when skipped) |
| `sdd status` | Milestones, task counts, claims, warnings, unresolved links, unticked tasks with COMPLETES commits |
| `sdd doctor` | Reads the Markdown only and never opens the store, so it works on a read-only checkout. Every parser warning and unresolved link, deviation index mismatches, duplicate IDs; exit 1 if any `error`. The counts include tables, columns and resolved `REFERENCES` |
| `sdd ids --write [--milestone M17]` | Add stable task IDs to legacy checkbox lines ([SPEC-03 §4.2](SPEC-03-markdown-parsing.md#42-task-ids)); shows a diff and asks unless `--yes` |
| `sdd next [--milestone M] [--limit N] [--agent A]` · `sdd claim T --agent A` · `sdd release T --agent A [--reason …] [--force]` · `sdd done T --agent A [--notes …] [--files PATH]… [--commit SHA]` | The coordination tools for humans and scripts |
| `sdd deviation T --agent A --title … --amends REF… --spec-says … --does … --why … [--consequences …] [--affects …] [--resolved]` · `sdd milestone-done M --agent A --verification TEXT` | `log_deviation` and `complete_milestone` ([SPEC-05 §5–6](SPEC-05-agent-tools.md#5-log_deviation)) |
| `sdd context T [--detail milestone]` · `sdd section REF` | Print a context packet or sections |
| `sdd impact TARGET [--depth N]` · `sdd explain PATH` · `sdd find [--feature F] [--domain D] [--table T] [--spec S] [--text X]` · `sdd changes --since X [--agent A]` | [SPEC-06](SPEC-06-code-context.md) and `what_changed`. `impact` prints the target, then every non-empty group (`tables (2)`) with one line per item and its `via` chain, and `… 50 of 120` when a group is capped; `explain` prints the summary, then its groups; `find` prints one `path  (language)` line per file and `N files` (`--json` prints the result as is) |
| `sdd query CYPHER` | Read-only Cypher through the guard |
| `sdd export …` | [§3](#3-exports-and-snapshots) |
| `sdd snapshot [--out DIR]` | Checkpoint and write the committed copies ([§3](#3-exports-and-snapshots)) |
| `sdd bench …` | [SPEC-10 §5](SPEC-10-testing-and-benchmark.md#5-benchmark) |
| `sdd demo prepare --sample DIR --data DIR` | Copy the sample into a fresh working copy and apply its start state ([SPEC-11 §4](SPEC-11-deployment-and-demo.md#4-sprint-replay) step 1) |
| `sdd demo replay --sample DIR --data DIR [--seed N]` | Prepare, then run the simulated agents in a loop ([SPEC-11 §4](SPEC-11-deployment-and-demo.md#4-sprint-replay)) |
| `sdd demo serve --sample DIR --data DIR [--host] [--port 8770]` | Prepare, then run the daemon on the copy. One command, so the judges' image can keep `ENTRYPOINT ["sdd"]` ([SPEC-11 §2](SPEC-11-deployment-and-demo.md#2-compose)) |

> **DEVIATION:** see [D002](../deviations/D002-reset-empties-store-in-place.md) — `sdd sync --reset` empties the store in place instead of deleting its directory

## 3. Exports and snapshots

- `sdd export --mermaid PRESET|CYPHER [--out FILE]`: renders a preset ([SPEC-06 §5](SPEC-06-code-context.md#5-presets)) or a query result as a Mermaid `flowchart LR`. GitHub renders the output natively, so the README shows it. Rules, so that output is deterministic (golden files):
  - **Argument:** it is Cypher when it starts with `MATCH`, `OPTIONAL MATCH`, `WITH`, `UNWIND`, `CALL` or `RETURN` (any case), else a preset name. Cypher runs through the query guard ([SPEC-09 §3](SPEC-09-security.md#3-query-guard)); every result value that is a map with an `id` becomes a node, and a row with columns `source` and `target` (IDs or node maps, optional `type`, default `RELATED`) becomes an edge. Unknown IDs are dropped.
  - **Nodes:** the preset's root first, the rest sorted by `(label, id)`, at most 60; edges to dropped nodes go too and the last line is `%% truncated N nodes`. Mermaid IDs are `n0`, `n1`, … in that order. Shapes per label: Spec `[[ ]]`, Section `[ ]`, Task `( )`, Deviation `{{ }}`, File `[/ /]`, Table `[( )]`, Milestone `([ ])`, Feature `> ]`, anything else `[ ]`.
  - **Labels:** `"<id>: <title>"` (just the ID when they are equal; a Commit shows `<short sha>: <message>`; the `schema` preset shows its node title, `Table (12)`), cut to 60 characters with `…`, in double quotes with `"`, `<`, `>` written as `#quot;`, `#lt;`, `#gt;`.
  - **Edges:** `nA -->|TYPE| nB`, sorted by source, type, target; an edge with a `count` reads `|"TYPE (12)"|`.
  - **Classes:** one `classDef <label lowercased>` per label present (the dashboard's hues) and one `class` line per label; the nodes of the `schema` preset take the colour of the label they stand for.

  The `schema` preset renders labels and relationship types with counts.
- `sdd export --cypher [--out FILE]`: the whole graph as an idempotent Cypher script, used by the static demo ([SPEC-11 §6](SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)). **One statement per line, each ending in `;`**, so a loader splits on newlines: two `//` header lines (counts, no timestamp, so re-exports diff cleanly), then `MERGE (n:<Label> {id: '<id>'}) SET n += {<props>};` per node sorted by `id`, then `MATCH (a:<L> {id: '…'}), (b:<L> {id: '…'}) MERGE (a)-[r:<TYPE> {<props>}]->(b);` per relationship sorted by source, type, target. Properties are written **as stored** (a map such as `header` stays the `header_json` string, [SPEC-01 §4](SPEC-01-architecture.md#4-relate-access-and-concurrency)), keys sorted, nulls skipped. Relationship properties are part of the `MERGE` pattern, because two relationships of one type between the same nodes exist (a deviation's file and the spec note that amends the same section differ in `src`). Strings are single-quoted with backslash, quote, newline and tab escaped; a carriage return and any other unprintable character is written `\uXXXX` (Relate reads `\n` and `\t` but not `\r`). `service/exports.py` has `load_cypher(store, script)`, which runs the lines in one write job.
- `sdd export --json [--out FILE]`: `{nodes, edges}` in the `/api/graph` shape for the whole graph (no limit), nodes sorted by `id`, edges by source, type, target; also for the static demo.
- `sdd export --claude-status`: rewrites the CLAUDE.md block between `<!-- sdd:status -->` and `<!-- /sdd:status -->` ([SPEC-04 §5.1](SPEC-04-sync.md#51-edits)); the marker lines and every byte outside them stay as they are (CRLF files keep CRLF). Without the file or a marker the command fails with `invalid_input` (exit 2) and prints the two lines to add. The block, deterministic and without timestamps, is one generated line and four bullets: `**Done:**` (`M01 Title (date)` for each done milestone, in order), `**Next:**` (the first milestone not done, as a link, its open/total task count and its *Read first* sections), `**Open deviations:**` (`D003 Title (M03b)`), `**Active claims:**` (`M05a.3 by sonnet-1`); `none` where empty. The file is written through `sync/writeback.py` after re-reading it (`source_changed` if it changed meanwhile); a second run writes nothing and reports `changed: false`. Result `{path, changed}`.
- `sdd snapshot [--out .sdd/snapshots]`: writes the committed copies for judges: `graph/` (a consistent copy of the directory store that keeps the `.cypherlite.lock` markers in its root and `wal/`, which a read-only open needs, and drops `.cypherlite.writer`; O11, [D001](../deviations/D001-store-copies-keep-lock-markers.md)), `graph.rl` (single file) and `graph-json/` (readable JSON codec). These are the **only** committed stores of a project; the live `.sdd/graph/` is gitignored ([DEC-001](../decisions/DEC-001-committed-store.md)). Run it on purpose (M06a, M99, before a release); the committed copy lags the docs until the next run. Steps:
  1. **Checkpoint.** Without a daemon: open the store writable (`daemon_running` if another process holds it), checkpoint, close. With a daemon: no checkpoint, because `relate clone` reads every committed transaction.
  2. **Copies.** Delete the old `graph/`, `graph.rl` and `graph-json/` under `--out` (nothing else there). With the `relate` CLI on PATH (O3, closed: only the CLI can clone; it works beside a running daemon): `relate clone` for all three. Without it: a plain directory copy of `graph/` only when no daemon runs, and `graph.rl` and `graph-json/` are `skipped`; with a daemon and no CLI the command fails with `daemon_running` and says to install the CLI or stop the daemon. `:memory:` is `invalid_input`.
  3. **Verify.** The live store and every copy are opened read-only and their node and relationship counts per label and type compared; a mismatch is an error.
  4. **Result** `{out, copies: {graph, graph_rl, graph_json}, relate_cli, checkpointed, total_nodes, total_relationships}`, each copy `written` or `skipped`.

## 4. Acceptance checks

1. `sdd init` on a fresh fixture repo detects the specs and milestones folders and writes all files; a second run without `--force` changes nothing.
2. `sdd claim` on a claimed task exits 4 with `already_claimed` in `--json` output.
3. `sdd ids --write --yes` on the office-suite fixture gives every legacy task an ID, renumbers nothing that had one, and a re-sync shows zero `task_unstable_id` warnings.
4. `sdd export --mermaid` output for the `schema` and `impact:` presets matches golden files, and renders on GitHub (checked by hand once in M06a; no Node or Chromium in the image).
5. `sdd export --cypher` loaded into an empty in-memory Relate store reproduces the node and relationship counts.
6. `sdd export --claude-status` changes only the text between the markers.
7. `sdd snapshot` output opens with `relate.connect(…, read_only=True)` and has the same counts as the live store.
