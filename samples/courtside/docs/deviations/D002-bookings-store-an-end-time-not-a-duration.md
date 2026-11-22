# D002 — Bookings store an end time, not a duration

- **Date / milestone:** 2026-10-02 · M03a · M03a.2
- **Spec:** [SPEC-03 §2](../specs/SPEC-03-booking-rules.md#2-making-a-booking), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings)
- **Affects:** `bookings`, `src/booking/model.py`
- **Status:** Resolved → spec updated

## Spec says
A booking has a start time and a duration in minutes.

## Implementation does
A booking has `starts_at` and `ends_at`. The overlap rule compares two intervals directly, and a duration would have to be added to every start before comparing.

## Why
Overlap is the hot path. Comparing stored end times keeps it one indexed range query.

## Consequences
The `duration_minutes` column is replaced by `ends_at`. Reports compute durations by subtraction.
