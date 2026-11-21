GREEN_TEA_SECONDS = 120


def steep_seconds(tea: str) -> int:
    return GREEN_TEA_SECONDS if tea == "green" else 180
