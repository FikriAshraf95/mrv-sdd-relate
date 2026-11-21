# M03b — Context packet, query guard and Claude Code integration

> **Depends on:** [M03a](M03a-coordination-tools.md) · **Blocks:** [M04a](M04a-code-and-git.md), [M05a](M05a-dashboard-core.md)
> **Read first:** [SPEC-05 §4, §9–10](../specs/SPEC-05-agent-tools.md#4-get_context) · [SPEC-03 §2.2](../specs/SPEC-03-markdown-parsing.md#22-spec-reference-grammar) · [SPEC-09 §3](../specs/SPEC-09-security.md#3-query-guard) · [SPEC-07 §2](../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index) · [SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands)
> **Model:** Opus. The context packet's selection and truncation rules, and the query guard.
> **Split from:** M03 (2026-11-21)

## Goal
Agents pull a minimal context packet instead of reading files, fetch any section by reference, and run read-only Cypher safely. Claude Code on the Windows host connects to the daemon in the dev container. From the end of this milestone, this repo is built with its own tool.

## Tasks
### Services
- [ ] **M03b.1** `service/context.py`: `get_context` (both details, sections with descendants, truncation order) and `read_section` ([SPEC-05 §4](../specs/SPEC-05-agent-tools.md#4-get_context)).
- [ ] **M03b.2** `service/query_guard.py`: tokenizer, always-rollback on the snapshot connection, row cap, timeout, one query at a time, variable-length bound; resolve open item O4 (timeouts) ([SPEC-09 §3](../specs/SPEC-09-security.md#3-query-guard)).
### Surfaces
- [ ] **M03b.3** MCP tools 5, 6 and 14; HTTP endpoints 7, 8 and 14; CLI `context`, `section`, `query`. (after M03b.1, M03b.2)
- [ ] **M03b.4** `sdd init`: config, merged `.mcp.json`, `.claude/skills/sdd/SKILL.md`, the CLAUDE.md snippet ([SPEC-05 §9](../specs/SPEC-05-agent-tools.md#9-claude-code-integration)).
### Dogfooding
- [ ] **M03b.5** Run `sdd init` on this repo; connect Claude Code (host) to `http://localhost:8770/mcp`; update CLAUDE.md so later milestones use `what_changed`, `get_context` and `read_section` instead of the grep rule. (after M03b.3, M03b.4)
### Tests
- [ ] **M03b.6** [SPEC-05 §10](../specs/SPEC-05-agent-tools.md#10-acceptance-checks) checks 5, 6 and 10; [SPEC-09 §6](../specs/SPEC-09-security.md#6-acceptance-checks) checks 4–6 and 9; [SPEC-08 §4](../specs/SPEC-08-cli-and-exports.md#4-acceptance-checks) check 1; invariants 6 (MCP and CLI parts) and 7.

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough (on a copy of the `tool_style` fixture):** an Opus session calls `status` and `next_tasks`, launches two Sonnet subagents that claim different tasks, each calls `get_context`, one logs a deviation (file + index row + spec note appear), both complete; the boxes are ticked, `what_changed` lists everything, and no Markdown edit was lost. Record the packet sizes against the files the token rule would have read.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
