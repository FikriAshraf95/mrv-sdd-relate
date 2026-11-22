"""Joining the waitlist for a taken slot (SPEC-05 §1)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Entry:
    id: str
    court_id: str
    member_id: str
    wanted_start: datetime
    promoted_booking_id: str | None = None


def join(
    entries: list[Entry], court_id: str, member_id: str, start: datetime, *, slot_taken: bool
) -> Entry:
    """Only a taken slot has a waitlist; a free one should just be booked."""
    if not slot_taken:
        raise ValueError("That slot is free; book it instead.")
    entry = Entry(f"w-{len(entries) + 1}", court_id, member_id, start)
    entries.append(entry)
    return entry
