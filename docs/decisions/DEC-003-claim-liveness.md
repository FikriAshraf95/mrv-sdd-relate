# DEC-003 — When a claim goes stale, and what "last session" means

- **Date raised:** 2026-11-21 (spec audit) · **Needed by:** M03 · **Status:** Accepted (D for liveness, (ii) for sessions; 2026-11-21)
- **Specs affected:** [SPEC-05 §1–3, §7](../specs/SPEC-05-agent-tools.md#3-claims), [SPEC-02 §2](../specs/SPEC-02-graph-schema.md#agent-event-graph-only) (Agent), [CLAUDE.md](../../CLAUDE.md) token rule

## Context

Two related gaps, both about how the daemon knows an agent is still around.

**1. Claims can be taken from an agent that is still working.** A claim is stale when the agent's `last_seen` is older than `SDD_CLAIM_TTL` (30 min), and anyone can then claim the task. `last_seen` only moves when a tool call passes `agent`, but the tools a worker uses while working don't take it: `get_context` and `read_section` have no `agent` parameter. A typical worker:

```
10:00 claim_task(M02.3, agent="sonnet-2")         last_seen = 10:00
10:01 get_context(M02.3)                          (no agent: last_seen stays 10:00)
10:02 read_section(...)                           (same)
10:03–10:40 edits code, runs tests through Bash   (the daemon hears nothing)
10:31 another agent: claim_task(M02.3) succeeds   (sonnet-2 looks stale)
10:41 sonnet-2: complete_task → not_claimed_by_you, after doing the work
```

Opus milestones and slow test runs easily pass 30 minutes. The cost is wasted work, or two agents building the same task.

A **heartbeat** tool doesn't fix this on its own: an LLM agent can't call a tool while it is blocked in one long Bash command, and reminding it to heartbeat costs tokens on every turn.

**2. "Last session" is undefined.** `what_changed(since="last_session")` uses `Agent.previous_seen`, "the `last_seen` before the current session", but no spec says when a session starts. It also only works if an agent uses the same name in every session (CLAUDE.md now tells it to pass `agent`).

## Options: claim liveness

### A. Longer TTL, and `agent` on every tool
Every tool accepts an optional `agent`; any call with it refreshes `last_seen`. `SDD_CLAIM_TTL` default becomes 2 h.
For: tiny change, and most work stays well inside 2 h. Against: a crashed agent's task stays blocked for up to 2 h.

### B. Heartbeat tool and a short TTL (15 min)
For: precise when it works. Against: fails exactly in the long-Bash-command case; adds protocol and tokens.

### C. No expiry; explicit release only
Claims last until completed or released. `status`, `next_tasks` and the Board show each claim's age. The orchestrator or a human frees a stuck task with `release_task(task_id, agent, force=true)` (a new parameter that skips `not_claimed_by_you` and records who forced it).
For: never takes work from a live agent, and fits the orchestrator-reviews model. Against: a crashed subagent's task waits until someone notices.

### D. A, plus forced release *(recommended)*
`agent` on every tool, a TTL of 2 h for automatic expiry, **and** `release_task(…, force=true)` so the orchestrator doesn't have to wait 2 h when it knows a subagent died.
For: safe by default, with a way out. Against: one more parameter and one more acceptance check.

## Options: what "last session" means

### (i) Gap-based
When a call arrives more than `SDD_SESSION_GAP` (30 min) after `last_seen`, copy `last_seen` into `previous_seen` first.
Against: depends on a tuned number; a short break inside one session looks like a new one.

### (ii) Since the last time this agent asked *(recommended)*
Store `Agent.last_changes_at` on every `what_changed` call. `since="last_session"` returns everything after the previous value. The first call for a new agent returns the last 24 h, with `first_session: true` in the result.
For: deterministic, no tuning, and it means exactly "what's new since I last looked". `previous_seen` can be dropped.

## Recommendation

**D for liveness, (ii) for sessions.** Together they replace two guesses with explicit rules.

## If accepted

- **D:** SPEC-05 §1 rule 2: every tool takes optional `agent`. SPEC-05 §2: add `agent?` to the read tools; `release_task(task_id, agent, reason?, force=false)`. SPEC-05 §3: TTL default 2 h; forced release emits `task_released` with `data.forced_by`. New SPEC-05 acceptance check for forced release. SPEC-04/SPEC-11: replay unaffected (it releases nothing by force).
- **(ii):** SPEC-02 Agent: replace `previous_seen` with `last_changes_at`. SPEC-05 §7: define `last_session` as above, and the 24 h first-call rule. M03.4 wording.
- **A, B or C instead:** the matching subset (B adds a `heartbeat(agent)` tool to the SPEC-05 index; C removes `SDD_CLAIM_TTL`).
- Remove the DEC-003 pointers in SPEC-05 §3 and §7.

## Decision
**2026-11-21, the user: accepted the recommendation.** Every tool takes `agent` (optional on reads) and refreshes `last_seen`; `SDD_CLAIM_TTL` defaults to 2 h; no heartbeat tool; `release_task(…, force=true)` frees another agent's claim and records `data.forced_by`. `what_changed(since="last_session")` returns everything since that agent's previous `what_changed` call (`Agent.last_changes_at` replaces `previous_seen`); the first call returns the last 24 h with `first_session: true`. Agents keep the same name across sessions.

Applied in: SPEC-02 §2 (Agent), SPEC-05 §1–3, §7, §9 and new checks 11–12, SPEC-08 §2 (`sdd release --force`), M03.1, M03.4, M03.10, CLAUDE.md token rule.
