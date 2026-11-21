# M00b — Relate access layer

> **Depends on:** [M00a](M00a-docker-and-skeleton.md) · **Blocks:** [M01a](M01a-markdown-parsers.md)
> **Read first:** [SPEC-01 §1, §4](../../specs/SPEC-01-architecture.md#1-process-model) · [SPEC-00 §8](../../specs/SPEC-00-overview.md#8-schedule-and-open-items) (open items O5, O6, O10–O12) · [SPEC-02 §2, §6](../../specs/SPEC-02-graph-schema.md#2-planning-layer) · [SPEC-09 §3](../../specs/SPEC-09-security.md#3-query-guard) · [SPEC-10 §2](../../specs/SPEC-10-testing-and-benchmark.md#2-test-host)
> **Model:** Opus. The store layer and write queue are the contract every later milestone writes through; the experiments decide its shape. **Human review after.**
> **Split from:** M00 (2026-11-21)

## Goal
`graph/store.py` is the only door to Relate: one connection, a writer thread with a queue, transactions with rollback and retries, serialized reads, checkpoints and read-only snapshots, shaped by small experiments on what Relate actually supports. The test host gains a real `store` fixture, and `sdd info` shows store counts.

## Tasks
- [x] **M00b.1** Experiments for open items O5 (concurrent reads on one connection, and isolation from an open write transaction), O6 (uniqueness constraints, property and full-text indexes), O10 (map properties), O11 (read-only open on a read-only mount; stale writer lock after a killed writer) and O12 (a read-only snapshot in the writer's own process). Small scripts in the dev container against a temp store; record the results in SPEC-00 §8, and note any spec text that has to change.
- [x] **M00b.2** `graph/store.py`: connection, writer thread and queue, `autocommit = False` transactions with rollback, retry on `write_conflict` / `storage locked`, `read()`, `checkpoint()`, `read_only` snapshot open, the snapshot connection for guarded queries if O12 allows, JSON encoding of map properties if O10 requires ([SPEC-01 §4](../../specs/SPEC-01-architecture.md#4-relate-access-and-concurrency)). (after M00b.1)
- [x] **M00b.3** `graph/schema.py`: indexes and constraints as far as O6 allows ([SPEC-02 §6](../../specs/SPEC-02-graph-schema.md#6-indexes-and-constraints)). (after M00b.2)
- [x] **M00b.4** `store` fixture: a real directory store in `tmp_path` ([SPEC-10 §2](../../specs/SPEC-10-testing-and-benchmark.md#2-test-host)). (after M00b.2)
- [x] **M00b.5** `sdd info`: project, store path, daemon (none yet), counts per label and relationship type, schema version ([SPEC-08 §2](../../specs/SPEC-08-cli-and-exports.md#2-commands)). (after M00b.2)
- [x] **M00b.6** [SPEC-01 §7](../../specs/SPEC-01-architecture.md#7-acceptance-checks) check 4; plus plain tests for the queue order, the retry path, a `read_only` open refusing writes, and the map-property round trip. (after M00b.4)

## Acceptance criteria
1. The tests above are green, along with the full gates, inside the dev container.
2. **Walkthrough:** `exec dev uv run sdd info --store /tmp/s` on an empty store prints zero counts and the schema version; SPEC-00 §8 shows O5, O6 and O10–O12 answered, each with what `store.py` does about it.
3. **Deviations recorded**, or *"Deviations: none"*.

**Status:** DONE (2026-11-21). Verified inside the dev container: `ruff check`, `ruff format --check`, `mypy --strict src/sdd`, `lint-imports` (13 contracts kept) and `pytest -q` (195 passed, network blocked). Walkthrough: `uv run sdd info --store /tmp/s` on a missing store prints `schema version  1 (store: not set)`, zero nodes and relationships, and creates nothing; on a freshly opened empty store it prints the same. O5, O6 and O10–O12 closed in SPEC-00 §8, each with what `store.py` does: connections are thread-affine, so one worker thread runs every job (reads too) in its own transaction; constraints, range and full-text indexes all exist; maps are stored as `<name>_json` and decoded on the way out; read-only opens write nothing but need the `.cypherlite.lock` markers; guarded queries get a fresh read-only snapshot per query on the calling thread. Spec text updated: SPEC-01 §4, SPEC-02 §2 and §6, SPEC-08 §3, SPEC-09 §3 step 2, SPEC-10 §2; `.gitignore` now ignores only `.cypherlite.writer`. The experiment scripts were throwaway (they imported `relate` outside `store.py`); their findings are in SPEC-00 §8 and covered by `tests/spec01/test_store.py`. **Human review pending.** Deviations: D001.
