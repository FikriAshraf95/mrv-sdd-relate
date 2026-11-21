"""``sdd ids`` (SPEC-08 §2): stable task IDs for legacy checkbox lines, through write-back."""

from __future__ import annotations

import difflib
import posixpath
from dataclasses import dataclass
from typing import Any

from sdd.config import Settings
from sdd.errors import SddError
from sdd.ids import InvalidIdError, id_from_filename, normalise
from sdd.service import remote
from sdd.sync import indexer, writeback


@dataclass(frozen=True, slots=True)
class IdPlan:
    path: str
    milestone: str
    count: int
    new_text: str
    diff: str


def plan_ids(settings: Settings, milestone: str | None = None) -> list[IdPlan]:
    """The rewrite for every milestone file that has legacy task lines (or just ``milestone``)."""
    wanted: str | None = None
    if milestone is not None:
        try:
            wanted = normalise(milestone)
        except InvalidIdError as exc:
            raise SddError("invalid_input", str(exc)) from None
    plans: list[IdPlan] = []
    matched = False
    for path, kind in indexer.discover(settings).items():
        if kind != "milestone":
            continue
        ident = id_from_filename(posixpath.basename(path))
        if wanted is not None and ident != wanted:
            continue
        matched = True
        raw = (settings.project_root / path).read_bytes().decode("utf-8", errors="replace")
        old = raw.replace("\r\n", "\n")
        new, count = writeback.add_task_ids(path, old)
        if count:
            diff = "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            plans.append(IdPlan(path, ident or "", count, new, diff))
    if wanted is not None and not matched:
        raise SddError(
            "milestone_not_found",
            f"No milestone file for {wanted}.",
            details={"milestone": wanted},
        )
    return plans


def write_ids(settings: Settings, plans: list[IdPlan]) -> list[dict[str, Any]]:
    """Apply a plan with the atomic write helper (line endings kept). Does not sync.

    Refuses with ``daemon_running`` while a daemon owns the project (SPEC-01 §1 rule 3).
    """
    remote.ensure_no_daemon(settings, check_store=True)
    done = []
    for plan in plans:
        writeback.atomic_write(settings.project_root / plan.path, plan.new_text)
        done.append({"path": plan.path, "milestone": plan.milestone, "added": plan.count})
    return done
