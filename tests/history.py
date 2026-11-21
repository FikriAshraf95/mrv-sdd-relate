"""Scripted git history for the ``tool_style`` fixture (M04a.1).

Pass it to the ``project`` factory: ``project("tool_style", commits=TOOL_STYLE_HISTORY)``. The
copy gets ``chore: import fixture`` first, then these commits in order, with fixed dates.
"""

from __future__ import annotations

from tests.conftest import Commit

LOADER = "def load(title: str, text: str) -> dict[str, str]:\n    return {}\n"
CHUNKER = "def chunk(text: str) -> list[str]:\n    return [text]\n"

TOOL_STYLE_HISTORY: tuple[Commit, ...] = (
    Commit(
        "feat: brew model [M01.1]",
        {"src/kettle/brew.py": "GREEN_TEA_SECONDS = 120\nBLACK_TEA_SECONDS = 240\n"},
    ),
    Commit("feat: loader [M02.1]", {"src/ingest/loader.py": LOADER}),
    Commit("chore: tidy (M02)", {"src/ingest/chunker.py": CHUNKER}),
    Commit("docs: readme", {"README.txt": "Kettle fixture, updated.\n"}),
)
