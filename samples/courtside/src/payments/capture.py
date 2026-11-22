"""Taking payment for a booking, once (SPEC-04 §2). The desk captures at check-in (D005)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Payment:
    id: str
    booking_id: str
    amount_cents: int
    captured_at: datetime | None = None


def capture(
    payments: dict[str, Payment], booking_id: str, amount_cents: int, now: datetime
) -> Payment:
    """Record the payment; a second call for one booking returns the first row."""
    if booking_id in payments:
        return payments[booking_id]
    payments[booking_id] = Payment(f"p-{len(payments) + 1}", booking_id, amount_cents, now)
    return payments[booking_id]
