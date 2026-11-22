"""The slot grid of one court for one day (SPEC-03 §1)."""

from datetime import date, datetime, time, timedelta


def slot_grid(day: date, opens_at: time, closes_at: time) -> list[datetime]:
    """Start times of every one-hour slot between opening and closing."""
    start = datetime.combine(day, opens_at)
    end = datetime.combine(day, closes_at)
    slots = []
    while start + timedelta(hours=1) <= end:
        slots.append(start)
        start += timedelta(hours=1)
    return slots
