"""Host, token and Origin checks for ``/api`` and ``/mcp`` (SPEC-09 §2 rules 2–4; plan M02 §5.2).

A pure ASGI middleware, so it also guards streaming responses. Order: Host, token, Origin. Every
rejection uses the one error shape. The ``Authorization`` header is never logged.
"""

from __future__ import annotations

import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

from sdd.config import Settings
from sdd.errors import SddError
from sdd.web.errors import error_response

__all__ = ["SecurityMiddleware", "parse_host"]

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def parse_host(value: str) -> str:
    """The host part of a ``Host`` header value: ``[::1]:8770`` → ``::1``, ``a:80`` → ``a``."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].partition("]")[0]
    if value.count(":") == 1:
        return value.partition(":")[0]
    return value


def _guarded(path: str) -> bool:
    return path in ("/api", "/mcp") or path.startswith(("/api/", "/mcp/"))


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._token = settings.token.encode("utf-8") if settings.token else None
        self._hosts = LOOPBACK_HOSTS | {parse_host(h) for h in settings.allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        error = self._check(scope["method"], scope["path"], headers)
        if error is not None:
            await error_response(error)(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _check(self, method: str, path: str, headers: dict[str, str]) -> SddError | None:
        host = headers.get("host")
        # Host first, on every request: a rebinding page must not read anything (rule 3).
        if host is None or parse_host(host) not in self._hosts:
            return SddError(
                "forbidden_host",
                "The Host header is not a loopback host or in SDD_ALLOWED_HOSTS.",
            )
        if not _guarded(path):
            return None
        if self._token is not None:
            given = headers.get("authorization", "")
            scheme, _, secret = given.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                secret.strip().encode("utf-8"), self._token
            ):
                return SddError("unauthorized", "Send `Authorization: Bearer <SDD_TOKEN>`.")
        origin = headers.get("origin")
        writes = path.startswith("/mcp") or method not in SAFE_METHODS
        if writes and origin is not None and origin != f"http://{host}":
            return SddError("forbidden_origin", "Requests from another origin are refused.")
        return None
