from datetime import datetime

from payments.capture import capture
from payments.prices import price_cents
from payments.refunds import refund_cents

NOW = datetime(2026, 11, 3, 12)


def test_spec04_ac1_price_comes_from_the_surface_rate():
    assert price_cents("clay", 2) == 4400


def test_spec04_ac2_paying_twice_records_one_payment():
    payments = {}
    first = capture(payments, "b1", 1800, NOW)
    assert capture(payments, "b1", 1800, NOW) is first
    assert len(payments) == 1


def test_spec04_ac3_refund_never_exceeds_the_amount_paid():
    amount, _ = refund_cents(1800, datetime(2026, 11, 10, 12), NOW)
    assert amount <= 1800
    late, reason = refund_cents(1800, datetime(2026, 11, 3, 18), NOW)
    assert (late, reason) == (900, "late")
