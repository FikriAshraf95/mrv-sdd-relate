"""Helpers for the coordination tests (SPEC-05, and the SPEC-01/04/08 checks that use them)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from sdd.service.runtime import Runtime

MILESTONE = "docs/milestones/M01-timer.md"
SPEC = "docs/specs/SPEC-01-timer.md"
INDEX = "docs/DEVIATIONS.md"

# A second milestone that depends on M01 and links to it (invented, like the fixture).
M02 = """# M02 — Brew log

> **Depends on:** [M01](M01-timer.md)
> **Read first:** [SPEC-01 §2](../specs/SPEC-01-timer.md#2-teas)

## Goal
A log of every brew.

## Tasks
### Backend
- [ ] **M02.1** Log each brew ([SPEC-01 §2](../specs/SPEC-01-timer.md#2-teas))

## Acceptance criteria
1. Every brew is logged.

**Status:**
"""

# A milestone with no dependency whose task shares M01.1's governing section.
M03 = """# M03 — Kettle sounds

> **Depends on:** nothing
> **Read first:** [SPEC-01 §1](../specs/SPEC-01-timer.md#1-brewing)

## Goal
A whistle when the brew is ready.

## Tasks
### Backend
- [ ] **M03.1** Whistle at the end of a brew ([SPEC-01 §1](../specs/SPEC-01-timer.md#1-brewing))

## Acceptance criteria
1. The kettle whistles.

**Status:**
"""


class Clock:
    """A settable clock for ``Settings.clock`` (SPEC-10 §1: only time is mocked)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 12, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def use_clock(runtime: Runtime, clock: Clock) -> Clock:
    runtime.settings = dataclasses.replace(runtime.settings, clock=clock)
    return clock


def write_file(runtime: Runtime, rel: str, text: str) -> None:
    """Write a project file as a person would (LF), then sync like the watcher does."""
    path = runtime.settings.project_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    runtime.sync(full=True)


def read(runtime: Runtime, rel: str) -> str:
    return (runtime.settings.project_root / rel).read_text(encoding="utf-8")


def task(runtime: Runtime, task_id: str) -> dict[str, Any]:
    rows = runtime.store.read("MATCH (t:Task {id: $id}) RETURN properties(t) AS p", {"id": task_id})
    return dict(rows[0]["p"])


def events(runtime: Runtime, kind: str) -> list[dict[str, Any]]:
    rows = runtime.store.read(
        "MATCH (e:Event) WHERE e.kind = $k RETURN properties(e) AS e ORDER BY e.at, e.id",
        {"k": kind},
    )
    return [dict(r["e"]) for r in rows]


def claims_on(runtime: Runtime, task_id: str) -> int:
    rows = runtime.store.read(
        "MATCH (:Agent)-[r:CLAIMED]->(:Task {id: $id}) RETURN count(r) AS n", {"id": task_id}
    )
    return int(rows[0]["n"])
