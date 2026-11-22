# M99 — Release and submission

> **Depends on:** [M07](done/M07-benchmark.md) (and [M08](M08-static-demo.md) if done) · **Blocks:** —
> **Read first:** [SPEC-11 §8](../specs/SPEC-11-deployment-and-demo.md#8-submission-checklist-m99) · [SPEC-00 §7](../specs/SPEC-00-overview.md#7-success-criteria) · [SPEC-09 (whole file)](../specs/SPEC-09-security.md) · [DEVIATIONS](../DEVIATIONS.md) · [HANDOFF §1, §3, §6](../../HANDOFF.md#1-the-hackathon)
> **Model:** Opus. Security sweep, folding deviations into specs, and the story for judges.

## Goal
Submit a complete, reproducible entry before **Thu 11 Dec, 23:59 MYT** (the hard deadline is Fri 12 Dec, 10:00 MYT): a public repo whose README makes the case in one screen, a working live demo and static demo, a committed store, and a 1–2 minute video.

## Tasks
### Quality
- [ ] **M99.1** Security sweep against SPEC-09: bind rules, Origin checks, guard corpus, public routes, container hardening on the home server.
- [ ] **M99.2** Fold open deviations into the specs, or mark them as known limitations.
- [ ] **M99.3** Every success criterion in SPEC-00 §7 verified and noted in this Status line.
### README and media
- [ ] **M99.4** README from the Devpost template: pitch, demo links, a GIF of the Board, the Mermaid schema and an impact chain, the benchmark table, setup (Docker; `pip`/`uvx`), usage for humans and agents, **how Relate is used and why**, comparison with Spec Kit and Beads, limitations, future work (Relate's Markdown vault store, vector search, a global lessons store).
- [ ] **M99.5** *(bonus)* Resolve open item O7 and document browsing the store with Neo4j Browser through `relate serve --bolt`.
- [ ] **M99.6** Final stores: rebuild the sample with `scripts/make_sample.py` and run `sdd snapshot` on this repo; commit both (never the live `.sdd/graph/`).
- [ ] **M99.7** Demo video (1–2 min): problem → Board with parallel agents → `impact` on the centrepiece table → a spec edit changing a worker's `get_context` → benchmark numbers.
### Submission
- [ ] **M99.8** Repo public; topics `relate` and `relate-neo4j-hackathon`; tag `v1.0.0`.
- [ ] **M99.9** Devpost: description (use case, what connects to what), links, video. Submit.

## Acceptance criteria
1. A fresh clone on another machine reaches the sample dashboard with `docker compose up`, following only the README.
2. The live and static demo links work from a phone.
3. Submitted on Devpost before the target time, with a confirmation email.

**Status:**
