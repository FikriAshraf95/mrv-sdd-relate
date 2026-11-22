# M03a — Booking core

> **Depends on:** [M02](M02-courts-and-schema.md)
> **Read first:** [SPEC-03 §1–3](../../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours) · [SPEC-03 §6](../../specs/SPEC-03-booking-rules.md#6-acceptance-checks) · [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)
> **Model:** Opusplan. The overlap rule needs a careful plan. Plan: [M03a-plan](M03a-plan.md).

## Goal
A member can book a free slot, and two bookings of one court can never overlap.

## Tasks
### Backend
- [x] **M03a.1** The slot grid for a day from the opening hours ([SPEC-03 §1](../../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours))
- [x] **M03a.2** Create a booking in `bookings` ([SPEC-03 §2](../../specs/SPEC-03-booking-rules.md#2-making-a-booking), [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)) (after M03a.1)
- [x] **M03a.3** The overlap rule, checked inside the insert transaction ([SPEC-03 §3](../../specs/SPEC-03-booking-rules.md#3-overlap-rule), [SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)) (after M03a.2)
### Tests
- [x] **M03a.4** [SPEC-03 §6](../../specs/SPEC-03-booking-rules.md#6-acceptance-checks) checks 1–3 (after M03a.3)

## Acceptance criteria
1. A free slot can be booked; the same slot cannot be booked twice.
2. A member cannot hold more than three future bookings.

**Status: DONE (2026-10-14).** Verified with the test suite and a two-session race on one slot. A booking stores its end time: [D002](../../deviations/D002-bookings-store-an-end-time-not-a-duration.md).
