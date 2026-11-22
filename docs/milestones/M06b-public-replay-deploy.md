# M06b — Public mode, replay and home deploy

> **Depends on:** [M06a](done/M06a-sample-and-exports.md) · **Blocks:** [M07](M07-benchmark.md), [M08](M08-static-demo.md)
> **Read first:** [SPEC-11 §2–4, §7, §9](../specs/SPEC-11-deployment-and-demo.md#2-compose) · [SPEC-09 §4–5](../specs/SPEC-09-security.md#4-public-mode) · [SPEC-07 §2–3](../specs/SPEC-07-dashboard-and-api.md#2-endpoint-index) · [SPEC-01 §1](../specs/SPEC-01-architecture.md#1-process-model) rule 4
> **Model:** Opusplan. The public/replay process split, snapshot reopening and the hosting security rules. Write `M06b-plan.md` first.
> **Split from:** M06 (2026-11-21)

## Goal
Judges get the two live ways in: `docker compose up` locally, and a home-hosted demo where simulated agents work the sample in a loop while a separate read-only process serves it to the internet. The public side can never write.

## Tasks
### Public and replay
- [x] **M06b.1** `samples/<name>/replay.toml`: start state, scripted deviations, notes and files.
- [x] **M06b.2** `public.py` / `sdd public`: read-only snapshot, reopen on `manifest.json` change, public routes only, rate limits, headers ([SPEC-09 §4](../specs/SPEC-09-security.md#4-public-mode)).
- [x] **M06b.3** `sdd demo prepare`, `sdd demo replay` (with the heartbeat file) and `sdd demo serve` ([SPEC-08 §2](../specs/SPEC-08-cli-and-exports.md#2-commands), [SPEC-11 §4](../specs/SPEC-11-deployment-and-demo.md#4-sprint-replay)). (after M06b.1)
### Docker and hosting
- [x] **M06b.4** Runtime image final; `docker-compose.yml` (judges: `sample` service running `sdd demo serve`) ([SPEC-11 §2–3](../specs/SPEC-11-deployment-and-demo.md#2-compose)). (after M06b.3)
- [x] **M06b.5** `deploy/docker-compose.yml` (project `relate-sdd`: `replay`, `public`, `cloudflared` under profile `tunnel`, fixed `COMPOSE_SUBNET`, healthchecks, limits, read-only FS with `tmpfs /tmp`), `deploy/.env.example` and `deploy/README.md`, following the shape of office-suite-v2's `deploy/` (shape only, nothing copied) ([SPEC-11 §7](../specs/SPEC-11-deployment-and-demo.md#7-home-hosting)). Deploy to the home server through the Cloudflare tunnel. (after M06b.2, M06b.3)
### Tests
- [x] **M06b.6** [SPEC-09 §6](../specs/SPEC-09-security.md#6-acceptance-checks) check 7; [SPEC-07 §5](../specs/SPEC-07-dashboard-and-api.md#5-acceptance-checks) check 1; [SPEC-11 §9](../specs/SPEC-11-deployment-and-demo.md#9-acceptance-checks) checks 1–4 and 6; [SPEC-10 §7](../specs/SPEC-10-testing-and-benchmark.md#7-acceptance-checks) check 2 (the invariant suite is complete here); invariant 5; invariant 6, endpoint part (every route is registered by now).

## Acceptance criteria
1. The tests above are green, along with the full gates.
2. **Walkthrough:** fresh clone in a temp folder → `docker compose up` → the sample dashboard at `:8770` within 60 s of the build. The public URL from a phone shows the Board moving; `/mcp` gives 404, a write gives 403, a heavy query gives `query_timeout`; after a replay reset the Board returns to its start state.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:**
