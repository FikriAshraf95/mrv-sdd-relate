# D012 — Order totals round per line

- **Date / milestone:** 2026-10-20 · M16
- **Spec:** SPEC-06 §7 step 1
- **Status:** Resolved → spec updated

## Spec says
Totals are computed once for the whole order.

## Implementation does
Each line is rounded to cents, then summed.

## Why
Invoices must add up line by line.

## Consequences
Totals can differ by a cent from the old export.
