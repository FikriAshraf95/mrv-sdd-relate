"""Desk overrides: book, cancel and move inside the cut-off (SPEC-03 §5)."""

from dataclasses import replace
from datetime import datetime

from booking.model import Booking
from booking.overlap import first_conflict


def move(booking: Booking, new_start: datetime, others: list[Booking]) -> Booking:
    """Move a booking to another slot. The overlap rule still applies."""
    length = booking.ends_at - booking.starts_at
    moved = replace(booking, starts_at=new_start, ends_at=new_start + length)
    if first_conflict(moved, [b for b in others if b.id != booking.id]):
        raise ValueError("That slot is taken.")
    return moved
