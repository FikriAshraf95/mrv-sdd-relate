# SPEC-08 — CLI and exports

> **Status:** v1 (2026-11-21) · **Owner of:** every `sdd` command, Mermaid / Cypher / JSON exports, snapshots of the store, the CLAUDE.md status block

## 1. Rules

1. `sdd` is a Typer app. Commands call the daemon API when a daemon runs for the project ([SPEC-01 §1](SPEC-01-architecture.md#1-process-model) rule 3), otherwise `service/` directly on a read-only snapshot (reads) or the store (writes).
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
| `sdd sync [--reset]` | One full sync without a daemon; `--reset` deletes the store first (graph-only state is lost; asks unless `--yes`) |
| `sdd status` | Milestones, task counts, claims, warnings, unresolved links, unticked tasks with COMPLETES commits |
| `sdd doctor` | Every parser warning and unresolved link, deviation index mismatches, duplicate IDs; exit 1 if any `error` |
| `sdd ids --write [--milestone M17]` | Add stable task IDs to legacy checkbox lines ([SPEC-03 §4.2](SPEC-03-markdown-parsing.md#42-task-ids)); shows a diff and asks unless `--yes` |
| `sdd next` · `sdd claim T --agent A` · `sdd release T --agent A [--force]` · `sdd done T --agent A [--notes] [--files]` | The coordination tools for humans and scripts |
| `sdd deviation T --agent A --title … --amends REF… --spec-says … --does … --why … [--consequences …] [--affects …]` · `sdd milestone-done M --agent A --verification TEXT` | `log_deviation` and `complete_milestone` ([SPEC-05 §5–6](SPEC-05-agent-tools.md#5-log_deviation)) |
| `sdd context T [--detail milestone]` · `sdd section REF` | Print a context packet or sections |
| `sdd impact TARGET` · `sdd explain PATH` · `sdd find …` · `sdd changes --since X` | [SPEC-06](SPEC-06-code-context.md) and `what_changed` |
| `sdd query CYPHER` | Read-only Cypher through the guard |
| `sdd export …` | [§3](#3-exports-and-snapshots) |
| `sdd snapshot [--out DIR]` | Checkpoint and write the committed copies ([§3](#3-exports-and-snapshots)) |
| `sdd bench …` | [SPEC-10 §5](SPEC-10-testing-and-benchmark.md#5-benchmark) |
| `sdd demo prepare --sample DIR --data DIR` | Copy the sample into a fresh working copy and apply its start state ([SPEC-11 §4](SPEC-11-deployment-and-demo.md#4-sprint-replay) step 1) |
| `sdd demo replay --sample DIR --data DIR [--seed N]` | Prepare, then run the simulated agents in a loop ([SPEC-11 §4](SPEC-11-deployment-and-demo.md#4-sprint-replay)) |
| `sdd demo serve --sample DIR --data DIR [--host] [--port 8770]` | Prepare, then run the daemon on the copy. One command, so the judges' image can keep `ENTRYPOINT ["sdd"]` ([SPEC-11 §2](SPEC-11-deployment-and-demo.md#2-compose)) |

## 3. Exports and snapshots

- `sdd export --mermaid PRESET|CYPHER [--out FILE]`: renders a preset ([SPEC-06 §5](SPEC-06-code-context.md#5-presets)) or a query result as a Mermaid `flowchart LR`. Node shapes per label (Spec `[[ ]]`, Section `[ ]`, Task `( )`, Deviation `{{ }}`, File `[/ /]`, Table `[( )]`), class colours per label, IDs sanitised, labels escaped, max 60 nodes (then `%% truncated N nodes`). The `schema` preset renders labels and relationship types with counts. GitHub renders the output natively, so the README shows it.
- `sdd export --cypher [--out FILE]`: the whole graph as an idempotent Cypher script (`MERGE` per node by `id`, then relationships), used by the static demo ([SPEC-11 §6](SPEC-11-deployment-and-demo.md#6-static-demo-github-pages)).
- `sdd export --json [--out FILE]`: `{nodes, edges}` in the `/api/graph` shape, also for the static demo.
- `sdd export --claude-status`: rewrites the CLAUDE.md block between `<!-- sdd:status -->` markers ([SPEC-04 §5.1](SPEC-04-sync.md#51-edits)): done milestones, the next milestone with its *Read first*, open deviations, active claims. Hand-written text outside the markers never changes.
- `sdd snapshot [--out .sdd/snapshots]`: checkpoints, then writes the committed copies for judges: `graph/` (a consistent copy of the directory store, without lock files), `graph.rl` (single file, via `relate clone`) and `graph-json/` (readable JSON codec); the last two as far as the tooling allows (open item O3). These are the **only** committed stores of a project; the live `.sdd/graph/` is gitignored ([DEC-001](../decisions/DEC-001-committed-store.md)). Run it on purpose (M06a, M99, before a release); the committed copy lags the docs until the next run.

## 4. Acceptance checks

1. `sdd init` on a fresh fixture repo detects the specs and milestones folders and writes all files; a second run without `--force` changes nothing.
2. `sdd claim` on a claimed task exits 4 with `already_claimed` in `--json` output.
3. `sdd ids --write --yes` on the office-suite fixture gives every legacy task an ID, renumbers nothing that had one, and a re-sync shows zero `task_unstable_id` warnings.
4. `sdd export --mermaid` output for the `schema` and `impact:` presets matches golden files, and renders on GitHub (checked by hand once in M06a; no Node or Chromium in the image).
5. `sdd export --cypher` loaded into an empty in-memory Relate store reproduces the node and relationship counts.
6. `sdd export --claude-status` changes only the text between the markers.
7. `sdd snapshot` output opens with `relate.connect(…, read_only=True)` and has the same counts as the live store.
