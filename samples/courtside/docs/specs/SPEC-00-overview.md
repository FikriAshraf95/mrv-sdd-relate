# SPEC-00 — Overview

> **Spec ID:** SPEC-00 · **Consumed by:** every other spec

## 1. Purpose
Courtside runs the bookings of a community sports hall with four badminton courts and two tennis courts. Members reserve a court for one slot, pay for it, and join a waitlist when the slot they want is taken. Front-desk staff can override most rules when someone turns up with a problem.

## 2. Glossary
- **Member:** a person with an account. Staff are members with a role.
- **Court:** one playing surface (badminton or tennis, indoor or outdoor).
- **Slot:** one hour on one court, starting on the hour.
- **Booking:** a member's claim on one slot, from held, to confirmed, to cancelled.
- **Waitlist:** members waiting for a slot that is taken. The oldest entry is offered the slot first.
- **Desk:** the front-desk staff role, with the override powers of [SPEC-03 §5](SPEC-03-booking-rules.md#5-desk-overrides).

## 3. Users
Members book from their phones. Desk staff work from one shared tablet. The hall manager (admin) reads the reports of [SPEC-06](SPEC-06-reports-and-audit.md).

## 4. Spec map
| Spec | Covers |
|---|---|
| [SPEC-01](SPEC-01-members-and-access.md) | Sign-up, roles, sessions |
| [SPEC-02](SPEC-02-database-schema.md) | Every table |
| [SPEC-03](SPEC-03-booking-rules.md) | Slots, booking, overlap, cancellation, desk overrides |
| [SPEC-04](SPEC-04-payments.md) | Prices, payment, refunds |
| [SPEC-05](SPEC-05-waitlist-and-reminders.md) | Waitlist, promotion, reminders |
| [SPEC-06](SPEC-06-reports-and-audit.md) | Daily report, audit trail |

## 5. Non-goals
No coaching schedules, no equipment hire, no membership fees. Courtside only sells court time.

## 6. Conventions
These apply everywhere. A rule here beats any other spec, and a conflict is a logged deviation ([DEVIATIONS](../DEVIATIONS.md)).

1. All times are stored in UTC and shown in the hall's time zone.
2. Money is an integer number of cents. There are no floats in price code.
3. Every table has a `uuid` primary key named `id`. Foreign keys are `uuid not null` unless the column says otherwise.
4. A rule that needs the clock takes it as a parameter, so tests can fix it.
5. Every numbered acceptance check becomes a test named after it: `test_spec03_ac2_overlap_is_refused`.
