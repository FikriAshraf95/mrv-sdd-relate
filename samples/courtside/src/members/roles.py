"""Roles and the session token (SPEC-01 §2 and §3)."""

from datetime import datetime, timedelta

ROLES = ("member", "desk", "admin")
SESSION_LIFETIME = timedelta(hours=8)


def can_override(role: str) -> bool:
    """Desk staff and admins may use the overrides of SPEC-03 §5."""
    return role in ("desk", "admin")


def session_valid(issued_at: datetime, now: datetime) -> bool:
    return now - issued_at < SESSION_LIFETIME
