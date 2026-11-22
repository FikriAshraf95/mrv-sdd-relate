# D006 — A promoted waitlist entry holds the slot for 15 minutes

- **Date / milestone:** 2026-11-12 · M05a · M05a.2
- **Spec:** [SPEC-05 §2](../specs/SPEC-05-waitlist-and-reminders.md#2-promotion)
- **Affects:** `bookings`, `waitlist_entries`, `src/waitlist/promote.py`
- **Status:** Open

## Spec says
Promotion creates a confirmed booking for the oldest waiting member.

## Implementation does
Promotion creates a booking with status `held`. The member has 15 minutes to confirm; after that the slot goes to the next entry.

## Why
Members who were offered a slot at night never saw it, and the slot stayed blocked.

## Consequences
`held` becomes a booking status and the overlap rule counts held bookings. A job must expire them.
