# M03b — Context packet, query guard and Claude Code integration

> **Depends on:** [M03a](M03a-coordination-tools.md) · **Blocks:** [M04a](M04a-code-and-git.md), [M05a](M05a-dashboard-core.md)
> **Read first:** [SPEC-05 §4, §9–10](../../specs/SPEC-05-agent-tools.md#4-get_context) · [SPEC-03 §2.2](../../specs/SPEC-03-markdown-parsing.md#22-spec-reference-grammar) · [SPEC-09 §3](../../specs/SPEC-09-security.md#3-query-guard) · [SPEC-07 §2](../../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index) · [SPEC-08 §2](../../specs/SPEC-08-cli-and-exports.md#2-commands)
> **Model:** Opus. The context packet's selection and truncation rules, and the query guard.
> **Split from:** M03 (2026-11-21)

## Goal
Agents pull a minimal context packet instead of reading files, fetch any section by reference, and run read-only Cypher safely. Claude Code on the Windows host connects to the daemon in the dev container. From the end of this milestone, this repo is built with its own tool.

## Tasks
### Services
- [x] **M03b.1** `service/context.py`: `get_context` (both details, sections with descendants, truncation order) and `read_section` ([SPEC-05 §4](../../specs/SPEC-05-agent-tools.md#4-get_context)).
- [x] **M03b.2** `service/query_guard.py`: tokenizer, always-rollback on the snapshot connection, row cap, timeout, one query at a time, variable-length bound; resolve open item O4 (timeouts) ([SPEC-09 §3](../../specs/SPEC-09-security.md#3-query-guard)).
### Surfaces
- [x] **M03b.3** MCP tools 5, 6 and 14; HTTP endpoints 7, 8 and 14; CLI `context`, `section`, `query`. (after M03b.1, M03b.2)
- [x] **M03b.4** `sdd init`: config, merged `.mcp.json`, `.claude/skills/sdd/SKILL.md`, the CLAUDE.md snippet ([SPEC-05 §9](../../specs/SPEC-05-agent-tools.md#9-claude-code-integration)).
### Dogfooding
- [x] **M03b.5** Run `sdd init` on this repo; connect Claude Code (host) to `http://localhost:8770/mcp`; update CLAUDE.md so later milestones use `what_changed`, `get_context` and `read_section` instead of the grep rule. (after M03b.3, M03b.4)
### Tests
- [x] **M03b.6** [SPEC-05 §10](../../specs/SPEC-05-agent-tools.md#10-acceptance-checks) checks 5, 6 and 10; [SPEC-09 §6](../../specs/SPEC-09-security.md#6-acceptance-checks) checks 4–6 and 9; [SPEC-08 §4](../../specs/SPEC-08-cli-and-exports.md#4-acceptance-checks) check 1; invariants 6 (MCP and CLI parts) and 7.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (on a copy of the `tool_style` fixture):** an Opus session calls `status` and `next_tasks`, launches two Sonnet subagents that claim different tasks, each calls `get_context`, one logs a deviation (file + index row + spec note appear), both complete; the boxes are ticked, `what_changed` lists everything, and no Markdown edit was lost. Record the packet sizes against the files the token rule would have read.
3. **Deviations recorded**, or *"Deviations: none"*.

## Walkthrough record
- **Scripted run (2026-11-22)**, on a copy of `tool_style` with one extra independent task (M01.5) and its own daemon, over real streamable-HTTP MCP: `opus-orch` called `what_changed`, `status`, `next_tasks` (M01.1, M01.5, no overlaps); two concurrent clients `sonnet-1` and `sonnet-2` each called `claim_task` and `get_context` (packets 1020 and 842 chars; the files the grep rule reads for them are about 1400 chars); `sonnet-2` logged D002 (file, index row and SPEC-01 note appeared); both called `complete_task`. Both boxes were ticked, `what_changed` listed the changed section, D002, both claims and both completions, and a hand edit made to the milestone file while the daemon ran survived.
- **Packet sizes on this repo** (default `max_chars`, nothing truncated): tasks whose line links governing sections get 7.2k–15k chars; the grep rule reads the milestone file plus its *Read first* sections plus SPEC-00 §6, about 20.5k chars (M03b 17.2k + 3.2k, M04a 17.3k + 3.2k, M04b 18.3k + 3.2k). Tasks that link nothing (M03b.3, M03b.5, M04a.6, M04b.5, M04b.8, M05a.2–5) fall back to the whole *Read first* set (up to 23k), which saves nothing, so task lines should link the sections they implement.
- **Claude Code run (2026-11-22)**, after M03b.5 connected Claude Code on the host to the `sdd` server. The repo's daemon on :8770 was stopped and restarted on `/tmp/walk` in the dev container (a copy of `tool_style` with one extra independent task, M01.5), then switched back. `opus-orch` (Opus) called `what_changed`, `status` and `next_tasks`, which returned M01.1 and M01.5 with no overlaps. It then launched two Sonnet subagents in parallel, `sonnet-1` and `sonnet-2`, that used only the sdd MCP tools. Each called `what_changed`, `claim_task` and `get_context`. `sonnet-1` also called `read_section("SPEC-01 §2")` and logged D002, amending SPEC-01 §2 with Affects `src/kettle/brew.py`; the file, the index row (at the top, per SPEC-04 §5.1) and the SPEC-01 §2 note all appeared. `sonnet-2` ran a guarded `query`. Both called `complete_task`, and M01.1's completion unblocked M01.2. Both boxes were ticked. `what_changed` for `opus-orch` listed SPEC-01#2, D002, both claims and both completions with notes. A hand edit to the milestone's Goal, made while the agents ran, survived the write-backs. Packets were 1027 chars (M01.1) and 854 chars (M01.5). The grep rule would read about 900 chars for either task (the 785-char milestone file plus SPEC-01 §1–2; the fixture has no SPEC-00 §6), so this toy fixture shows no saving. The saving shows on this repo's real specs, measured above.

**Status:** DONE (2026-11-21). Tests (501) and all gates green. Walkthrough driven by Claude Code over the sdd MCP server on a tool_style copy: an Opus orchestrator and two parallel Sonnet subagents claimed M01.1 and M01.5, pulled packets (1027 and 854 chars), one logged D002 (file, index row and spec note), both completed. Boxes ticked, what_changed listed everything, and a concurrent hand edit survived (see Walkthrough record). Deviations: none.
