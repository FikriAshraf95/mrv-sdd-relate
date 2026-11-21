"""``GET /api/events`` (SPEC-07 §3; endpoint 16): a Server-Sent Events stream of bus events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from sse_starlette.sse import EventSourceResponse
from starlette.requests import Request

from sdd.service.events import Subscription
from sdd.service.runtime import Runtime

__all__ = ["event_stream", "events"]

PING_SECONDS = 15


async def event_stream(sub: Subscription) -> AsyncIterator[dict[str, str]]:
    """Yield ``{"event", "data"}`` items until the subscription closes; always closes it."""
    try:
        while True:
            try:
                type_, data = await sub.get()
            except asyncio.QueueShutDown:
                return
            yield {"event": type_, "data": json.dumps(data, ensure_ascii=False)}
    finally:
        sub.close()


def events(runtime: Runtime) -> Callable[[Request], Awaitable[EventSourceResponse]]:
    """The route handler for ``/api/events``, bound to ``runtime``."""

    async def handler(request: Request) -> EventSourceResponse:
        sub = runtime.events.subscribe(asyncio.get_running_loop())
        return EventSourceResponse(event_stream(sub), ping=PING_SECONDS)

    return handler
