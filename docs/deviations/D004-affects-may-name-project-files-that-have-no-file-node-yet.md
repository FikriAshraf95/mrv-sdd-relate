# D004 — Affects may name project files that have no File node yet

- **Date / milestone:** 2026-11-21 · M03a · M03a.2
- **Spec:** [SPEC-05 §5](../specs/SPEC-05-agent-tools.md#5-log_deviation)
- **Affects:** `src/sdd/sync/writeback.py`
- **Status:** Resolved (2026-11-22, M04b.3: Table and code File nodes exist, so the spec's rule holds)

## Spec says
log_deviation adds AFFECTS for affects entries that resolve to a File or Table; an entry that resolves to neither is invalid_input.

## Implementation does
An entry is accepted when it names a File or Table node, or a file that exists in the project. The entry is written into the deviation's Affects field either way; the AFFECTS relationship appears once the node exists (code File nodes from M04a, Table nodes from M04b).

## Why
Until M04a only SDD documents have File nodes, so the strict rule would reject every code path and make the Affects field unusable in M03a, M03b and M04a.

## Consequences
Table names are still rejected until M04b creates Table nodes. Once M04b lands, the rule can return to the spec's wording and this deviation is resolved.
