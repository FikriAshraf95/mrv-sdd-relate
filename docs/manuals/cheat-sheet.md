# SDD Graph cheat sheet

## 10 commands

| Command | Does |
|---|---|
| `sdd init` | set up `.sdd/config.toml`, `.mcp.json`, the agent skill |
| `sdd doctor` | parser warnings and unresolved links (exit 1 on errors) |
| `sdd ids --write` | add `**M02.3**` IDs to task lines without one |
| `sdd daemon` | sync + serve MCP, API and dashboard on `127.0.0.1:8770` |
| `sdd status` | milestones, tasks, claims, warnings |
| `sdd next --milestone M02` | claimable tasks, with overlaps |
| `sdd context M02.3` | a task's context packet and its size |
| `sdd impact bookings` | what a change affects, with `via` chains |
| `sdd explain src/x.py` | why a file exists |
| `sdd release M02.3 --agent me --force` | free a dead agent's claim |

More: `sdd claim/done/deviation/milestone-done`, `sdd section "SPEC-03 §2"`, `sdd changes --since last_session --agent me`, `sdd find --table bookings`, `sdd query '…'`, `sdd sync --reset`, `sdd snapshot`, `sdd export --mermaid schema`, `sdd export --claude-status`, `sdd bench context`, `sdd info`.
Global: `--project DIR` · `--store PATH|:memory:` · `--json`. Exit codes: 0 ok · 1 other · 2 usage · 3 not found · 4 conflict · 5 write conflict.

## 10 MCP tools

| Tool | When |
|---|---|
| `what_changed(since="last_session", agent)` | **every session start** |
| `status(agent)` | milestones and live claims |
| `next_tasks(milestone, agent)` | claimable tasks; check `overlaps` |
| `claim_task(task_id, agent)` | **before any work** |
| `get_context(task_id, agent)` | instead of reading spec files |
| `read_section(refs, agent)` | anything in the packet's `outline` |
| `log_deviation(task_id, agent, title, amends, spec_says, implementation_does, why, …)` | every departure from a spec |
| `complete_task(task_id, agent, notes, files_touched, commit)` | done; ticks the box |
| `release_task(task_id, agent, force=true)` | orchestrator: free a failed worker's task |
| `complete_milestone(milestone_id, agent, verification)` | all tasks done, acceptance verified |

Also: `impact(target)`, `explain(path)`, `find_code(...)`, `query(cypher)`.

## The protocol

- **Orchestrator** `opus-orch`: `what_changed` → `status` → `next_tasks` → one subagent per non-overlapping task (give it its name and task ID) → review → `complete_milestone`.
- **Worker** `sonnet-N`: `what_changed` → `claim_task` → `get_context` → `read_section` → build, test → `log_deviation` → commit `feat: … [M02.3]` → `complete_task` → report.
- Same `agent` name every session. Never tick boxes or write deviation files by hand.

## Formats

```
- [ ] **M02.3** Task text ([SPEC-04 §2](../specs/SPEC-04-sync.md#2-incremental-sync)) (after M02.1)
> **Depends on:** [M01](…) · **Read first:** SPEC-04 §1–2 · SPEC-02 `bookings` · **Model:** Opus
> **Feature:** Booking · **Domain:** Courts · **Implements:** `src/booking/**` · **Tables:** bookings
> **DEVIATION:** see [D006](../deviations/D006-….md) — summary
git commit -m "feat: overlap rule [M03a.3]"
```

References: `SPEC-03 §2` (with subsections) · `§3–4` · `§2, §5` · ``SPEC-02 `bookings` `` · `SPEC-03 (whole file)` · `SPEC-04 §4 checks 1–3`.

## Places

Dashboard `http://localhost:8770` · MCP `http://localhost:8770/mcp` · health `/api/health` · store `.sdd/graph/` (never commit) · snapshots `.sdd/snapshots/` · config `.sdd/config.toml` · claim TTL 2 h · query guard: read-only, `*..4`, 100 rows, 5 s.
