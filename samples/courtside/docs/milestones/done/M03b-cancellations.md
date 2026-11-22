# M03b — Cancellations

> **Depends on:** [M03a](M03a-booking-core.md)
> **Read first:** [SPEC-03 §4–5](../../specs/SPEC-03-booking-rules.md#4-cancellation) · [SPEC-03 §6](../../specs/SPEC-03-booking-rules.md#6-acceptance-checks) · [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)
> **Model:** Sonnet. Small and mechanical.

## Goal
Members can cancel, desk staff can override, and a cancelled booking frees its slot.

## Tasks
### Backend
- [x] **M03b.1** Cancel a booking and free its slot ([SPEC-03 §4](../../specs/SPEC-03-booking-rules.md#4-cancellation), [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings))
- [x] **M03b.2** Desk overrides for booking, cancelling and moving ([SPEC-03 §5](../../specs/SPEC-03-booking-rules.md#5-desk-overrides)) (after M03b.1)
### Tests
- [x] **M03b.3** [SPEC-03 §6](../../specs/SPEC-03-booking-rules.md#6-acceptance-checks) check 4 and [SPEC-02 §7](../../specs/SPEC-02-database-schema.md#7-acceptance-checks) check 2 (after M03b.2)

## Acceptance criteria
1. A cancelled booking frees its slot for the next member.
2. A desk override never skips the overlap rule.

**Status: DONE (2026-10-24).** Verified with the test suite. Cancelled bookings are kept, not deleted: [D003](../../deviations/D003-cancelled-bookings-are-kept-with-cancelled-at.md).
