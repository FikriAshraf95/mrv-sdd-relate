# SPEC-02 — Database schema

> **Spec ID:** SPEC-02 · **Consumed by:** SPEC-03, SPEC-04, SPEC-05, SPEC-06
> **Related:** [SPEC-00 §6 conventions](SPEC-00-overview.md#6-conventions)

Every table has a `uuid` primary key `id`. Money is in cents and times are UTC ([SPEC-00 §6](SPEC-00-overview.md#6-conventions)). Foreign keys are written `→ table [rule]`.

## 1. Accounts ([SPEC-01](SPEC-01-members-and-access.md))

### members

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| email | text not null | unique |
| name | text not null | |
| role | text not null | member, desk or admin |
| created_at | timestamptz | not null |

## 2. Courts ([SPEC-03](SPEC-03-booking-rules.md))

### courts

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| name | text not null | unique, shown to members |
| surface | text not null | decides the hourly rate |
| indoor | boolean | not null |

### opening_hours

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| court_id | uuid not null | → courts [cascade] |
| weekday | int | not null, 0 is Monday |
| opens_at | time | not null |
| closes_at | time | not null |

> > **DEVIATION:** see [D001](../deviations/D001-opening-hours-are-per-court-not-per-hall.md) — one row per court and weekday, not one per hall.

## 3. Bookings ([SPEC-03](SPEC-03-booking-rules.md))

### bookings

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| member_id | uuid not null | → members [restrict] |
| court_id | uuid not null | → courts [restrict] |
| starts_at | timestamptz | not null |
| ends_at | timestamptz | not null |
| status | text not null | held, confirmed or cancelled |
| cancelled_at | timestamptz | null while the booking stands |
| created_at | timestamptz | not null |

> > **DEVIATION:** see [D002](../deviations/D002-bookings-store-an-end-time-not-a-duration.md) — `ends_at` replaced `duration_minutes`.
> > **DEVIATION:** see [D003](../deviations/D003-cancelled-bookings-are-kept-with-cancelled-at.md) — cancelled rows stay, with `cancelled_at` set.
> > **DEVIATION:** see [D005](../deviations/D005-payment-is-taken-at-check-in.md) — a booking can be `confirmed` before any payment row exists.
> > **DEVIATION:** see [D006](../deviations/D006-a-promoted-waitlist-entry-holds-the-slot-for-15-minutes.md) — `held` is a status of promoted bookings.

## 4. Payments ([SPEC-04](SPEC-04-payments.md))

### payments

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| booking_id | uuid not null | → bookings [restrict] |
| amount_cents | int | not null |
| captured_at | timestamptz | null until the money is taken |

### refunds

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| payment_id | uuid not null | → payments [restrict] |
| amount_cents | int | not null |
| reason | text | not null |

> > **DEVIATION:** see [D004](../deviations/D004-late-refunds-are-partial.md) — a late cancellation refunds half of `amount_cents`.

## 5. Waitlist and reminders ([SPEC-05](SPEC-05-waitlist-and-reminders.md))

### waitlist_entries

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| court_id | uuid not null | → courts |
| member_id | uuid not null | → members |
| wanted_start | timestamptz | not null |
| promoted_booking_id | uuid | → bookings, null until promoted |

### reminders

| Column | Type | Notes |
|---|---|---|
| id | uuid | PK |
| booking_id | uuid not null | → bookings [cascade] |
| send_at | timestamptz | not null |
| sent_at | timestamptz | null until sent |

## 6. Table → milestone map

| Table | Milestone |
|---|---|
| members | M01 |
| courts, opening_hours | M02 |
| bookings | M02, then M03a and M03b |
| payments, refunds | M04 |
| waitlist_entries | M05a |
| reminders | M05b |

## 7. Acceptance checks
1. Every foreign-key column is indexed.
2. Two bookings of one court never overlap in time, unless one of them is cancelled.
3. A member who has bookings cannot be deleted.
