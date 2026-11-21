"""The coordination commands behind the CLI (SPEC-08 §1 rules 1 and 4).

With a daemon running for the project, each command is one call to its API (the daemon owns the
store). Without one, the command runs the same ``service/`` function itself: reads on a
read-only open of the store, writes on a writable open after a full sync, so the graph matches
the Markdown it is about to edit. ``:memory:`` writes nothing, so it refuses the write commands.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph.store import Store
from sdd.service import changes, coordination, remote
from sdd.service.runtime import Runtime

__all__ = [
    "changes_since",
    "claim",
    "deviation",
    "done",
    "milestone_done",
    "next_tasks",
    "release",
]


def _client(settings: Settings) -> remote.DaemonClient | None:
    if remote.routes_through_daemon(settings) and (info := remote.detect(settings)):
        return remote.DaemonClient(settings, info)
    return None


def _id(value: str) -> str:
    return quote(value.strip(), safe="")


@contextmanager
def _local(settings: Settings, *, write: bool) -> Iterator[Runtime]:
    if settings.in_memory:
        if write:
            raise SddError(
                "invalid_input", "--store :memory: writes nothing; drop it to change the project."
            )
        runtime = Runtime.open(settings)
        try:
            runtime.sync(full=True)
            yield runtime
        finally:
            runtime.close()
        return
    if write:
        runtime = Runtime.open(settings)  # daemon_running if another process writes the store
        try:
            runtime.sync(full=True)
            yield runtime
        finally:
            runtime.close()
        return
    store = Store.open(settings.store_path, read_only=True)
    try:
        yield Runtime(settings=settings, store=store)
    finally:
        store.close()


def next_tasks(
    settings: Settings, milestone: str | None, limit: int, agent: str | None
) -> dict[str, Any]:
    if client := _client(settings):
        result: dict[str, Any] = client.get(
            "/api/next", {"milestone": milestone, "limit": limit, "agent": agent}
        )
        return result
    with _local(settings, write=False) as runtime:
        return coordination.next_tasks(runtime, milestone, limit, agent)


def changes_since(settings: Settings, since: str, agent: str | None) -> dict[str, Any]:
    if client := _client(settings):
        result: dict[str, Any] = client.get("/api/changes", {"since": since, "agent": agent})
        return result
    with _local(settings, write=False) as runtime:
        return changes.what_changed(runtime, since, agent)


def claim(settings: Settings, task_id: str, agent: str) -> dict[str, Any]:
    if client := _client(settings):
        result: dict[str, Any] = client.post(f"/api/tasks/{_id(task_id)}/claim", {"agent": agent})
        return result
    with _local(settings, write=True) as runtime:
        return coordination.claim_task(runtime, task_id, agent)


def release(
    settings: Settings, task_id: str, agent: str, reason: str | None, force: bool
) -> dict[str, Any]:
    body = {"agent": agent, "reason": reason, "force": force}
    if client := _client(settings):
        result: dict[str, Any] = client.post(f"/api/tasks/{_id(task_id)}/release", body)
        return result
    with _local(settings, write=True) as runtime:
        return coordination.release_task(runtime, task_id, agent, reason, force)


def done(
    settings: Settings,
    task_id: str,
    agent: str,
    *,
    notes: str | None,
    files_touched: list[str] | None,
    commit: str | None,
) -> dict[str, Any]:
    body = {"agent": agent, "notes": notes, "files_touched": files_touched, "commit": commit}
    if client := _client(settings):
        result: dict[str, Any] = client.post(f"/api/tasks/{_id(task_id)}/complete", body)
        return result
    with _local(settings, write=True) as runtime:
        return coordination.complete_task(
            runtime, task_id, agent, notes=notes, files_touched=files_touched, commit=commit
        )


def deviation(settings: Settings, task_id: str, agent: str, **fields: Any) -> dict[str, Any]:
    """``fields``: title, spec_says, implementation_does, why, consequences, amends, affects,
    status (the ``log_deviation`` arguments)."""
    if client := _client(settings):
        result: dict[str, Any] = client.post(
            "/api/deviations", {"task_id": task_id, "agent": agent, **fields}
        )
        return result
    with _local(settings, write=True) as runtime:
        return coordination.log_deviation(runtime, task_id, agent, **fields)


def milestone_done(
    settings: Settings, milestone_id: str, agent: str, verification: str
) -> dict[str, Any]:
    body = {"agent": agent, "verification": verification}
    if client := _client(settings):
        result: dict[str, Any] = client.post(f"/api/milestones/{_id(milestone_id)}/complete", body)
        return result
    with _local(settings, write=True) as runtime:
        return coordination.complete_milestone(runtime, milestone_id, agent, verification)
