"""Task writes (SPEC-05). M02 ships only the tick; M03a adds claims and ``complete_task`` on top."""

from __future__ import annotations

from typing import Any

from sdd.errors import SddError
from sdd.ids import InvalidIdError, normalise
from sdd.service.runtime import Runtime, publish_changed
from sdd.sync import writeback


def tick_task(runtime: Runtime, task_id: str, *, agent: str | None = None) -> dict[str, Any]:
    """Tick one task box in Markdown and the graph, then publish ``task`` and ``graph_changed``.

    Serialized with syncs through ``runtime.sync_lock``. No HTTP route and no CLI yet: M03a's
    ``complete_task`` wraps this.
    """
    try:
        ident = normalise(task_id)
    except InvalidIdError as exc:
        raise SddError("invalid_input", str(exc)) from None
    settings = runtime.settings
    with runtime.sync_lock:
        result = runtime.store.write(
            lambda tx: writeback.tick_task(tx, settings, ident, now=settings.now_iso(), agent=agent)
        )
    runtime.events.publish(
        "task",
        {
            "id": result.task_id,
            "status": result.status,
            "claimed_by": None,
            "milestone_id": result.milestone_id,
        },
    )
    publish_changed(runtime.events, [result.task_id, f"file:{result.path}"])
    return {
        "task": result.task_id,
        "path": result.path,
        "changed_file": result.changed_file,
        "status": result.status,
    }
