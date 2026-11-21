"""The in-process event bus behind ``/api/events`` (SPEC-07 §3; plan M02 §4).

Publishers run on any thread (the sync thread, a request thread); subscribers live on an asyncio
loop. ``publish`` never blocks: it hands the event to each subscriber's loop with
``call_soon_threadsafe``. A subscriber whose queue is full is dropped (its stream ends and the
browser reconnects), so a slow client cannot hold memory or stall a writer.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Mapping
from typing import Any

__all__ = ["EventBus", "Subscription"]


class Subscription:
    """One subscriber: an ``asyncio.Queue`` fed from the bus. Use inside its own loop."""

    def __init__(self, bus: EventBus, loop: asyncio.AbstractEventLoop, maxsize: int) -> None:
        self._bus = bus
        self._loop = loop
        self._queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize)

    async def get(self) -> tuple[str, dict[str, Any]]:
        """The next ``(type, data)``; raises ``asyncio.QueueShutDown`` once closed or dropped."""
        return await self._queue.get()

    def close(self) -> None:
        """Stop receiving. Safe to call twice, and from any thread."""
        self._bus._remove(self)
        with contextlib.suppress(RuntimeError):  # the loop is already closed
            self._loop.call_soon_threadsafe(self._shutdown)

    def _shutdown(self) -> None:
        self._queue.shutdown(immediate=True)

    def _put(self, item: tuple[str, dict[str, Any]]) -> None:  # runs on the subscriber's loop
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self.close()
        except asyncio.QueueShutDown:
            pass


class EventBus:
    """Thread-safe publish/subscribe for ``task``, ``graph_changed`` and later event types."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[Subscription] = []

    def subscribe(self, loop: asyncio.AbstractEventLoop, *, maxsize: int = 1000) -> Subscription:
        sub = Subscription(self, loop, maxsize)
        with self._lock:
            self._subs.append(sub)
        return sub

    def publish(self, type_: str, data: Mapping[str, Any]) -> None:
        """Deliver ``(type_, data)`` to every subscriber. Any thread; never blocks."""
        item = (type_, dict(data))
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub._loop.call_soon_threadsafe(sub._put, item)
            except RuntimeError:  # loop closed under us: the subscriber is gone
                self._remove(sub)

    def _remove(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)
