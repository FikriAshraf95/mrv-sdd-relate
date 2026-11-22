from pathlib import Path

from booking.model import Booking
from booking.overlap import first_conflict
from datetime import datetime

MIGRATIONS = Path(__file__).parent.parent / "migrations"


def test_spec02_ac1_foreign_keys_are_indexed():
    sql = "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))
    for column in ("opening_hours (court_id)", "bookings (member_id)", "payments (booking_id)"):
        assert column in sql


def test_spec02_ac2_bookings_of_one_court_never_overlap():
    a = Booking("b1", "m1", "c1", datetime(2026, 10, 1, 18), datetime(2026, 10, 1, 19))
    b = Booking("b2", "m2", "c1", datetime(2026, 10, 1, 18, 30), datetime(2026, 10, 1, 19, 30))
    assert first_conflict(b, [a]) is a


def test_spec02_ac3_member_with_bookings_cannot_be_deleted():
    sql = (MIGRATIONS / "0003_bookings.sql").read_text()
    assert "references members (id) on delete restrict" in sql
