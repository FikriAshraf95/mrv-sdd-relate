# D003 — Cancelled bookings are kept with cancelled_at

- **Date / milestone:** 2026-10-17 · M03b · M03b.1
- **Spec:** [SPEC-03 §4](../specs/SPEC-03-booking-rules.md#4-cancellation), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings)
- **Affects:** `bookings`, `src/booking/cancel.py`
- **Status:** Open

## Spec says
A cancelled booking is deleted from `bookings` and its slot is free again.

## Implementation does
The row stays. Its status becomes `cancelled` and `cancelled_at` is set. The overlap rule ignores cancelled rows, so the slot is still free.

## Why
Refunds ([SPEC-04 §3](../specs/SPEC-04-payments.md#3-refunds)) and the audit trail ([SPEC-06 §2](../specs/SPEC-06-reports-and-audit.md#2-audit-trail)) need the booking to point at.

## Consequences
Every query that counts bookings must filter on status. SPEC-03 §4 still says delete until the spec is rewritten.
