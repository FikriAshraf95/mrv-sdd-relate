# SPEC-04 — Payments

> **Spec ID:** SPEC-04 · **Consumed by:** SPEC-06
> **Feature:** Payments · **Domain:** Billing · **Implements:** `src/payments/**` · **Tables:** payments, refunds, bookings

## 1. Prices
The price of a booking is the hourly rate of the court's surface times the hours booked, in cents. Rates live in `src/payments/prices.py`; members see the price before they confirm. A booking has exactly one price, fixed when the booking is made, so a later rate change never alters it ([SPEC-02 `bookings`](SPEC-02-database-schema.md#bookings)).

## 2. Taking payment
A confirmed booking is paid online when it is made. The result is one row in `payments` with the amount and `captured_at` ([SPEC-02 `payments`](SPEC-02-database-schema.md#payments)). Payment is recorded once per booking; a second attempt returns the first row.

> **DEVIATION:** see [D005](../deviations/D005-payment-is-taken-at-check-in.md) — the desk takes payment at check-in, not online.

## 3. Refunds
Cancelling a paid booking refunds the full amount when the cancellation is more than 24 hours ahead. A refund row records the amount and a reason ([SPEC-02 `refunds`](SPEC-02-database-schema.md#refunds)). A refund never exceeds the amount paid.

> **DEVIATION:** see [D004](../deviations/D004-late-refunds-are-partial.md) — a cancellation inside 24 hours is refunded half.

## 4. Acceptance checks
1. The price of a booking comes from the court's surface rate.
2. Paying a booking twice records one payment.
3. A refund never exceeds the amount paid.
