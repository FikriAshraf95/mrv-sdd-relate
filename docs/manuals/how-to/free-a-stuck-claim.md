# Free a stuck claim when an agent crashed

> **For:** orchestrators and people. **Symptom:** a task sits *In progress* on the Board with an agent's chip, but that agent is gone.

## Find it

```bash
sdd status
```

The `claims:` line lists every live claim (`M05a.3 by sonnet-3`). The MCP `status` tool also gives each claim's age. On the Board, the card shows the holder's chip.

## Free it now

As the orchestrator (MCP):

```
release_task(task_id="M05a.3", agent="opus-orch", reason="sonnet-3 crashed", force=true)
```

As a person (CLI):

```bash
sdd release M05a.3 --agent me --reason "sonnet-3 crashed" --force
```

Result:

```json
{"task": "M05a.3", "released": true, "claimed_by": "sonnet-3", "forced": true, "synced_at": "…"}
```

The task is back to `todo`, the card returns to *To do*, and the event log records a `task_released` event with `actor` = the old holder and `data.forced_by` = you. Then relaunch a worker for it.

Without `--force`, `release` only works for the claim holder. Anyone else gets `not_claimed_by_you` (exit code 4).

## Or let it expire

A claim goes **stale** when its holder hasn't made any tool call that passes `agent` for longer than `SDD_CLAIM_TTL` (default **2 hours**). After that, any agent can simply `claim_task` it. The claim moves over and a `task_released` event (actor `sync`) is recorded first.

The TTL is long on purpose: a working agent may go quiet during a long build or test run. Any tool call with `agent`, reads included, keeps it alive. Change the TTL with the `SDD_CLAIM_TTL` environment variable (seconds) on the daemon.

## Other ways a claim ends

- **The agent completes the task** (`complete_task`), or gives it back (`release_task` without force).
- **A person ticks the box by hand** in the milestone file. The task is done, whoever held it, and the claim is cleared.
- **The task line is deleted** from the milestone. The claim goes with the task (`task_released`, actor `sync`).
- **`sdd sync --reset`** drops all claims, along with the other graph-only state.

## Partial work

Releasing a claim doesn't touch code. Check the crashed agent's working tree changes (`git status`) before the next worker starts, and either keep them (tell the new worker) or discard them.
