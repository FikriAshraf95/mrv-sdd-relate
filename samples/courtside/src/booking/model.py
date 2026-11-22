"""The booking row (SPEC-02 `bookings`, SPEC-03 §2)."""

from dataclasses import dataclass
from datetime import datetime

STATUSES = ("held", "confirmed", "cancelled")


@dataclass(frozen=True)
class Booking:
    id: str
    member_id: str
    court_id: str
    starts_at: datetime
    ends_at: datetime
    status: str = "confirmed"
    cancelled_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.status != "cancelled"
