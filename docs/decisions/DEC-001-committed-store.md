# DEC-001 — Commit the live store, or only snapshots

- **Date raised:** 2026-11-21 (spec audit) · **Needed by:** M00.1 (the `.gitignore`) · **Status:** Accepted (option A, with the sample's store treated as a snapshot, i.e. C in practice; 2026-11-21)
- **Specs affected:** [SPEC-08 §3](../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots), [SPEC-11 §5, §8](../specs/SPEC-11-deployment-and-demo.md#5-sample-project), [SPEC-00 §7](../specs/SPEC-00-overview.md#7-success-criteria) item 6, [M00a](../milestones/M00a-docker-and-skeleton.md) M00a.1, [M06a](../milestones/M06a-sample-and-exports.md) M06a.4

## Context

The hackathon asks for a **committed persistent store**, so judges can open the graph without running anything. SPEC-08 §3 currently says the live directory store at `.sdd/graph/` is committed (minus lock files), next to snapshot copies (`graph.rl`, `graph-json/`).

The live store is what the daemon writes to all day. Committing it causes problems:

- **The working tree is never clean.** Every sync (every saved Markdown file, with polling at 1 s) rewrites binary files in `.sdd/graph/` (WAL, shards, `manifest.json`). `git status` always shows changes, and `git add -A` sweeps them into unrelated commits.
- **Branches always conflict.** Two branches that both synced have different binary shards. Git can't merge them, so every merge or rebase stops on the store.
- **Switching branches under a running daemon swaps its files.** `git checkout` replaces the files the daemon has open, which can corrupt the store or make the graph silently wrong.
- **A commit can capture a half-written store.** Nothing ties `git commit` to a checkpoint, so a commit made mid-sync may hold an inconsistent copy.
- **The repo grows.** Each commit of changed shards adds binary data that history keeps forever.

## Options

### A. Commit only snapshots *(recommended)*
`.sdd/graph/` is gitignored. `sdd snapshot` checkpoints the store and writes a consistent copy to `.sdd/snapshots/` (a directory copy of the store, `graph.rl`, `graph-json/`). You run it on purpose (M06.8, M99, before a release), and only then does git see a change.

For: a clean tree, no merge conflicts, every committed copy is consistent, and judges still get "directory + `.rl`". It also matches how the hosted demo works (replay writes a copy in a volume, never the checkout).
Against: the committed copy can lag behind the docs until the next `sdd snapshot`. One extra step to remember (a CI check could compare snapshot counts with a fresh `sdd sync`, optional).

### B. Commit the live store (current spec)
For: no extra step; the committed store is "the real one".
Against: every problem listed above. The checkout risk alone makes this unsafe in daily use.

### C. Hybrid: snapshots for this repo, live store for samples
The sample's store (`samples/<name>/.sdd/graph/`) is written only by `scripts/make_sample.py`, and no daemon ever runs on that checkout (judges' Compose copies the sample into a volume first). So committing that directory is harmless; it already behaves like a snapshot. This repo itself uses option A.

For: the sample ships as a plain store a judge can open directly. Against: two rules to explain instead of one.

## Recommendation

**A, treating the sample's store as a snapshot too (which is C in practice).** The rule becomes: *a store directory a daemon writes to is never committed; committed stores are build outputs.*

## If accepted

- **A or C:** M00.1 `.gitignore` adds `.sdd/graph/` (replacing `.sdd/graph/.cypherlite.*`). SPEC-08 §3: drop "The live directory store at `.sdd/graph/` is committed too"; `sdd snapshot` writes `.sdd/snapshots/graph/` (checkpointed directory copy, no lock files) as well as `graph.rl` and `graph-json/`. SPEC-11 §8 and SPEC-00 §7 item 6: "committed store" means the snapshot directory plus `.rl`. M06.8: commit the snapshot outputs.
- **C additionally:** SPEC-11 §5: the sample's `.sdd/graph/` is produced by `make_sample.py` and committed as is.
- **B:** M00.1 stays as is; add a rule to SPEC-04 that the daemon refuses to start on a checkout whose store is tracked by git *and* dirty, and document "stop the daemon before switching branches" in CLAUDE.md.

## Decision
**2026-11-21, the user: accepted the recommendation.** This repo's live `.sdd/graph/` is gitignored (root only, `/.sdd/graph/`); committed stores are `sdd snapshot` output (`.sdd/snapshots/`: directory copy, `.rl`, JSON) and the sample's store, which `make_sample.py` builds and nothing else writes.

Applied in: M00.1, SPEC-00 §7 item 6, SPEC-01 §4, SPEC-08 §3, SPEC-11 §5 and §8, M06.8, CLAUDE.md *Never break*.
