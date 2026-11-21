---
name: sdd
description: Work this spec-driven repo through the SDD Graph MCP server (server "sdd"). Use at
  the start of every session and for every milestone task, instead of reading spec and milestone
  files: claim tasks, pull context packets, log deviations, complete tasks.
---

# SDD Graph agent protocol

The `sdd` MCP server holds this repo's specs, milestones, tasks, deviations and code as one
graph. Markdown stays the source of truth; the tools read it for you and write it back safely.
Pass `agent` on every call: your own name, **the same one every session** (the main session is
`opus-orch`; subagents get theirs from the orchestrator, e.g. `sonnet-1`).

## Any session start
1. `what_changed(since="last_session", agent=<your name>)`: what moved since your last call
   (sections, deviations, tasks, milestones). Do this instead of re-reading docs.

## Orchestrator
1. `status` for the milestones and live claims, then `next_tasks` for the claimable tasks.
2. Launch one subagent per task that has no `overlaps`; tell each its agent name and task ID.
3. Review the work each one returns. If a subagent failed or died, free its task with
   `release_task(task_id, agent=<your name>, force=true)`.
4. When the milestone's acceptance criteria are verified: `complete_milestone` with how they
   were verified.

## Worker
1. `claim_task(task_id, agent)`. `already_claimed` means someone else has it: report back.
2. `get_context(task_id, agent)`: governing sections in full, deviations, checks, upstream
   notes, related code. `read_section` anything in `outline` you need. Do not read spec files.
3. Build and test.
4. `log_deviation` for **every** intentional departure from a spec (it writes the deviation
   file, the index row and the spec note in one change).
5. `complete_task(task_id, agent, notes, files_touched, commit)`, then report.

## Also
- `read_section(["SPEC-03 §4.2"])` for any section by reference (subsections included).
- `query(cypher)` for read-only Cypher (no writes or CALL, `*..4` at most, 100 rows, 5 s).
- Every result has `synced_at`; if the daemon is down, fall back to reading the Markdown.
