# Troubleshooting and FAQ

> Organised by what you see. Start with `sdd info` (is a daemon running, does the store exist, counts) and `sdd doctor` (parser warnings).

## Store is locked / `daemon_running`

**You see:** `error (daemon_running): …` and **exit code 4**, from `sdd daemon`, `sdd sync`, `sdd ids --write` or `sdd snapshot`.

**Why:** one process owns a store. Another daemon, or another `sync`, holds the writer lock.

**Check:**

```bash
sdd info                                  # "daemon: running on :8770 (pid 1234)" or "none"
cat .sdd/daemon.json                      # pid, port, started_at of the daemon that claims it
curl -s http://127.0.0.1:8770/api/health  # answers if it's alive; compare "project"
```

**Fix:**
- You meant to talk to the running daemon: you don't need a second one. Use `sdd status`, the dashboard, or MCP.
- You need `sync` or `ids --write`: stop the daemon (Ctrl+C or `docker stop sdd-daemon`), run the command, start it again. For a full scan without stopping, `POST /api/sync` instead.
- The daemon is in another container or terminal you forgot: `docker ps`, or find the pid from `daemon.json`.
- **Stale `daemon.json`?** It's ignored when nothing answers the health call, and a killed writer leaves no stale lock, so the next start works. You never need to delete lock files by hand.
- `sdd snapshot` with a daemon running needs the `relate` CLI on `PATH` ([Snapshot](how-to/snapshot-and-share.md)).

**Exit code 5** is `write_conflict`: a write retried three times (50/200/800 ms) and still conflicted. It's rare and retryable; run the command again.

## Daemon not reachable, or port already in use

**You see:** `address already in use` when starting the daemon, or connection refused from Claude Code, the CLI or the browser.

