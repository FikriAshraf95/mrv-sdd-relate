# M02 — Catalogue import

> **Depends on:** [M00](M00-foundation.md) · **Blocks:** [M03](M03-reminders.md)
> **Read first:** [SPEC-03 (whole file)](../specs/SPEC-03-lending-rules.md) · [SPEC-02 §3–4](../specs/SPEC-02-database-schema.md#3-loans) · [SPEC-06 §2, §4–6](../specs/SPEC-06-notifications.md#2-channels) · [SPEC-08 §4.6–4.7](../specs/SPEC-08-api-contract.md#46-renew-a-loan) · [SPEC-11 §2](../specs/SPEC-11-deployment.md#2-environment-variables)
> **Model:** Opusplan. Parsing CSV rows has edge cases.

## Goal
Volunteers import a CSV of books and the app creates `documents` rows.

## Tasks
### Backend
- [ ] `app/importer.py`: read CSV rows, skip empty ones ([SPEC-03 §2](../specs/SPEC-03-lending-rules.md#2-catalogue-import))
  and report duplicate titles.
- [ ] Renew endpoint (SPEC-08 §4.6) with the `loans` table.
### Frontend
- [ ] Import page with a progress bar.
### Tests
- [ ] SPEC-03 §10 checks 3–9, 12 (loan rules, one test each)

## Acceptance criteria
1. A 500-row CSV imports in under a second.
2. Duplicate titles are reported, not dropped.

**Status:**
