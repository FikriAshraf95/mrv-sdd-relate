"""Cancelling a booking (SPEC-03 §4). The row is kept and stamped (D003)."""

from dataclasses import replace
from datetime import datetime, timedelta

from booking.model import Booking

CUTOFF = timedelta(hours=2)


def cancel(booking: Booking, now: datetime, *, desk: bool = False) -> Booking:
    """A member cancels until two hours before the start; desk staff at any time."""
    if not desk and booking.starts_at - now < CUTOFF:
        raise ValueError("Too late to cancel online; ask the desk.")
    return replace(booking, status="cancelled", cancelled_at=now)
