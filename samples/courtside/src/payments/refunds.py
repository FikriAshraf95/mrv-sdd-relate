"""Refunds on cancellation (SPEC-04 §3). A late cancellation refunds half (D004)."""

from datetime import datetime, timedelta

LATE = timedelta(hours=24)


def refund_cents(paid_cents: int, starts_at: datetime, now: datetime) -> tuple[int, str]:
    """The refund amount and its reason. It never exceeds what was paid."""
    if starts_at - now < LATE:
        return paid_cents // 2, "late"
    return paid_cents, "cancelled"
