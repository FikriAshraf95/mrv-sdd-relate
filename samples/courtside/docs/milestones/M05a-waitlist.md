# M05a — Waitlist

> **Depends on:** [M04](done/M04-payments.md)
> **Read first:** [SPEC-05 §1–2](../specs/SPEC-05-waitlist-and-reminders.md#1-joining-the-waitlist) · [SPEC-05 §4](../specs/SPEC-05-waitlist-and-reminders.md#4-acceptance-checks) · [SPEC-02 `waitlist_entries`](../specs/SPEC-02-database-schema.md#waitlist_entries)
> **Model:** Opusplan. Promotion touches the booking rules.

## Goal
Members can queue for a taken slot, and a cancellation offers the slot to the oldest entry.

## Tasks
### Backend
- [x] **M05a.1** Join the waitlist for a taken slot ([SPEC-05 §1](../specs/SPEC-05-waitlist-and-reminders.md#1-joining-the-waitlist), [SPEC-02 `waitlist_entries`](../specs/SPEC-02-database-schema.md#waitlist_entries))
- [x] **M05a.2** Promote the oldest entry when a booking is cancelled ([SPEC-05 §2](../specs/SPEC-05-waitlist-and-reminders.md#2-promotion), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings)) (after M05a.1)
- [ ] **M05a.3** Tell the promoted member by message ([SPEC-05 §2](../specs/SPEC-05-waitlist-and-reminders.md#2-promotion)) (after M05a.2)
### Tests
- [ ] **M05a.4** [SPEC-05 §4](../specs/SPEC-05-waitlist-and-reminders.md#4-acceptance-checks) checks 1–2 (after M05a.2)

## Acceptance criteria
1. A member cannot join the waitlist for a free slot.
2. Cancelling a booking promotes the oldest waiting entry.

**Status:**
