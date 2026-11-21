# M03a — Coordination tools: claims, deviations, changes

> **Depends on:** [M02](done/M02-sync-daemon.md) · **Blocks:** [M03b](M03b-context-and-integration.md)
> **Read first:** [SPEC-05 §1–3, §5–8](../specs/SPEC-05-agent-tools.md#1-rules) · [SPEC-04 §5](../specs/SPEC-04-sync.md#5-write-back) · [SPEC-02 §2](../specs/SPEC-02-graph-schema.md#2-planning-layer) · [SPEC-07 §1–2](../specs/SPEC-07-dashboard-and-api.md#1-rules) · [SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands)
> **Model:** Opus. Atomic claims, stale and forced releases, and deviation write-back under concurrency.
> **Split from:** M03 (2026-11-21)

## Goal
Agents can coordinate through the daemon: find claimable tasks, claim atomically, release (also by force), complete tasks and milestones with write-back, log deviations exactly as the manual ritual does, and ask what changed. Exposed over MCP, HTTP and the CLI. The context packet, the query guard and the Claude Code setup follow in M03b.

## Tasks
### Services
- [ ] **M03a.1** `service/coordination.py`: `next_tasks` with `overlaps`, `claim_task`, `release_task` (incl. `force`), stale claims (2 h TTL), `complete_task`, `complete_milestone` with the file move and link rewrite ([SPEC-05 §3, §6](../specs/SPEC-05-agent-tools.md#3-claims), [SPEC-04 §5.1](../specs/SPEC-04-sync.md#51-edits)).
- [ ] **M03a.2** `log_deviation`: numbering inside the write job, file from the template with the task and **Affects:** fields, index row, spec notes ([SPEC-05 §5](../specs/SPEC-05-agent-tools.md#5-log_deviation), [SPEC-04 §5.1](../specs/SPEC-04-sync.md#51-edits)). (after M03a.1)
- [ ] **M03a.3** `service/changes.py`: `what_changed` with `last_session` = since the agent's last call, Agent `last_seen` / `last_changes_at` ([SPEC-05 §7](../specs/SPEC-05-agent-tools.md#7-what_changed)).
### Surfaces
- [ ] **M03a.4** `mcp/server.py`: tools 1–4 and 7–10, `agent` on every tool, the protocol in `instructions`; mounted at `/mcp` ([SPEC-05 §2](../specs/SPEC-05-agent-tools.md#2-tool-index)). (after M03a.1, M03a.2, M03a.3)
- [ ] **M03a.5** HTTP endpoints 5, 12, 17, 18 (endpoint 2 exists since M02); CLI `next`, `claim`, `release`, `done`, `deviation`, `milestone-done`, `changes`. (after M03a.4)
### Tests
- [ ] **M03a.6** [SPEC-05 §10](../specs/SPEC-05-agent-tools.md#10-acceptance-checks) checks 1–4, 7–9, 11 and 12; [SPEC-01 §7](../specs/SPEC-01-architecture.md#7-acceptance-checks) check 5; [SPEC-04 §7](../specs/SPEC-04-sync.md#7-acceptance-checks) checks 7, 10, 12 and 13; [SPEC-08 §4](../specs/SPEC-08-cli-and-exports.md#4-acceptance-checks) check 2; invariant 4; an in-process MCP client smoke test of the tools above; extend `test_spec09_ac03` to `POST /api/tasks/M01.1/claim`.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (on a copy of the `tool_style` fixture, CLI against a running daemon):** two shells `sdd claim` the same task at once (one wins, one exits 4); `sdd deviation` creates the file, the index row and the spec note; `sdd done` ticks the box; `sdd milestone-done` moves the file to `done/` and rewrites the link to it; `sdd changes --since …` lists all of it.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
