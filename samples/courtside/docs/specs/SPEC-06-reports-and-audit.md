# SPEC-06 — Reports and audit

> **Spec ID:** SPEC-06 · **Consumed by:** nothing
> **Feature:** Reports · **Domain:** Admin · **Implements:** `src/reports/**` · **Tables:** bookings, payments

## 1. Daily usage report
The admin sees, for one day, the confirmed `bookings` per court and the money taken in `payments`. Utilisation is booked hours divided by opening hours. The report reads the tables directly and never writes ([SPEC-02 `bookings`](SPEC-02-database-schema.md#bookings)).

## 2. Audit trail
Every cancellation and every desk override is recorded with who did it, when, and which booking it touched. The trail is append-only and is read by admins only ([SPEC-01 §2](SPEC-01-members-and-access.md#2-roles)).

## 3. Acceptance checks
1. The daily report counts only confirmed bookings, per court.
2. Every cancellation and desk override appears in the audit trail.
