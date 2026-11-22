"""Promoting the oldest entry when a booking is cancelled (SPEC-05 §2, held 15 minutes, D006)."""

from datetime import datetime, timedelta

from waitlist.join import Entry

HOLD = timedelta(minutes=15)


def oldest_waiting(entries: list[Entry], court_id: str, start: datetime) -> Entry | None:
    """The first entry for this court and start time that has not been promoted yet."""
    waiting = [e for e in entries if e.court_id == court_id and e.wanted_start == start]
    return next((e for e in waiting if e.promoted_booking_id is None), None)
