"""Named read queries (SPEC-06 §1 rule 3): the ``*.cypher`` files next to this module.

Each file holds several queries. A query starts at a ``// name: <dotted.name>`` line and runs to
the next one; other ``//`` lines are comments and are dropped. Queries take parameters only and
are read-only, so the static demo can run the same files. ``service/impact.py`` calls them by
name and holds no Cypher of its own.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

from sdd.graph.store import Row, Store

__all__ = ["get", "load", "names", "run"]

_NAME_RE = re.compile(r"^//\s*name:\s*(?P<name>[A-Za-z0-9_.]+)\s*$")


def _parse(text: str, source: str) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        m = _NAME_RE.match(line.strip())
        if m:
            name = m["name"]
            if name in found:
                raise ValueError(f"{source}: duplicate query name {name!r}")
            current = found.setdefault(name, [])
        elif current is not None and not line.strip().startswith("//"):
            current.append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


@cache
def load() -> dict[str, str]:
    """Every named query of every ``.cypher`` file, parsed once. A duplicate name raises."""
    queries: dict[str, str] = {}
    folder = resources.files("sdd.graph").joinpath("queries")
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".cypher"):
            continue
        for name, text in _parse(entry.read_text(encoding="utf-8"), entry.name).items():
            if name in queries:
                raise ValueError(f"{entry.name}: duplicate query name {name!r}")
            queries[name] = text
    return queries


def names() -> list[str]:
    return sorted(load())


def get(name: str) -> str:
    """The Cypher of a named query (``KeyError`` for an unknown name)."""
    return load()[name]


def run(store: Store, query: str, /, **params: object) -> list[Row]:
    """Run the named query ``query`` on the store's read path."""
    return store.read(get(query), params)
