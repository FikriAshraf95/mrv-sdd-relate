# D005 — Payment is taken at check-in

- **Date / milestone:** 2026-11-02 · M04 · M04.2
- **Spec:** [SPEC-04 §2](../specs/SPEC-04-payments.md#2-taking-payment)
- **Affects:** `payments`, `bookings`
- **Status:** Open

## Spec says
A confirmed booking is paid online when it is made.

## Implementation does
The desk takes payment when the member arrives. A booking is `confirmed` before its `payments` row exists, and the row is created with `captured_at` at check-in.

## Why
Most members pay in cash, and the online provider was not ready for the launch.

## Consequences
Reports cannot assume a confirmed booking has a payment. SPEC-04 §2 needs a rewrite.