- **Port taken:** another process uses 8770 (often another `sdd daemon`, the judges' `docker compose up`, or the dev container). Find it with `lsof -i :8770` (macOS/Linux) or `netstat -ano | findstr 8770` (Windows), or use another port: `sdd daemon --port 8771`. Then update the URL in `.mcp.json` to match.
- **Daemon in Docker but unreachable:** check you published the port (`-p 127.0.0.1:8770:8770`), bound `--host 0.0.0.0` inside the container, and set `SDD_ALLOW_REMOTE=1`. `docker logs sdd-daemon` shows startup errors.
- **Refuses to start with a non-loopback `--host`:** outside a container that needs both `SDD_ALLOW_REMOTE=1` and `SDD_TOKEN` ([Remote access](how-to/token-and-remote-access.md)).
- **403 `forbidden_host`:** you're using a host name other than `localhost`/`127.0.0.1`. Add it to `SDD_ALLOWED_HOSTS`.
- **401 `unauthorized`:** `SDD_TOKEN` is set on the daemon; send `Authorization: Bearer …`. The dashboard asks once per tab.

## `sdd doctor` warnings

| Warning | Fix |
|---|---|
| `task_unstable_id` | task lines without `**M02.3**` IDs: `sdd ids --write` |
| `task_duplicate_id` (error) | two tasks share an ID in one file: give one the next free number |
| `task_id_mismatch` | the ID's milestone part doesn't match the file: fix the ID |
| `task_bad_after` | `(after X)` where X isn't a task ID: fix the reference |
| `bad_filename` (error) | a file matched a glob but its name has no `SPEC-NN`/`M<nn>`/`D<nnn>`: rename it, or narrow the glob in `.sdd/config.toml` |
| `h1_id_mismatch` | the H1 says `SPEC-04` but the file is `SPEC-03-…`: align them (the file name wins) |
| `missing_h1` | add `# SPEC-03 — Title` (or `# M02 — Title`, `# D006 — Title`) |
| `duplicate_id` | two files produce the same ID (a milestone copied into `done/` without deleting the original?): remove one |
| unresolved links (`unresolved X: …`) | a link or reference points at nothing: a renamed or renumbered heading, a spec not written yet, a typo. Fix the link, or leave it until the target exists |
| `deviation_index_mismatch` | add the missing index row or file (or let `log_deviation` do both next time) |
| `deviation_missing_section` | add the missing `## Spec says` / `## Implementation does` / `## Why` / `## Consequences` |
| `feature_glob_empty` | a Feature's `Implements` globs match no file: fix the glob (project-relative, gitignore style) |
| `link_moved` (info) | a link points at a file's old path; it still resolves by ID. `complete_milestone` rewrites links itself; fix hand-moved ones when convenient |

Full list: [Repo format → Warning codes](reference/repo-format.md#warning-codes). `doctor` exits 1 only on `error`.

**`doctor` finds no milestones/specs at all:** your files aren't where the globs look. Run `sdd init` to detect them, or set the globs in `.sdd/config.toml`. Milestone file names must match `M<digits>[letter]-<name>.md`.

## Claude Code doesn't list the sdd tools

1. **Is `.mcp.json` in the folder you started Claude Code in?** It must contain:

   ```json
   { "mcpServers": { "sdd": { "type": "http", "url": "http://localhost:8770/mcp" } } }
   ```

   `"type": "http"` matters: SDD Graph is never started over stdio. Run `sdd init` to add the entry (it merges into an existing file).
2. **Is the daemon running?** `curl -s http://127.0.0.1:8770/api/health`.
3. **Did you approve the server?** Claude Code asks before using project MCP servers. Check `/mcp`: `sdd` should be *connected* with 14 tools. Reconnect from there after starting the daemon.
4. **Token set?** The entry needs `"headers": {"Authorization": "Bearer ${SDD_TOKEN}"}`, and Claude Code must be started from a shell where `SDD_TOKEN` is exported.
5. **Different port?** The URL must match `--port`.

## The graph looks out of date

- **Check `synced_at`** in any result, or the dashboard footer.
- **Edits through a Docker bind mount aren't seen:** inside containers, watching must poll (`SDD_WATCH=poll`, the default when `/.dockerenv` exists). Native events don't cross bind mounts on Windows or macOS.
- **Code changes take a while:** the code poll runs every 10 s at least, and backs off to 10 × its own duration on big trees (a 20,000-file tree through a Windows bind mount polls about every 5 minutes). Markdown is polled every second regardless. Commits are picked up within 3 s.
- **A file isn't in the graph at all:** it's ignored by `.gitignore`, `.sddignore` or the built-in list (`node_modules`, `dist`, `build`, …), or the tree exceeds `SDD_MAX_FILES` (20,000).
- **Force a full scan:** `curl -X POST http://127.0.0.1:8770/api/sync`, or restart the daemon (startup always does a full scan).
- **Still wrong:** [rebuild from scratch](how-to/rebuild-the-graph.md) with `sdd sync --reset`.

## A tool fails with `source_changed`

Someone edited the target away between your read and your write: the task line was deleted or its ID changed, or the section was renamed. Write-back finds targets by ID just before editing, never by line number, so ordinary edits nearby are fine. Re-read and retry.

## A task is stuck *In progress*

An agent crashed holding it. `release_task(…, force=true)` or `sdd release T --agent me --force`. See [Free a stuck claim](how-to/free-a-stuck-claim.md).

## `next_tasks` returns nothing, but there's work left

- The remaining tasks wait on unfinished tasks (`(after …)`) or the milestone `Depends on` an unfinished milestone. `sdd status` and the `task_blocked` details show which.
- They're claimed: `sdd status` lists the claims.
- They're ticked: check the checkboxes.

## Context packets are big

The task lines link no sections, so the packet falls back to the whole *Read first* list. Link the sections each task implements ([how](how-to/link-tasks-to-sections.md)). Also check `always_include` isn't pulling in long sections.

## Windows notes

- **Run it in Docker** ([Install, option B](how-to/install.md#option-b-docker-no-python-on-the-host)). Polling is chosen automatically inside the container, and it's required because inotify doesn't see Windows edits through a bind mount.
- **Git Bash rewrites container paths.** Prefix commands that pass paths like `/repo` with `MSYS_NO_PATHCONV=1`.
- **PowerShell:** use `-v "${PWD}:/repo"`, and `$env:SDD_TOKEN = "…"` to set variables.
- **Line endings:** write-back keeps CRLF files CRLF and LF files LF.
- **Paths in the graph** are always POSIX (`src/booking/overlap.py`). `explain` accepts backslashes and turns them into slashes.
- **Slow code polls through the bind mount** are expected (about 1.5 ms per file). Markdown stays fast because it's polled separately.
- **Docker Desktop data on another drive:** move Docker's disk image off a full C: drive in Docker Desktop's settings. Everything SDD Graph builds lives in images and volumes.

## FAQ

**Does it change my files without asking?** Only the write-back edits: ticking a box on `complete_task`, the deviation file + index row + spec note on `log_deviation`, the status line and move on `complete_milestone`, and the CLAUDE.md block on `export --claude-status`. It never commits, and never edits spec prose. `writeback = false` turns edits off.

**Can I keep editing Markdown by hand?** Yes. That's the point. Hand ticks, new tasks, spec edits and deviation edits are all picked up. Just don't hand-edit a task the tools are working on.

**What if I delete `.sdd/graph/`?** The next daemon start rebuilds it from your files. You lose claims, agent records and event history.

**Does it work without Claude Code?** Yes. Any MCP client that speaks streamable HTTP can connect. People use the CLI and the dashboard, and scripts can use the HTTP API.

**Can two repos share one daemon?** No. One daemon per repo; run the second on another port (`--port 8771`) and point its `.mcp.json` there.

**Is my code uploaded anywhere?** No. Everything runs locally. Only `sdd bench --exact` sends text to the Anthropic API, and only if you ask it to.
