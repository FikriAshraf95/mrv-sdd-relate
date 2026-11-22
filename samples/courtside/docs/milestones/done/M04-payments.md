# M04 — Payments

> **Depends on:** [M03b](M03b-cancellations.md)
> **Read first:** [SPEC-04 §1–3](../../specs/SPEC-04-payments.md#1-prices) · [SPEC-04 §4](../../specs/SPEC-04-payments.md#4-acceptance-checks) · [SPEC-02 `payments`](../../specs/SPEC-02-database-schema.md#payments)
> **Model:** Sonnet. Small and mechanical.

## Goal
Every booking has a price, a payment row and, when cancelled, a refund.

## Tasks
### Backend
- [x] **M04.1** Prices from the court's surface rate ([SPEC-04 §1](../../specs/SPEC-04-payments.md#1-prices))
- [x] **M04.2** Take payment for a booking in `payments` ([SPEC-04 §2](../../specs/SPEC-04-payments.md#2-taking-payment), [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)) (after M04.1)
- [x] **M04.3** Refunds on cancellation in `refunds` ([SPEC-04 §3](../../specs/SPEC-04-payments.md#3-refunds), [SPEC-02 `refunds`](../../specs/SPEC-02-database-schema.md#refunds)) (after M04.2)
### Tests
- [x] **M04.4** [SPEC-04 §4](../../specs/SPEC-04-payments.md#4-acceptance-checks) checks 1–3 (after M04.3)

## Acceptance criteria
1. A booking's price never changes after it is made.
2. A refund never exceeds the amount paid.

**Status: DONE (2026-11-07).** Verified with the test suite. Two departures: [D004](../../deviations/D004-late-refunds-are-partial.md) and [D005](../../deviations/D005-payment-is-taken-at-check-in.md).
