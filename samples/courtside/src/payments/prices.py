"""Hourly rates by court surface, in cents (SPEC-04 §1)."""

RATES_CENTS = {"hard": 1800, "clay": 2200, "wood": 1500, "synthetic": 1600}


def price_cents(surface: str, hours: int = 1) -> int:
    return RATES_CENTS[surface] * hours
