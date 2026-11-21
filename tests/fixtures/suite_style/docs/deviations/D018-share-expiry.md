# D018 — Share links expire after seven days

- **Date / milestone:** 2026-10-28 · M17
- **Spec:** [SPEC-02 §2](../specs/SPEC-02-database-schema.md#2-files-spec-18)
- **Status:** Resolved → spec updated

## Spec says
Share links never expire.

## Implementation does
A link stops working after seven days.

## Why
Customers forwarded old links.

## Consequences
A new `expires_at` column is needed.
