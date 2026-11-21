# D003 — Re-link trigger widened to the whole link catalog

- **Date / milestone:** 2026-11-22 · M01b · M01b.2
- **Spec:** [SPEC-04 §2](../specs/SPEC-04-sync.md#2-incremental-sync)
- **Affects:** `src/sdd/sync/indexer.py`
- **Status:** Open

## Spec says
Step 3: re-parse all SDD Markdown only "if the set of SDD document IDs changed (a spec, milestone or deviation was added, removed or renamed)"; otherwise only changed files.

## Implementation does
Phase 2 (relationships) runs for every file when anything links resolve against changed: node IDs (including sections, acceptance checks and tasks), section anchors, title slugs, document paths and doc stems. The old catalog is rebuilt from the graph and compared with the new one by a canonical fingerprint. The initial sync always re-links everything. Phase 1 (nodes) still runs only for files whose hash changed.

## Why
A renamed section or a new task would otherwise leave links in unchanged files unresolved (or pointing nowhere) until those files were edited. The cost is one extra phase 2 per file, only in the batches where the catalog changed.

## Consequences
- Editing a heading or adding a task re-links all files (a few hundred small transactions at most).
- Unchanged-file batches still write only `Meta.last_full_sync`.
