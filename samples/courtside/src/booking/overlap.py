"""The overlap rule (SPEC-03 §3): two bookings of one court never overlap."""

from booking.model import Booking


def overlaps(a: Booking, b: Booking) -> bool:
    """Intervals [starts_at, ends_at) of the same court that share any time."""
    return a.court_id == b.court_id and a.starts_at < b.ends_at and b.starts_at < a.ends_at


def first_conflict(new: Booking, existing: list[Booking]) -> Booking | None:
    """The active booking that blocks ``new``, if any. Cancelled bookings do not count."""
    return next((b for b in existing if b.active and overlaps(new, b)), None)
