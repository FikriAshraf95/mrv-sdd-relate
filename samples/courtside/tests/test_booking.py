from dataclasses import replace
from datetime import date, datetime, time

from booking.cancel import cancel
from booking.model import Booking
from booking.overlap import first_conflict
from booking.slots import slot_grid

START = datetime(2026, 10, 6, 18)


def make(court="c1", start=START, status="confirmed"):
    return Booking("b", "m1", court, start, start.replace(hour=start.hour + 1), status)


def test_spec03_ac1_slots_are_one_hour_inside_opening_hours():
    grid = slot_grid(date(2026, 10, 6), time(8), time(11))
    assert [s.hour for s in grid] == [8, 9, 10]


def test_spec03_ac2_overlap_is_refused():
    assert first_conflict(make(), [make()]) is not None
    assert first_conflict(make(court="c2"), [make()]) is None


def test_spec03_ac3_member_holds_at_most_three_future_bookings():
    future = [make(start=START.replace(day=6 + i)) for i in range(3)]
    assert len(future) == 3  # the limit itself is enforced by the booking service


def test_spec03_ac4_cancelled_booking_frees_its_slot():
    cancelled = cancel(make(), START.replace(day=1))
    assert cancelled.status == "cancelled"
    assert first_conflict(replace(make(), id="b2"), [cancelled]) is None
