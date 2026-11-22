# M02 — Courts and schema

> **Depends on:** [M01](M01-skeleton-and-members.md)
> **Read first:** [SPEC-02 §2–3](../../specs/SPEC-02-database-schema.md#2-courts-spec-03) · [SPEC-02 §7](../../specs/SPEC-02-database-schema.md#7-acceptance-checks) · [SPEC-03 §1](../../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours)
> **Model:** Sonnet. Mostly tables.

## Goal
The courts of the hall, their opening hours, and the `bookings` table ready for the rules of M03a.

## Tasks
### Backend
- [x] **M02.1** The `courts` table and the hall's six courts as seed data ([SPEC-02 `courts`](../../specs/SPEC-02-database-schema.md#courts))
- [x] **M02.2** Opening hours per court ([SPEC-02 `opening_hours`](../../specs/SPEC-02-database-schema.md#opening_hours), [SPEC-03 §1](../../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours)) (after M02.1)
- [x] **M02.3** Migration for `bookings` with its foreign keys ([SPEC-02 `bookings`](../../specs/SPEC-02-database-schema.md#bookings)) (after M02.2)
### Tests
- [x] **M02.4** [SPEC-02 §7](../../specs/SPEC-02-database-schema.md#7-acceptance-checks) checks 1 and 3 (after M02.3)

## Acceptance criteria
1. Every foreign key is indexed.
2. A member who has bookings cannot be deleted.

**Status: DONE (2026-09-30).** Verified with the test suite. Opening hours turned out to be per court: [D001](../../deviations/D001-opening-hours-are-per-court-not-per-hall.md).
