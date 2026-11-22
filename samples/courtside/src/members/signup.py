"""Sign-up with a unique email address (SPEC-01 §1)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    id: str
    email: str
    name: str
    role: str = "member"


class EmailTaken(Exception):
    """A second sign-up with an address that already has an account."""


def sign_up(existing: dict[str, Member], email: str, name: str) -> Member:
    key = email.strip().lower()
    if key in existing:
        raise EmailTaken(f"{key} already has an account; log in instead.")
    member = Member(id=f"m-{len(existing) + 1}", email=key, name=name.strip())
    existing[key] = member
    return member
