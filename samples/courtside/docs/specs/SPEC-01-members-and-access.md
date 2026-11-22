# SPEC-01 — Members and access

> **Spec ID:** SPEC-01 · **Consumed by:** SPEC-02, SPEC-03, SPEC-06
> **Feature:** Members · **Domain:** Accounts · **Implements:** `src/members/**` · **Tables:** members

## 1. Sign-up
A person signs up with an email address and a name. The email must be unique; a second sign-up with the same address is refused with a clear message. New accounts have the role `member`. The `members` table is defined in [SPEC-02 `members`](SPEC-02-database-schema.md#members).

## 2. Roles
| Role | Can |
|---|---|
| member | Book, cancel and pay for their own bookings; see only their own account |
| desk | Everything a member can, for any member, plus the overrides of [SPEC-03 §5](SPEC-03-booking-rules.md#5-desk-overrides) |
| admin | Everything, plus the reports of [SPEC-06](SPEC-06-reports-and-audit.md) |

Roles are set by an admin. There is no self-service upgrade.

## 3. Sessions
A session is a signed token. It expires after eight hours. The token carries the member id and the role, and nothing else.

## 4. Acceptance checks
1. A new member can sign up; signing up again with the same email is refused.
2. A member can read only their own account; a desk user can read any account.
3. A session older than eight hours is rejected.
