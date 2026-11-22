# SPEC-05 — Waitlist and reminders

> **Spec ID:** SPEC-05 · **Consumed by:** SPEC-06
> **Feature:** Waitlist · **Domain:** Courts · **Implements:** `src/waitlist/**` · **Tables:** waitlist_entries, bookings
> **Feature:** Reminders · **Domain:** Notifications · **Implements:** `src/reminders/**` · **Tables:** reminders, bookings

## 1. Joining the waitlist
A member can join the waitlist for a court and start time only when that slot is taken. There is one row in `waitlist_entries` per member and slot ([SPEC-02 `waitlist_entries`](SPEC-02-database-schema.md#waitlist_entries)). Joining a free slot is refused: the member should just book it.

## 2. Promotion
When a booking is cancelled, the oldest waiting entry for that court and start time is promoted: a new `bookings` row is created for that member and the entry stores its id in `promoted_booking_id`. The member is told by message.

> **DEVIATION:** see [D006](../deviations/D006-a-promoted-waitlist-entry-holds-the-slot-for-15-minutes.md) — the promoted booking is `held` for 15 minutes until the member confirms.

## 3. Reminders
Every confirmed booking gets a reminder 24 hours before it starts: one row in `reminders` with `send_at` ([SPEC-02 `reminders`](SPEC-02-database-schema.md#reminders)). The row is removed when the booking is cancelled, and nothing is sent for a cancelled booking.

## 4. Acceptance checks
1. A member cannot join the waitlist for a slot that is free.
2. Cancelling a booking promotes the oldest waiting entry for that slot.
3. A reminder is created for a confirmed booking and dropped when it is cancelled.
