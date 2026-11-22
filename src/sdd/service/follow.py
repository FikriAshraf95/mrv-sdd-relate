"""Follow the writer: reopen the read-only store when ``manifest.json`` changes (SPEC-01 §1 rule
4, SPEC-11 §4 step 3) and publish what changed (SPEC-07 §3).

A ``read_only`` connection never moves forward, so ``sdd public`` swaps in a freshly opened store
each time the writer's checkpoint rewrites ``manifest.json``. The previous store is closed a
little later so a request that still holds it can finish.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from sdd.errors import SddError
from sdd.graph.store import Store
from sdd.service.runtime import Runtime, publish_changed

__all__ = ["Follower", "read_states"]

log = logging.getLogger("sdd.follow")

MANIFEST = "manifest.json"
CLOSE_DELAY = 10.0  # seconds the previous store stays open after a swap

Stamp = tuple[int, int, int]  # (st_ino, st_mtime_ns, st_size)
TaskState = tuple[Any, Any, Any]  # (status, claimed_by, milestone_id)


def read_states(store: Store) -> tuple[dict[str, TaskState], dict[str, Any]]:
    """Task states ``{id: (status, claimed_by, milestone_id)}`` and ``{milestone id: status}``."""
    tasks = {
        r["id"]: (r["status"], r["claimed_by"], r["milestone_id"])
        for r in store.read(
            "MATCH (t:Task) RETURN t.id AS id, t.status AS status, t.claimed_by AS claimed_by, "
            "t.milestone_id AS milestone_id"
        )
    }
    milestones = {
        r["id"]: r["status"]
        for r in store.read("MATCH (m:Milestone) RETURN m.id AS id, m.status AS status")
    }
    return tasks, milestones


class Follower:
    """A thread that polls ``manifest.json`` and swaps ``runtime.store`` when it changed."""

    def __init__(self, runtime: Runtime, interval: float = 2.0, close_delay: float = CLOSE_DELAY):
        self.runtime = runtime
        self.interval = interval
        self.close_delay = close_delay
        self.manifest = Path(runtime.settings.store_path) / MANIFEST
        self._seen: Stamp | None = self._stamp()
        self._tasks, self._milestones = self._states(runtime.store)
        self._stop = threading.Event()
        self._timers: list[threading.Timer] = []
        self._thread = threading.Thread(target=self._loop, name="sdd-follow", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        """Stop polling and close every store this follower still holds (the current one too)."""
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join()
        for timer in self._timers:
            timer.cancel()
            timer.function(*timer.args)  # close the previous store now
        self._timers.clear()
        self.runtime.close()

    def _stamp(self) -> Stamp | None:
        try:
            st = os.stat(self.manifest)
        except OSError:
            return None  # no manifest yet (the writer has not flushed): keep waiting
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def _states(self, store: Store) -> tuple[dict[str, TaskState], dict[str, Any]]:
        try:
            return read_states(store)
        except SddError as exc:
            log.warning("could not read task states: %s", exc.code)
            return {}, {}

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:  # a bad poll must never kill the follower
                log.exception("follow check failed")

    def check(self) -> bool:
        """One poll: True when a new store was swapped in."""
        stamp = self._stamp()
        if stamp is None or stamp == self._seen:
            return False
        try:
            new = Store.open(self.runtime.settings.store_path, read_only=True)
        except SddError as exc:
            log.warning("reopen failed (%s); keeping the old snapshot", exc.code)
            return False
        try:
            tasks, milestones = read_states(new)
        except SddError as exc:
            log.warning("reading the new snapshot failed (%s); keeping the old one", exc.code)
            new.close()
            return False
        self._seen = stamp
        old = self.runtime.store
        self.runtime.store = new
        self.runtime.synced_at = None  # health re-reads Meta
        timer = threading.Timer(self.close_delay, self._close_old, args=(old,))
        timer.daemon = True
        self._timers = [t for t in self._timers if t.is_alive()]
        self._timers.append(timer)
        timer.start()
        self._publish(tasks, milestones)
        self._tasks, self._milestones = tasks, milestones
        return True

    def _close_old(self, store: Store) -> None:
        try:
            store.close()
        except Exception:
            log.exception("closing the previous snapshot failed")

    def _publish(self, tasks: dict[str, TaskState], milestones: dict[str, Any]) -> None:
        events = self.runtime.events
        changed: list[str] = []
        for task_id, state in tasks.items():
            if self._tasks.get(task_id) != state:
                status, claimed_by, milestone_id = state
                events.publish(
                    "task",
                    {
                        "id": task_id,
                        "status": status,
                        "claimed_by": claimed_by,
                        "milestone_id": milestone_id,
                    },
                )
                changed.append(task_id)
        for milestone_id, status in milestones.items():
            if self._milestones.get(milestone_id) != status:
                events.publish("milestone", {"id": milestone_id, "status": status})
                changed.append(milestone_id)
        if changed:
            publish_changed(events, changed)
