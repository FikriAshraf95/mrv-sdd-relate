"""``replay.toml``: the sprint replay's start state, scripted outcomes and deviations (SPEC-11 §4).

Stdlib and ``errors`` only. Unknown keys, a task outside ``run.milestones`` or a missing file
raise ``invalid_input`` naming the key.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdd.errors import SddError

__all__ = ["ReplayScript", "ScriptedDeviation", "TaskOutcome", "load_script"]

SCRIPT_NAME = "replay.toml"
_MILESTONE = re.compile(r"^M\d+[a-z]?$")
_TASK = re.compile(r"^(M\d+[a-z]?)\.\d+$")


@dataclass(frozen=True)
class TaskOutcome:
    id: str
    notes: str | None = None
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScriptedDeviation:
    task: str
    title: str
    amends: tuple[str, ...]
    spec_says: str
    does: str
    why: str
    consequences: str | None = None
    affects: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ReplayScript:
    unticked: tuple[str, ...]
    milestones: tuple[str, ...]
    verification: str
    outcomes: dict[str, TaskOutcome]
    deviations: dict[str, ScriptedDeviation]  # by task ID


def _bad(path: Path, message: str, key: str) -> SddError:
    return SddError("invalid_input", f"{path}: {message}", details={"key": key})


def _check_keys(path: Path, where: str, table: dict[str, Any], allowed: set[str]) -> None:
    for key in table:
        if key not in allowed:
            full = f"{where}.{key}" if where else key
            raise _bad(
                path, f"unknown key '{full}'. Known keys: {', '.join(sorted(allowed))}.", full
            )


def _str(path: Path, where: str, table: dict[str, Any], key: str, *, required: bool = True) -> Any:
    value = table.get(key)
    full = f"{where}.{key}"
    if value is None:
        if required:
            raise _bad(path, f"'{full}' is required.", full)
        return None
    if not isinstance(value, str) or not value.strip():
        raise _bad(path, f"'{full}' must be a non-empty string.", full)
    return value


def _strs(path: Path, where: str, table: dict[str, Any], key: str, *, required: bool) -> Any:
    value = table.get(key)
    full = f"{where}.{key}"
    if value is None:
        if required:
            raise _bad(path, f"'{full}' is required.", full)
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise _bad(path, f"'{full}' must be a list of strings.", full)
    return tuple(value)


def _milestones(path: Path, where: str, table: dict[str, Any], key: str) -> tuple[str, ...]:
    values = _strs(path, where, table, key, required=True)
    for value in values:
        if not _MILESTONE.match(value):
            raise _bad(path, f"'{where}.{key}': {value!r} is not a milestone ID.", f"{where}.{key}")
    return tuple(values)


def _task_in_run(path: Path, where: str, task: str, run: tuple[str, ...]) -> str:
    match = _TASK.match(task)
    if match is None or match.group(1) not in run:
        raise _bad(path, f"'{where}': task {task!r} is not in run.milestones.", where)
    return task


def load_script(path: Path) -> ReplayScript:
    """Parse ``path`` (a ``replay.toml``) into a :class:`ReplayScript`."""
    if not path.is_file():
        raise SddError("invalid_input", f"{path} does not exist.", details={"key": SCRIPT_NAME})
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise SddError("invalid_input", f"{path} is not valid TOML: {exc}.") from exc
    _check_keys(path, "", raw, {"start", "run", "task", "deviation"})
    start = raw.get("start")
    run = raw.get("run")
    if not isinstance(start, dict):
        raise _bad(path, "the [start] table is required.", "start")
    if not isinstance(run, dict):
        raise _bad(path, "the [run] table is required.", "run")
    _check_keys(path, "start", start, {"unticked"})
    _check_keys(path, "run", run, {"milestones", "verification"})
    unticked = _milestones(path, "start", start, "unticked")
    milestones = _milestones(path, "run", run, "milestones")
    verification = _str(path, "run", run, "verification")

    outcomes: dict[str, TaskOutcome] = {}
    for entry in _tables(path, raw, "task"):
        _check_keys(path, "task", entry, {"id", "notes", "files"})
        task = _task_in_run(path, "task.id", _str(path, "task", entry, "id"), milestones)
        files = _strs(path, "task", entry, "files", required=False) or ()
        outcomes[task] = TaskOutcome(
            task, _str(path, "task", entry, "notes", required=False), files
        )

    deviations: dict[str, ScriptedDeviation] = {}
    for entry in _tables(path, raw, "deviation"):
        _check_keys(
            path,
            "deviation",
            entry,
            {"task", "title", "amends", "spec_says", "does", "why", "consequences", "affects"},
        )
        task = _task_in_run(
            path, "deviation.task", _str(path, "deviation", entry, "task"), milestones
        )
        deviations[task] = ScriptedDeviation(
            task=task,
            title=_str(path, "deviation", entry, "title"),
            amends=_strs(path, "deviation", entry, "amends", required=True),
            spec_says=_str(path, "deviation", entry, "spec_says"),
            does=_str(path, "deviation", entry, "does"),
            why=_str(path, "deviation", entry, "why"),
            consequences=_str(path, "deviation", entry, "consequences", required=False),
            affects=_strs(path, "deviation", entry, "affects", required=False),
        )
    return ReplayScript(unticked, milestones, verification, outcomes, deviations)


def _tables(path: Path, raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, dict) for v in value):
        raise _bad(path, f"'{key}' must be an array of tables ([[{key}]]).", key)
    return value
