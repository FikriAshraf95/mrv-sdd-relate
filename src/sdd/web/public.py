"""The public-mode wrapper of the HTTP API (SPEC-09 §4; plan M06b §6.3).

``sdd public`` serves only public data and has no write route, so there is no Host, token or
Origin check here (the daemon's :class:`~sdd.web.security.SecurityMiddleware` does those). What it
adds: a per-IP sliding-window rate limit, the client IP from a trusted proxy, and the security
headers on every response.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sdd.config import Settings
from sdd.errors import SddError
from sdd.web.errors import HTTP_STATUS

log = logging.getLogger("sdd.public")

__all__ = [
    "PUBLIC_PATHS",
    "RATE_QUERY",
    "RATE_REST",
    "PublicMiddleware",
    "RateLimiter",
    "client_ip",
]

# SPEC-07 §2 rows marked public, as (method, path template with `{id}` for `{id:path}`). Asserted
# against the spec by tests/invariants/test_inv06_drift.py.
PUBLIC_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/status"),
        ("GET", "/api/graph"),
        ("GET", "/api/nodes/{id}"),
        ("GET", "/api/board"),
        ("GET", "/api/milestones"),
        ("GET", "/api/sections/{ref}"),
        ("GET", "/api/tasks/{id}/context"),
        ("GET", "/api/impact"),
        ("GET", "/api/explain"),
        ("GET", "/api/find"),
        ("GET", "/api/changes"),
        ("GET", "/api/presets"),
        ("GET", "/api/presets/{name}"),
        ("GET", "/api/mermaid"),
        ("POST", "/api/query"),
        ("GET", "/api/events"),
        ("GET", "/api/next"),
    }
)

RATE_QUERY = 60  # POST /api/query per client IP and minute
RATE_REST = 600  # every other request
WINDOW = 60.0

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", b"default-src 'self'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


class RateLimiter:
    """A sliding window per ``(client, bucket)``: in memory, under a lock, pruned when empty."""

    def __init__(self, window: float = WINDOW, clock: Callable[[], float] = time.monotonic):
        self.window = window
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}

    def hit(self, client: str, bucket: str, limit: int) -> int | None:
        """Count one request; ``None`` if allowed, else the seconds until the oldest hit leaves."""
        now = self.clock()
        with self._lock:
            self._prune(now)
            hits = self._hits.setdefault((client, bucket), deque())
            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            return None

    def _prune(self, now: float) -> None:
        # bounded memory: drop expired hits and empty buckets (cheap while buckets are few)
        for key in list(self._hits):
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if not hits:
                del self._hits[key]


def _valid_ip(text: str) -> str | None:
    try:
        return str(ipaddress.ip_address(text.strip()))
    except ValueError:
        return None


def client_ip(scope: Scope, trusted: ipaddress.IPv4Network | ipaddress.IPv6Network | None) -> str:
    """The socket address, or ``CF-Connecting-IP`` / the first ``X-Forwarded-For`` entry when the
    socket address is inside the trusted proxy network. Never reads those headers otherwise."""
    client = scope.get("client")
    socket_host = str(client[0]) if client else "unknown"
    if trusted is None:
        return socket_host
    try:
        inside = ipaddress.ip_address(socket_host) in trusted
    except ValueError:
        inside = False
    if not inside:
        return socket_host
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
    cf = headers.get("cf-connecting-ip")
    if cf and (ip := _valid_ip(cf)):
        return ip
    forwarded = headers.get("x-forwarded-for", "").split(",")[0]
    if forwarded and (ip := _valid_ip(forwarded)):
        return ip
    return socket_host


class PublicMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        settings: Settings,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.app = app
        self.limiter = limiter or RateLimiter()
        self._trusted = (
            ipaddress.ip_network(settings.trusted_proxy_net, strict=False)
            if settings.trusted_proxy_net
            else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                names = {k for k, _ in SECURITY_HEADERS}
                rest = [(k, v) for k, v in message.get("headers", []) if k.lower() not in names]
                message = {**message, "headers": [*rest, *SECURITY_HEADERS]}
            await send(message)

        is_query = scope["method"] == "POST" and scope["path"] == "/api/query"
        bucket, limit = ("query", RATE_QUERY) if is_query else ("rest", RATE_REST)
        wait = self.limiter.hit(client_ip(scope, self._trusted), bucket, limit)
        if wait is not None:
            await _rate_limited(wait)(scope, receive, send_with_headers)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send_with_headers(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception:
            # Starlette's outer 500 handler would bypass this middleware's headers: answer here.
            log.exception("unhandled error on %s %s", scope["method"], scope["path"])
            if started:
                raise
            await Response("Internal Server Error", status_code=500, media_type="text/plain")(
                scope, receive, send_with_headers
            )


def _rate_limited(wait: int) -> Response:
    err = SddError("rate_limited", "Too many requests. Slow down and retry.")
    return Response(
        json.dumps(err.to_dict()),
        status_code=HTTP_STATUS["rate_limited"],
        media_type="application/json",
        headers={"Retry-After": str(wait)},
    )
