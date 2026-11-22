# M06 — Reports and audit

> **Depends on:** [M05b](M05b-reminders.md)
> **Read first:** [SPEC-06 §1–3](../specs/SPEC-06-reports-and-audit.md#1-daily-usage-report) · [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings)
> **Model:** Sonnet. Small and mechanical.

## Goal
The hall manager sees a daily usage report and an audit trail of cancellations and overrides.

## Tasks
### Backend
- [ ] **M06.1** The daily usage report from `bookings` and `payments` ([SPEC-06 §1](../specs/SPEC-06-reports-and-audit.md#1-daily-usage-report), [SPEC-02 `bookings`](../specs/SPEC-02-database-schema.md#bookings))
- [ ] **M06.2** The append-only audit trail ([SPEC-06 §2](../specs/SPEC-06-reports-and-audit.md#2-audit-trail))
### Tests
- [ ] **M06.3** [SPEC-06 §3](../specs/SPEC-06-reports-and-audit.md#3-acceptance-checks) checks 1–2 (after M06.1, M06.2)

## Acceptance criteria
1. The report counts only confirmed bookings.
2. Every cancellation and override is in the trail.

**Status:**
