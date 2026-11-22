# M05b — Reminders

> **Depends on:** [M05a](M05a-waitlist.md)
> **Read first:** [SPEC-05 §3–4](../specs/SPEC-05-waitlist-and-reminders.md#3-reminders) · [SPEC-02 `reminders`](../specs/SPEC-02-database-schema.md#reminders)
> **Model:** Sonnet. Small and mechanical.

## Goal
Every confirmed booking gets a reminder a day ahead, and cancelled bookings lose theirs.

## Tasks
### Backend
- [ ] **M05b.1** Schedule a reminder when a booking is confirmed ([SPEC-05 §3](../specs/SPEC-05-waitlist-and-reminders.md#3-reminders), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings))
- [ ] **M05b.2** The job that sends due reminders ([SPEC-02 `reminders`](../specs/SPEC-02-database-schema.md#reminders)) (after M05b.1)
- [ ] **M05b.3** Drop the reminder with a cancelled booking ([SPEC-05 §3](../specs/SPEC-05-waitlist-and-reminders.md#3-reminders)) (after M05b.1)
### Tests
- [ ] **M05b.4** [SPEC-05 §4](../specs/SPEC-05-waitlist-and-reminders.md#4-acceptance-checks) check 3 (after M05b.3)

## Acceptance criteria
1. A confirmed booking has one reminder, a day ahead.
2. A cancelled booking has none.

**Status:**
