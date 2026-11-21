def chunk(text: str, size: int = 200) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
