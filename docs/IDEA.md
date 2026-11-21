# IDEA — SDD Graph (working name)

> **Status:** locked (2026-11-21) · Built for the [Relate by Neo4j Hackathon](https://relate.devpost.com/) (deadline **Dec 11, 2026, 6:00 pm PST** = Dec 12, 10:00 MYT)
> Background and verified Relate facts: [HANDOFF.md](../HANDOFF.md)

## Problem

Spec-driven development (SDD) keeps a project's intent in Markdown: specs, milestones with checklists, a deviation log, CLAUDE.md files and plan files, all cross-linked. AI agents build from them. It works, but:

1. **Token bloat.** Every session re-reads whole files to find the few sections a task needs, or what changed since last time.
2. **Parallel write collisions.** Several subagents ticking boxes in the same milestone file or CLAUDE.md overwrite each other.
3. **Lost lineage.** Nobody can quickly see which deviation changed a spec section that a later task depends on, or which spec, task and deviation explain why a file exists.

## Idea

Keep Markdown as the human source of truth. A daemon parses it, along with the codebase (files, git history, tables declared in specs), into one **Relate** graph. Agents query that graph through MCP tools: they get the exact context packet for a task, and claim and complete tasks atomically. Humans see the same graph in a dashboard.

**Pitch:** Spec Kit-style specs plus Beads-style task tracking, joined in one Relate graph, so agents follow how specs, deviations and code connect instead of re-reading files.

## What connects to what

Spec → Section → (Task, Milestone *Read first*, Deviation, Table, Feature) → File → Commit → Task. Full schema: [SPEC-02](specs/SPEC-02-graph-schema.md).

## Users

- **The developer** who writes specs and milestones (the human gate).
- **The orchestrator agent** (Opus) that plans and launches workers.
- **Worker agents** (Sonnet subagents) that each claim a task, pull its context, build it and report back.
- **Hackathon judges**, who must see it running in minutes.

## Must have (v1)

1. Parser for the existing SDD format (two real projects as references), with no new conventions required except stable task IDs.
2. One daemon that owns the store, syncs Markdown and code incrementally, and serves MCP over localhost HTTP.
3. Coordination tools: `next_tasks`, `claim_task`, `get_context`, `log_deviation`, `complete_task`, `what_changed`, `query`.
4. Code context: files, folders, git commits, tables and columns from spec Markdown, features and domains; `impact`, `explain`, `find_code`.
5. Write-back: completing a task ticks its box; logging a deviation writes the file, the index row and the spec note, exactly as the manual ritual does today.
6. Dashboard: graph view, live milestone board, impact and explain views, a read-only Cypher box.
7. Docker for development, for judges (`docker compose up`) and for a home-hosted live demo with sprint replay.
8. A committed persistent store, Mermaid diagrams in the README, and a token benchmark (Markdown vs graph).

## Should have

- Static zero-install demo on GitHub Pages using Relate's WASM build.
- Generated CLAUDE.md status block.

## Non-goals for this build

- Replacing Markdown or editing specs through the graph (only task status and deviations are written back).
- Function or class symbol graphs and call graphs (agents grep well).
- Parsing ORM models or migration files (tables come from the spec that owns them).
- Multi-user hosting, accounts, or any public write access.
- Vector search, a global lessons store (stretch only).
