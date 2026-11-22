# CLAUDE.md

## What this repo is

**SDD Graph** (working name; package `relate-sdd`, CLI `sdd`): a Python daemon that parses a spec-driven repo (specs, milestones, deviations, CLAUDE.md, plans, code, git) into one **Relate** graph, and serves it to AI agents over MCP and to people through a dashboard. Agents claim tasks atomically and pull a minimal context packet instead of re-reading Markdown. Markdown stays the source of truth. Built for the **Relate by Neo4j Hackathon**: submit by **Thu 11 Dec 2026, 23:59 MYT** (hard deadline Fri 12 Dec, 10:00 MYT). Background and verified Relate facts: [HANDOFF.md](HANDOFF.md); locked idea: [docs/IDEA.md](docs/IDEA.md).

**The repo is spec-driven, and it is built with the workflow it improves.**
- Specs in `docs/specs/` are the source of truth. Read **[SPEC-00 §6](docs/specs/SPEC-00-overview.md#6-global-conventions) Global conventions** before non-trivial work.
- **SPEC-02 owns every label and relationship type. SPEC-05 indexes every MCP tool, SPEC-07 every endpoint, SPEC-08 every CLI command.** Change them in the same change as the code.
- Milestones in `docs/milestones/` are worked **in number order, one at a time**. Each one's *Read first* line lists the spec sections to load.
- **Every task line has a stable ID:** `- [ ] **M02.3** text (after M02.1)`. New tasks take the next free number; numbers are never reused. Commits name the task: `feat: walker [M04.1]`.
- **Deviations are a mandatory log** ([docs/DEVIATIONS.md](docs/DEVIATIONS.md)): check the highest D-number, add `docs/deviations/D<nnn>-….md` + index row + spec note **in the same change**. An unlogged deviation is a bug.

## How to read specs (token rule)

This repo is built with its own tool (from M03b). **Before a session**, start the daemon in the dev container (it serves `/mcp` on host loopback :8770; `.mcp.json` has the `sdd` server):

```bash
docker compose -f docker-compose.dev.yml exec -d dev uv run sdd daemon --host 0.0.0.0
```

Then follow [.claude/skills/sdd/SKILL.md](.claude/skills/sdd/SKILL.md):
- Start every session with `what_changed(since="last_session", agent="opus-orch")` (subagents use their own fixed names, e.g. `sonnet-1`).
- Work a task with `claim_task` → `get_context(<task>)` → `read_section("SPEC-04 §5.2")` for anything in its `outline` → build and test → `log_deviation` for every departure → `complete_task`. Close a milestone with `complete_milestone`.
- `query(cypher)` for read-only questions about the graph.

**Fallback only if the daemon is down:** run `grep -n '^## ' <spec>` to find a section's line range, then Read with offset/limit. Never read a whole spec unless the milestone says "(whole file)".

**Write task lines with links to the sections they implement** (`[SPEC-05 §4](…)`): a task that links nothing gets the whole *Read first* set as its context packet, which is no smaller than reading the files.

## Status

<!-- sdd:status -->
Specs v1 written (2026-11-21). **Done:** [M00a](docs/milestones/done/M00a-docker-and-skeleton.md) Docker and package skeleton (2026-11-21; O9 closed); [M00b](docs/milestones/done/M00b-relate-access-layer.md) Relate access layer (2026-11-21; O5, O6, O10–O12 closed; D001). [M01a](docs/milestones/done/M01a-markdown-parsers.md) Markdown parsers (2026-11-21; deviations: none). [M01b](docs/milestones/done/M01b-graph-sync.md) Graph upsert and full sync (2026-11-22; D002, D003). M00b human review done (2026-11-22). [M02](docs/milestones/done/M02-sync-daemon.md) Sync daemon (2026-11-22; deviations: none). [M03a](docs/milestones/done/M03a-coordination-tools.md) Coordination tools (2026-11-21 UTC; D004, D005; closed with its own `sdd milestone-done`). [M03b](docs/milestones/done/M03b-context-and-integration.md) Context, query guard, integration (2026-11-22; O4 closed; deviations: none; walkthrough driven by Claude Code with two Sonnet subagents, closed with `complete_milestone`). [M04a](docs/milestones/done/M04a-code-and-git.md) Code and git layer (2026-11-22; O8 closed; deviations: none; planned on Opus, built by one Sonnet subagent, reviewed and walked through on Opus). [M04b](docs/milestones/done/M04b-schema-features-impact.md) Schema, features, impact (2026-11-22; D004 resolved; deviations: none; same Opus plan → Sonnet build → Opus review flow). [M05a](docs/milestones/done/M05a-dashboard-core.md) Dashboard core (2026-11-22; deviations: none; built on Sonnet, reviewed on Opus; dashboard auth under `SDD_TOKEN` specified in SPEC-09 §2 and planned as M05b.5). [M05b](docs/milestones/done/M05b-dashboard-impact-explain.md) Dashboard Impact and Explain (2026-11-22; deviations: none; built and walked through on Sonnet, including token login and presets-only mode; `/api/health` gained `public_query`, SPEC-07 row 1 updated). [M06a](docs/milestones/done/M06a-sample-and-exports.md) Invented sample and exports (2026-11-22; O3 closed: `.rl`/JSON copies only via the `relate` CLI; deviations: none; sample `samples/courtside/`, centrepiece table `bookings`, rebuilt by `scripts/make_sample.py`; planned on Opus, built on Sonnet, reviewed on Opus). [M06b](docs/milestones/done/M06b-public-replay-deploy.md) Public mode, replay, deploy (2026-11-22; D006: guarded queries run in a killable worker process with a memory cap; judges' `docker compose up` on :8770; live at https://sddrelate.myradiantvision.com through the Cloudflare tunnel, `deploy/` stack on the home machine; planned on Opus, built on Sonnet, reviewed on Opus). [M07](docs/milestones/done/M07-benchmark.md) Benchmark (2026-11-22; D007: the sample's task packet is 61.2% smaller than the Markdown rule, under the 70% target, and 71.9% on this repo's own milestones; restart 88.1%; collisions 139 naive lost ticks vs 0 for the graph; `sdd bench`, results in `bench/results/`; M07.6 live run not done; built on Sonnet). [M08](docs/milestones/done/M08-static-demo.md) Static demo (2026-11-22; O2 closed: `@relate/relate-wasm` 1.2.0 loads the sample's `graph.cypher` in ~0.3 s; D008: only the Query tab runs in Relate WASM, other views use answers `sdd site` precomputes; D009: without WASM the Query examples still run; live at https://fikriashraf95.github.io/mrv-sdd-relate/ via `.github/workflows/pages.yml`; planned on Opus, built on Sonnet, reviewed on Opus). **Next: [M99 Release and submission](docs/milestones/M99-release-and-submission.md)** (Opus). Spec audit applied and milestones split into sub-milestones (2026-11-21). Decisions in [docs/decisions/](docs/decisions/README.md): DEC-001 to DEC-004 all accepted. O1 closed: private-repo-app can't be published, so the sample is invented.
<!-- /sdd:status -->

When a milestone is done: tick its boxes, set **Status** to `DONE (date)` + how acceptance was verified + deviations (`D003, D004` or "Deviations: none"), then move it and its plan file to `docs/milestones/done/` and update the status block. From M03b on, `complete_milestone` does this (it exists from M03a).

## Model per milestone

Start each milestone in a fresh session (`/clear`). *Opusplan* = `/model opusplan` (plan on Opus, build on Sonnet); write `M<nn>[a-z]-plan.md` first. If you are on a different model than the row says, say so first. On Sonnet, if the same test fails twice or a design question comes up, suggest switching to Opus. After a Sonnet milestone, a short Opus session reviews the diff for unlogged deviations and public-mode leaks.

| Milestone | Model | Why |
|---|---|---|
| M00a Docker and package skeleton | Opus | Docker and package contracts |
| M00b Relate access layer | Opus | Store layer and write queue, shaped by experiments. Human review after |
| M01a Markdown parsers | Opusplan | Two real formats, reference grammar |
| M01b Graph upsert and full sync | Opusplan | Two-phase transactional upserts, graph-only state |
| M02 Sync daemon | Opusplan | Process ownership, polling through the bind mount, safe write-back |
| M03a Coordination tools | Opus | Atomic claims, forced release, deviation write-back under concurrency |
| M03b Context, query guard, integration | Opus | Context packet rules, query guard, dogfooding switch-over |
| M04a Code and git layer | Opusplan | Ignore rules, git rewrites |
| M04b Schema, features, impact | Opusplan | Globs, traversals with `via` chains |
| M05a Dashboard core | Sonnet | Static UI over existing endpoints; can run in parallel with M04a/M04b |
| M05b Dashboard Impact and Explain | Sonnet | Two views over the M04b endpoints |
| M06a Invented sample and exports | Opusplan | The demo's story, snapshots (O3) |
| M06b Public mode, replay, deploy | Opusplan | Public/replay split, hosting security |
| M07 Benchmark | Sonnet | Measurement script |
| M08 Static demo *(cut first if late)* | Opusplan | Unverified WASM build, fallback first |
| M99 Release and submission | Opus | Security sweep, fold deviations, the story |

## Commands

**Everything runs in Docker.** The host's C: drive is nearly full; Docker's data is on D:. Never install Python, uv, Node or caches on the Windows host. In Git Bash, prefix commands that pass container paths with `MSYS_NO_PATHCONV=1`.

```bash
# dev container (from M00a): venv and uv cache live in named volumes
docker compose -f docker-compose.dev.yml up -d dev
docker compose -f docker-compose.dev.yml exec dev uv sync
docker compose -f docker-compose.dev.yml exec dev uv run pytest -q
docker compose -f docker-compose.dev.yml exec dev uv run pytest tests/spec05/test_claims.py::test_spec05_ac03_double_claim_one_winner
docker compose -f docker-compose.dev.yml exec dev sh -c "uv run ruff check . && uv run ruff format --check . && uv run mypy src/sdd && uv run lint-imports"
docker compose -f docker-compose.dev.yml exec dev uv run sdd daemon --host 0.0.0.0      # :8770 on host loopback (from M02)
docker compose -f docker-compose.dev.yml exec dev uv run sdd context M04a.1               # a context packet without MCP (also: sdd section, sdd query)
docker compose -f docker-compose.dev.yml exec dev uv run sdd doctor --project /refs/office-suite --store :memory:   # reference format check (from M01b)
docker compose up                                                                        # judges: sample dashboard on :8770 (from M06b)
```

## Never break

- Only `src/sdd/graph/store.py` imports `relate`. All graph writes go through its write queue; all Markdown writes through `sync/writeback.py`.
- **One process owns a store.** Never open a writable connection outside the daemon (or `sdd sync` when no daemon runs).
- Markdown is the source of truth: the graph holds nothing that a rebuild can't reproduce, except the graph-only state listed in [SPEC-02 §2](docs/specs/SPEC-02-graph-schema.md#graph-only-state-canonical-list) (claims, agents, events and tool-owned links).
- The public process opens the store `read_only`, never mounts `/mcp`, and serves no write route.
- Arbitrary Cypher only through the query guard, always rolled back.
- Tests never touch the network or the reference projects; they use `tests/fixtures/`.
- **Reference projects are read-only:** `D:\Works\ai\office-rag` and `D:\Works\ai\private-repo-app`. Copy their conventions, never modify them, and **never publish anything from private-repo-app** (O1: no): no text, file names or commit messages in fixtures, the sample, commits or Status lines.
- Never commit the live store (`/.sdd/graph/`); committed stores are `sdd snapshot` output or the sample's built store ([DEC-001](docs/decisions/DEC-001-committed-store.md)).
- Secrets (`SDD_TOKEN`, `TUNNEL_TOKEN`, `ANTHROPIC_API_KEY`) only in env or `deploy/.env`; never in files, logs or responses.
