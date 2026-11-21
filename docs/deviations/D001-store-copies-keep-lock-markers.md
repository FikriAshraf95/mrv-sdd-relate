# D001 — Committed store copies keep the `.cypherlite.lock` markers

- **Date / milestone:** 2026-11-21 · M00b · M00b.1
- **Spec:** [SPEC-08 §3](../specs/SPEC-08-cli-and-exports.md#3-exports-and-snapshots), [M00a](../milestones/done/M00a-docker-and-skeleton.md) M00a.1, [DEC-001](../decisions/DEC-001-committed-store.md)
- **Affects:** `.gitignore`, `sdd snapshot` (M06a), the sample's committed store (M06a)
- **Status:** Resolved → spec updated

## Spec says
`sdd snapshot` writes `graph/`, "a consistent copy of the directory store, without lock files". M00a.1 gitignored `**/.sdd/graph/.cypherlite.*`, which also strips them from the sample's committed store under `samples/`.

## Implementation does
Store copies keep both `.cypherlite.lock` files (store root and `wal/`) and drop only `.cypherlite.writer`. The `.gitignore` ignores `.cypherlite.writer` everywhere and nothing else of a committed store.

## Why
Open item O11 ([SPEC-00 §8](../specs/SPEC-00-overview.md#8-schedule-and-open-items)): a `read_only=True` open needs those two files. Without them `relate-db` 1.2.0 fails with "read-only open requires an existing database" (or "… existing WAL"), even though the data files are all there. Their content does not matter, and a read-only open never creates them, so a copy without them cannot be opened read-only on a read-only mount or by `sdd public`. `.cypherlite.writer` is not needed and is recreated by any writable open.

## Consequences
- A judge's fresh clone can open the committed sample store and snapshot read-only, which is how `sdd public` and `sdd impact` without a daemon open stores.
- `store.exists()` uses the root marker to recognise a store (`manifest.json` appears only after the first checkpoint), and a read-only open of a store without the markers fails with `invalid_input` naming them.
