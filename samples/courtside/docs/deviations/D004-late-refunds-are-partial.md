# D004 — Late refunds are partial

- **Date / milestone:** 2026-11-04 · M04 · M04.3
- **Spec:** [SPEC-04 §3](../specs/SPEC-04-payments.md#3-refunds)
- **Affects:** `refunds`, `src/payments/refunds.py`
- **Status:** Open

## Spec says
Cancelling a paid booking refunds the full amount.

## Implementation does
A cancellation inside 24 hours of the start refunds half the amount paid. A cancellation more than 24 hours ahead still refunds all of it.

## Why
The desk could not resell last-minute slots, and the hall asked for a late-cancellation fee.

## Consequences
The `reason` of a refund row says `late` for the half refund. SPEC-04 §3 needs a rewrite.
