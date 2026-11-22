# M01 — Skeleton and members

> **Depends on:** —
> **Read first:** [SPEC-00 §6](../../specs/SPEC-00-overview.md#6-conventions) · [SPEC-01 §1–3](../../specs/SPEC-01-members-and-access.md#1-sign-up) · [SPEC-02 `members`](../../specs/SPEC-02-database-schema.md#members)
> **Model:** Sonnet. Small and mechanical.

## Goal
A running package with config and tests, and members who can sign up, log in and carry a role.

## Tasks
### Backend
- [x] **M01.1** Package skeleton, config and the test runner ([SPEC-00 §6](../../specs/SPEC-00-overview.md#6-conventions))
- [x] **M01.2** The `members` table, sign-up and unique email ([SPEC-01 §1](../../specs/SPEC-01-members-and-access.md#1-sign-up), [SPEC-02 `members`](../../specs/SPEC-02-database-schema.md#members))
- [x] **M01.3** Roles and the session token ([SPEC-01 §2–3](../../specs/SPEC-01-members-and-access.md#2-roles)) (after M01.2)
### Tests
- [x] **M01.4** [SPEC-01 §4](../../specs/SPEC-01-members-and-access.md#4-acceptance-checks) checks 1–3 (after M01.3)

## Acceptance criteria
1. A person can sign up once per email address.
2. A session carries the member's role and expires after eight hours.

**Status: DONE (2026-09-18).** Verified with the test suite: all three SPEC-01 checks pass. Deviations: none.
