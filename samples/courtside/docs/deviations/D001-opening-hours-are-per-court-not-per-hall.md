# D001 — Opening hours are per court, not per hall

- **Date / milestone:** 2026-09-24 · M02 · M02.2
- **Spec:** [SPEC-02 `opening_hours`](../specs/SPEC-02-database-schema.md#opening_hours), [SPEC-03 §1](../specs/SPEC-03-booking-rules.md#1-slots-and-opening-hours)
- **Affects:** `opening_hours`, `src/booking/hours.py`
- **Status:** Resolved → spec updated

## Spec says
The hall has one set of opening hours per weekday, shared by every court.

## Implementation does
Each court has its own rows in `opening_hours`, one per weekday. The two outdoor tennis courts close at dusk, so a single hall-wide row could not describe them.

## Why
The groundsman closes the outdoor courts in winter while the sports hall stays open.

## Consequences
`opening_hours` gains a `court_id` column. The slot grid is built per court.
