# Configuration reference

SDD Graph reads two sources: **`.sdd/config.toml`** in the project (what to parse, and how) and **environment variables** (how the processes run). Nothing else; command-line flags are listed in the [CLI reference](cli.md).

## `.sdd/config.toml`

`sdd init` writes this file with the globs it detected. Every key is optional; a missing key uses the default. **An unknown key is an error** (`invalid_input`, naming the known keys), so typos fail loudly.

### Document globs

Each is a glob string or a list of globs, project-relative, gitignore-style.

| Key | Default | What matches |
|---|---|---|
| `specs` | `["docs/specs/SPEC-*.md"]` | spec files |
| `milestones` | `["docs/milestones/**/M*.md"]` | milestone files. Only names matching `M<digits>[letter]-<name>.md` count, and `*-plan.md` is excluded |
| `plans` | `["docs/milestones/**/M*-plan.md"]` | plan files (`M05a-plan.md` → a Doc with `PLANS` → `M05a`) |
| `deviations` | `["docs/deviations/D*.md"]` | deviation files |
| `deviation_index` | `["docs/DEVIATIONS.md"]` | the deviation index (cross-checked; write-back inserts rows here) |
| `docs` | `["**/CLAUDE.md", "docs/IDEA.md", "docs/design-system.md", "HANDOFF.md", "README.md"]` | other documents, indexed as Doc nodes with their links |
| `schema_specs` | `["docs/specs/SPEC-*schema*.md"]` | specs whose table sections become Table and Column nodes |
| `tests` | `["tests/**", "**/*Tests/**", "**/*.test.ts", "**/test_*.py", "**/*_test.go"]` | test files (`is_test`, and scanned for `spec<NN>_ac<N>` names) |

### Behaviour

| Key | Type | Default | Meaning |
|---|---|---|---|
| `writeback` | bool | `true` | `false` turns off all Markdown edits. `complete_task` then records completion in the graph only, and `log_deviation` / `complete_milestone` fail with `writeback_disabled` |
| `always_include` | list of spec references | `["SPEC-00 §6"]` | sections every context packet carries in full. A reference that doesn't resolve is skipped. Use `[]` for none |

### Example

```toml
# SDD Graph configuration
specs = ["design/specs/SPEC-*.md"]
milestones = ["design/milestones/**/M*.md"]
plans = ["design/milestones/**/M*-plan.md"]
deviations = ["design/deviations/D*.md"]
deviation_index = ["design/DEVIATIONS.md"]
docs = ["CLAUDE.md", "README.md", "design/decisions/*.md"]
schema_specs = ["design/specs/SPEC-02-data-model.md"]
always_include = ["SPEC-00 §4", "SPEC-00 §5"]
writeback = true
```

> A nested `CLAUDE.md` in test fixtures or vendored folders would be picked up by `**/CLAUDE.md`. List the ones you want explicitly (as this repo does) to avoid that.

## Ignore files

The code walker and the watcher skip:

- paths matched by **`.gitignore`** files (each folder's file applies beneath it; a deeper file can't un-ignore what a shallower one ignored),
- paths matched by **`.sddignore`** in the project root (gitignore syntax). Use it to keep folders out of the graph that git tracks, such as a bundled sample or generated docs,
- the built-in list, as any path segment: `.git`, `.sdd`, `node_modules`, `.venv`, `venv`, `__pycache__`, `dist`, `build`, `bin`, `obj`, `.next`, `coverage`, `target`.

There is no blanket rule for dot-folders: `.claude/` and `.github/` are walked. Ignore files are re-read on each code poll, so edits take effect without a restart.

## Environment variables

### Daemon and sync

| Variable | Default | Meaning |
|---|---|---|
| `SDD_WATCH` | `auto` | `auto` (polling when `/.dockerenv` exists, native events otherwise), `poll` or `native`. Polling is required for Docker bind mounts on Windows and macOS |
| `SDD_POLL_INTERVAL` | `1` | seconds between polls of the SDD documents |
| `SDD_POLL_CODE_INTERVAL` | `10` | minimum seconds between code polls. The code poll backs off to 10 × its own duration on large trees |
| `SDD_MAX_FILES` | `20000` | soft cap on code files; beyond it the first N by path are kept and a warning is logged |
| `SDD_GIT_MAX_COMMITS` | `2000` | commits read on the first git sync, and the reachability window after a history rewrite |
| `SDD_CLAIM_TTL` | `7200` | seconds without any call carrying `agent` before that agent's claims go stale |

### Security and serving

| Variable | Default | Meaning |
|---|---|---|
| `SDD_TOKEN` | unset | bearer token for every `/api` and `/mcp` request on the daemon. Also sent by the CLI, and named (not written) in `.mcp.json` by `sdd init` |
| `SDD_ALLOW_REMOTE` | off | `1`/`true`/`yes`/`on` allows binding beyond loopback. Outside a container this also needs `SDD_TOKEN` |
| `SDD_ALLOWED_HOSTS` | empty | comma-separated extra host names accepted in the `Host` header |
| `SDD_PUBLIC_QUERY` | `guarded` | public mode: `guarded` (read-only Cypher through the guard) or `presets` (presets only) |
| `SDD_QUERY_MEMORY_MB` | `1024` | address-space cap of the guarded-query worker process (`0` = none) |
| `SDD_TRUSTED_PROXY_NET` | unset | CIDR whose requests may set the client IP via `CF-Connecting-IP` / `X-Forwarded-For` (public mode rate limiting) |
| `PUBLIC_BASE_URL` | unset | public URL shown in the dashboard footer and returned by `/api/health` |
| `SDD_PROJECT_NAME` | project folder name | the name `/api/health` reports and the dashboard header shows |

### Demo replay

| Variable | Default | Meaning |
|---|---|---|
| `SDD_REPLAY_TICK` | `4` | seconds per replay tick |
| `SDD_REPLAY_MAX_MIN` | `20` | minutes before the replay resets even if unfinished |
| `SDD_REPLAY_SEED` | unset | seed for `sdd demo replay` when `--seed` isn't given |

### Benchmark

| Variable | Meaning |
|---|---|
| `ANTHROPIC_API_KEY` | used only by `sdd bench … --exact` to count tokens exactly. Keep it in your environment, never in a file |

Numeric variables must be non-negative numbers, and choice variables one of their listed values. Anything else is `invalid_input` at startup.

## Files SDD Graph creates

| Path | What | Commit? |
|---|---|---|
| `.sdd/config.toml` | configuration | yes |
| `.sdd/.gitignore` | ignores the live store, `daemon.json`, locks | yes |
| `.sdd/graph/` | the live Relate store | **never** |
| `.sdd/daemon.json` | the running daemon's pid, host, port, instance ID, token hash, start time | never |
| `.sdd/snapshots/` | `sdd snapshot` output | yes, when you want to share it |
| `.mcp.json` | Claude Code MCP server entry | yes |
| `.claude/skills/sdd/SKILL.md` | the agent protocol | yes |
