"""Invariant 4 (SPEC-10 §4): write-back changes exactly the intended lines and keeps line endings.

Every Markdown edit of the coordination tools is checked as a line diff on a CRLF copy: the tick,
the deviation index row and spec note, and the milestone status line.
"""

from __future__ import annotations

import difflib
from pathlib import Path

from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from tests.spec05.helpers import INDEX, MILESTONE, SPEC, Clock, use_clock


def _to_crlf(path: Path) -> None:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))


def _diff(before: bytes, after: bytes) -> list[str]:
    """Changed lines as ``-``/``+`` entries; asserts both sides are pure CRLF."""
    for data in (before, after):
        assert b"\n" not in data.replace(b"\r\n", b"")
        assert data.endswith(b"\r\n")
    old = before.decode("utf-8").split("\r\n")
    new = after.decode("utf-8").split("\r\n")
    return [
        line
        for line in difflib.unified_diff(old, new, lineterm="", n=0)
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]


def test_inv04_writeback_changes_exactly_the_intended_lines(runtime: Runtime) -> None:
    use_clock(runtime, Clock())
    root = runtime.settings.project_root
    for rel in (MILESTONE, SPEC, INDEX):
        _to_crlf(root / rel)
    runtime.sync(full=True)
    snap = {rel: (root / rel).read_bytes() for rel in (MILESTONE, SPEC, INDEX)}

    coord.claim_task(runtime, "M01.1", "a")
    coord.complete_task(runtime, "M01.1", "a")
    tick = _diff(snap[MILESTONE], (root / MILESTONE).read_bytes())
    assert tick == [
        "-- [ ] **M01.1** Brew model with default steep times "
        "([SPEC-01 §1](../specs/SPEC-01-timer.md#1-brewing))",
        "+- [x] **M01.1** Brew model with default steep times "
        "([SPEC-01 §1](../specs/SPEC-01-timer.md#1-brewing))",
    ]

    dev = coord.log_deviation(
        runtime,
        "M01.2",
        "a",
        title="Countdown in tenths",
        spec_says="Seconds.",
        implementation_does="Tenths.",
        why="Smoother.",
        amends=["SPEC-01 §2"],
    )
    row = _diff(snap[INDEX], (root / INDEX).read_bytes())
    assert row == [
        f"+| [{dev['id']}](deviations/{dev['path'].rsplit('/', 1)[1]}) | Countdown in tenths "
        "| M01 | [SPEC-01 §2](specs/SPEC-01-timer.md#2-teas) | Open |"
    ]
    note = _diff(snap[SPEC], (root / SPEC).read_bytes())
    assert sorted(note) == [  # a blank line and the note, nothing removed; placement below
        "+",
        f"+> **DEVIATION:** see [{dev['id']}](../deviations/{dev['path'].rsplit('/', 1)[1]}) "
        "— Countdown in tenths",
    ]
    spec_lines = (root / SPEC).read_bytes().decode("utf-8").split("\r\n")
    at = next(i for i, ln in enumerate(spec_lines) if ln.startswith("> **DEVIATION:**"))
    assert spec_lines[at - 2].startswith("Each tea has a default steep time.")
    assert spec_lines[at + 1] == ""
    assert spec_lines[at + 2] == "## 3. Acceptance checks"

    before_status = (root / MILESTONE).read_bytes()
    for tid in ("M01.2", "M01.3"):
        coord.claim_task(runtime, tid, "a")
        coord.complete_task(runtime, tid, "a")
    after_ticks = (root / MILESTONE).read_bytes()
    assert len(_diff(before_status, after_ticks)) == 4  # two ticks, nothing else
    coord.complete_milestone(runtime, "M01", "a", "Checked")
    status = _diff(after_ticks, (root / MILESTONE).read_bytes())
    assert status == [
        "-**Status:**",
        f"+**Status:** DONE (2026-12-01). Checked. Deviations: D001, {dev['id']}.",
    ]
