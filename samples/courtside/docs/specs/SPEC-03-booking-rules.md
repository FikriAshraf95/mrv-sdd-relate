# SPEC-03 — Booking rules

> **Spec ID:** SPEC-03 · **Consumed by:** SPEC-04, SPEC-05, SPEC-06
> **Feature:** Booking · **Domain:** Courts · **Implements:** `src/booking/**` · **Tables:** bookings, courts, opening_hours

## 1. Slots and opening hours
A slot is one hour, starting on the hour. A court can be booked only inside its opening hours, which are kept per court in [SPEC-02 `opening_hours`](SPEC-02-database-schema.md#opening_hours). The slot grid for a day is built in `src/booking/slots.py` from those rows.

> **DEVIATION:** see [D001](../deviations/D001-opening-hours-are-per-court-not-per-hall.md) — opening hours belong to a court, so the grid is built per court.

## 2. Making a booking
A member picks a court and a slot. The new row in `bookings` starts as `confirmed` when the slot is free (the columns are in [SPEC-02 `bookings`](SPEC-02-database-schema.md#bookings)). A member holds at most three future bookings. The member, the court and the start and end times are required; the price is worked out by [SPEC-04 §1](SPEC-04-payments.md#1-prices).

> **DEVIATION:** see [D002](../deviations/D002-bookings-store-an-end-time-not-a-duration.md) — a booking stores `ends_at`, not a duration.

## 3. Overlap rule
Two bookings of one court never overlap in time. The check runs in the same transaction as the insert, so two members racing for one slot cannot both win: the second gets a refusal that names the next free slot. Cancelled bookings do not count. The rule lives in `src/booking/overlap.py`.

## 4. Cancellation
A member cancels a booking until two hours before it starts. A cancelled booking is deleted from `bookings` and its slot is free again. Cancellation triggers the waitlist promotion of [SPEC-05 §2](SPEC-05-waitlist-and-reminders.md#2-promotion).

> **DEVIATION:** see [D003](../deviations/D003-cancelled-bookings-are-kept-with-cancelled-at.md) — the row is kept and stamped, not deleted.

## 5. Desk overrides
Desk staff can book inside the two-hour cut-off, cancel any booking, and move a booking to another slot. Every override is written to the audit trail of [SPEC-06 §2](SPEC-06-reports-and-audit.md#2-audit-trail). Overrides never skip the overlap rule of §3.

## 6. Acceptance checks
1. Slots are one hour long, start on the hour and fall inside the court's opening hours.
2. A booking that overlaps an existing one on the same court is refused.
3. A member cannot hold more than three future bookings.
4. A cancelled booking frees its slot.
