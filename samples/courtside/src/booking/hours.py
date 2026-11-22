"""Opening hours per court and weekday (SPEC-02 `opening_hours`, D001)."""

from datetime import time

OpeningHours = dict[tuple[str, int], tuple[time, time]]  # (court_id, weekday) -> (opens, closes)


def hours_for(rows: OpeningHours, court_id: str, weekday: int) -> tuple[time, time] | None:
    """The hours of one court on one weekday, or None when the court is closed."""
    return rows.get((court_id, weekday))
