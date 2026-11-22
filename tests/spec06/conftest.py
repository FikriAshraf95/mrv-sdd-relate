"""Fixtures for the SPEC-06 tests: a runtime on ``tool_style`` with its scripted git history."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sdd.service.runtime import Runtime
from tests.conftest import MakeProject, daemon_settings
from tests.history import TOOL_STYLE_HISTORY

MakeHistory = Callable[..., Runtime]


@pytest.fixture
def history_runtime(project: MakeProject) -> Iterator[MakeHistory]:
    """Factory: ``history_runtime(history=True, before=fn)`` → a synced Runtime on tool_style.

    ``before(root)`` may edit the project copy before the first sync.
    """
    opened: list[Runtime] = []

    def make(*, history: bool = True, before: Callable[[Path], None] | None = None) -> Runtime:
        root = project("tool_style", commits=TOOL_STYLE_HISTORY if history else ())
        if before is not None:
            before(root)
        runtime = Runtime.open(daemon_settings(root))
        opened.append(runtime)
        runtime.sync(full=True)
        return runtime

    yield make
    for runtime in opened:
        runtime.close()


@pytest.fixture
def hist(history_runtime: MakeHistory) -> Runtime:
    """tool_style with its git history, synced."""
    return history_runtime()
