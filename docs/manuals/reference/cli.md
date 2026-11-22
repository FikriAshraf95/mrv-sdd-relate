# CLI reference

> Complete list of `sdd` commands. The source of truth is [SPEC-08 §2](../../specs/SPEC-08-cli-and-exports.md#2-commands). Run `sdd <command> --help` for the same information in your terminal.

## Global behaviour

**Global options.** These work before the command (`sdd --json status`) or after it (`sdd status --json`). The value given after the command wins.

| Option | Default | Meaning |
|---|---|---|
| `--project PATH` | walk up from the current folder to the first one containing `.sdd/` or `docs/specs/` | the project root |
| `--store PATH` | `<project>/.sdd/graph` | the store directory. `:memory:` parses into a throwaway in-memory store and writes nothing (works on read-only checkouts) |
| `--json` | off | print the result, or the error, as JSON on stdout |
| `--version` | | print the `sdd` and `relate-db` versions |

**Daemon or not.** If a daemon runs for the project (found through `.sdd/daemon.json` plus a health check on `127.0.0.1:<port>`), read and coordination commands go through its API. Otherwise read commands open a **read-only** snapshot of the store (creating no lock files), and write commands open the store themselves. `sync` and `ids --write` refuse with `daemon_running` while a daemon runs. Exports and `snapshot` read the store files directly either way.

**Output.** Human output is plain text, without colour when stdout isn't a terminal. Errors print `error (<code>): <message>` on stderr, or the JSON error shape with `--json`.

### Exit codes

| Code | Meaning | Error codes |
|---|---|---|
| 0 | ok | |
| 1 | any other error, or `doctor` found an `error` warning | everything not listed below |
| 2 | usage | `invalid_input`, `ambiguous_target` |
| 3 | not found | `task_not_found`, `milestone_not_found`, `node_not_found`, `file_not_found`, `unknown_section` |
| 4 | conflict | `already_claimed`, `task_done`, `task_blocked`, `not_claimed_by_you`, `milestone_incomplete`, `source_changed`, `daemon_running` |
| 5 | write conflict (retryable) | `write_conflict` |

See [Error codes](error-codes.md) for what each means.

---

## Setup and inspection

### `sdd init`

```bash
sdd init [--force] [--project DIR] [--json]
```

Sets a project up. Writes `.sdd/config.toml` (the document globs it detected), `.sdd/.gitignore` (live store, `daemon.json`, locks), `.mcp.json` (merges an `sdd` server at `http://localhost:8770/mcp` into any existing file, keeping other servers) and `.claude/skills/sdd/SKILL.md` (the agent protocol). It then prints a CLAUDE.md snippet. Nothing that exists is overwritten without `--force`; an existing `sdd` entry in `.mcp.json` is replaced only with `--force`. With `SDD_TOKEN` set, the `.mcp.json` entry gets `"headers": {"Authorization": "Bearer ${SDD_TOKEN}"}`. `--json` returns `{project, paths, files: [{path, action}], snippet}`.

### `sdd info`

```bash
sdd info
```

Project root, store path (and whether it exists yet), whether a daemon runs (port, pid), the code's schema version and the store's, node counts per label, relationship counts per type.

### `sdd doctor`

```bash
sdd doctor [--project DIR]
```

Parses the Markdown only and **never opens the store**, so it works on any checkout, even read-only. Lists every parser warning grouped by file, every unresolved link, deviation index mismatches and duplicate IDs, then counts (specs, sections, milestones, tasks, deviations, tables, columns, resolved references, legacy task lines, unresolved links). **Exit 1 if any warning has severity `error`.** Warning codes: [Repo format](repo-format.md#warning-codes).

### `sdd status`

```bash
sdd status
```

Every milestone with its status and `done/total`, every task with its checkbox and claimer, live claims, unresolved links, tasks that are unticked although a commit says it completes them, warning counts, and a note when write-back is off.

### `sdd ids`

```bash
sdd ids [--write] [--milestone M17] [--yes]
```

Adds stable IDs (`**M17.5**`) to legacy checkbox lines without one, numbering after the highest existing number in each file. Without `--write`, it only prints the diff. With `--write`, it asks before rewriting unless `--yes` (`--json` requires `--yes`). Never renumbers a line that already has an ID. Refused while a daemon runs.

### `sdd sync`

```bash
sdd sync [--reset] [--yes]
```

One full sync without a daemon: code walker, Markdown, git. `--reset` empties the store first, in place; graph-only state (claims, agents, events) is lost. It asks unless `--yes` (`--json` requires `--yes`). Refused while a daemon runs (use `POST /api/sync` instead). `--json` adds `code` (`added`, `updated`, `removed`, `folders`, `tests_links`, `capped`) and `git` (`added`, `removed`, `head`; `null` when skipped).

---

## Servers

### `sdd daemon`

```bash
sdd daemon [--host 127.0.0.1] [--port 8770]
```

Runs the daemon: opens the store writable, creates indexes, runs a startup sync, then watches files, polls git, and serves `/mcp`, `/api` and the dashboard. Writes `.sdd/daemon.json` once the socket is bound; on SIGTERM or Ctrl+C it drains the queue, checkpoints and removes the file. Exits with `daemon_running` if another daemon or writer holds the store. Binding beyond loopback needs `SDD_ALLOW_REMOTE=1` and `SDD_TOKEN` (inside a container, `SDD_ALLOW_REMOTE=1` alone).

### `sdd public`

```bash
sdd public --store PATH [--project DIR] [--host 127.0.0.1] [--port 8780]
```

Runs the read-only public server on a store, re-opening it when its `manifest.json` changes (checked every 2 s). `--project` defaults to `PATH/../..` when `PATH` ends in `.sdd/graph`, else it's required. No `/mcp`, no writes. See [Public mode](../how-to/public-mode.md).

---

## Coordination

`--agent` is your agent name, the same every session. It's required on writes; on reads it's optional and marks you as alive.

### `sdd next`

```bash
sdd next [--milestone M] [--limit 10] [--agent A]
```

Claimable tasks in order, each with the claimed tasks it overlaps (`[overlaps M05a.2 (sonnet-2)]`). Prints `No claimable tasks.` when none.

### `sdd claim`

```bash
sdd claim T --agent A
```

Atomic claim. Re-claiming your own task succeeds. Errors: `already_claimed`, `task_done`, `task_blocked`, `task_not_found` (exit 4 or 3).

### `sdd release`

```bash
sdd release T --agent A [--reason TEXT] [--force]
```

Gives a claim back. `--force` frees a claim someone else holds.

### `sdd done`

```bash
sdd done T --agent A [--notes TEXT] [--files PATH]... [--commit SHA]
```

Completes the task: ticks its box (write-back), records notes and files in the event, links the commit, returns the newly unblocked tasks. You must hold the claim. `--files` repeats.

### `sdd deviation`

```bash
sdd deviation T --agent A --title TEXT --amends REF... --spec-says TEXT --does TEXT --why TEXT \
  [--consequences TEXT] [--affects PATH_OR_TABLE]... [--resolved]
```

Logs a deviation raised in task `T`: file, index row and spec notes. `--amends` and `--affects` repeat. See [Log a deviation](../how-to/log-a-deviation.md).

### `sdd milestone-done`

```bash
sdd milestone-done M --agent A --verification TEXT
```

Writes the DONE status line, moves the file (and plan) to `done/` if that folder exists, and rewrites links to it. Fails with `milestone_incomplete` if a task isn't done.

---

## Reading the graph

### `sdd context`

```bash
sdd context T [--detail task|milestone] [--max-chars 24000] [--agent A]
```

Prints a task's context packet: each section with why it's included, the deviations, the outline, and the size (`3122 chars (~781 tokens)`). `--detail milestone` includes every *Read first* section in full.

### `sdd section`

```bash
sdd section REF...
sdd section "SPEC-03 §4.2" "SPEC-02 \`bookings\`"
```

Prints sections by reference, each with its subsections.

### `sdd changes`

```bash
sdd changes --since X [--agent A]
```

`X` is an ISO time, an event ID, or `last_session` (needs `--agent`). One line per change: time, group, ID, title, actor.

### `sdd impact`

```bash
sdd impact TARGET [--depth 3]
```

Prints the target, then every non-empty group with one line per item and its `via` chain, and `… 50 of 120` when a group is capped. `TARGET` is a table, `table.column`, spec reference, task, milestone, deviation, file, feature or prefixed ID. Depth 1 to 5. See [Impact and explain](../how-to/impact-and-explain.md).

### `sdd explain`

```bash
sdd explain PATH
```

Prints the summary, then features, sections, tasks, commits, deviations and checks with their `via` chains. A unique tail of the path is enough.

### `sdd find`

```bash
sdd find [--feature F] [--domain D] [--table T] [--spec S] [--text X]
```

One `path  (language)` line per file, then `N files`. At least one option; several intersect.

### `sdd query`

```bash
sdd query CYPHER [--params JSON]
sdd query 'MATCH (t:Task {status: $s}) RETURN t.id' --params '{"s": "todo"}'
```

Read-only Cypher through the query guard (no writes or `CALL`, `*..4` at most, 100 rows, 5 s). Prints tab-separated columns and JSON values, then `(truncated at 100 rows)` if capped. See [Example queries](cypher-examples.md).

---

## Exports and snapshots

### `sdd export`

```bash
sdd export --mermaid PRESET_OR_CYPHER [--out FILE]
sdd export --cypher [--out FILE]
sdd export --json [--out FILE]
sdd export --claude-status
```

Exactly one mode. Without `--out`, the output goes to stdout. Here `--json` names the export format; the global `--json` (before the command) still switches result output. Presets: `schema`, `milestone:<id>`, `impact:<target>`, `explain:<path>`, `lineage:<section>`, `feature:<slug>`. See [Export diagrams and status](../how-to/export-diagrams-and-status.md) and [Snapshot and share](../how-to/snapshot-and-share.md).

### `sdd snapshot`

```bash
sdd snapshot [--out .sdd/snapshots]
```

Checkpoints (when no daemon runs), writes `graph/`, `graph.rl` and `graph-json/` (the last two need the `relate` CLI), and verifies their counts against the live store. `:memory:` is `invalid_input`.

### `sdd site`

```bash
sdd site [--sample samples/courtside] [--out site] [--wasm-dir DIR] [--seed 1]
```

Builds the static demo folder from a sample's committed store: the dashboard files, `data/` with precomputed answers, `graph.cypher`, `graph.json` and a recorded replay, plus `wasm/` when `--wasm-dir` points at an unpacked `@relate/relate-wasm` package (the build never downloads). `--out` is deleted and rewritten. Refuses the repo root, `src/`, or a non-empty folder that isn't a previous site.

---

## Benchmark

All three work on a temporary copy of `--project`, print a table, and write `<date>.json` and `<date>.md` to `--out` (default `bench/results`).

```bash
sdd bench context [--milestone M]... [--exact]
sdd bench restart [--exact]
sdd bench collisions [--agents 10] [--tasks 30] [--runs 5]
```

`--exact` counts tokens with the Anthropic API (needs `ANTHROPIC_API_KEY`). See [Measure savings](../how-to/measure-savings.md).

---

## Demo (the bundled sample)

```bash
sdd demo prepare --sample DIR --data DIR      # clone <sample>.bundle into <data>/run, apply replay.toml's start state
sdd demo replay  --sample DIR --data DIR [--seed N]               # prepare, then simulated agents in a loop
sdd demo serve   --sample DIR --data DIR [--host 127.0.0.1] [--port 8770]   # prepare, then the daemon on the copy
```

These power `docker compose up` (`demo serve`) and the hosted demo (`demo replay`). `replay.toml` keys: `[start] unticked`, `[run] milestones` and `verification`, optional `[[task]]` outcomes and `[[deviation]]` entries. Tuning: `SDD_REPLAY_TICK`, `SDD_REPLAY_MAX_MIN`, `SDD_REPLAY_SEED` ([Configuration](configuration.md)).
