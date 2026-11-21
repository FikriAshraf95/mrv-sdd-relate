"""The JSON API (SPEC-07 §2; plan M02 §5.1): endpoints 1–4, 6, 16 and 19.

Each handler validates its input, calls one ``service/`` function and returns its JSON. Handlers
are plain ``def`` functions, which Starlette runs in its thread pool, so a blocking store read never
stalls the event loop. ``/mcp`` mounts here from M03a.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from sdd.errors import SddError
from sdd.service import api_views
from sdd.service.runtime import Runtime
from sdd.web import sse
from sdd.web.errors import HTTP_STATUS, error_response
from sdd.web.security import SecurityMiddleware

__all__ = ["HTTP_STATUS", "create_app"]


def _int(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise SddError("invalid_input", f"{name}={raw!r} is not an integer.") from None


def create_app(runtime: Runtime) -> Starlette:
    def health(request: Request) -> Response:
        return JSONResponse(api_views.health(runtime))

    def status(request: Request) -> Response:
        return JSONResponse(api_views.status(runtime))

    def graph(request: Request) -> Response:
        raw = request.query_params.get("labels", "")
        labels = [x.strip() for x in raw.split(",") if x.strip()]
        result = api_views.graph(
            runtime,
            labels,
            request.query_params.get("focus") or None,
            _int(request, "depth", 1),
            _int(request, "limit", 300),
        )
        return JSONResponse(result)

    def node(request: Request) -> Response:
        return JSONResponse(api_views.node(runtime, request.path_params["id"]))

    def milestones(request: Request) -> Response:
        return JSONResponse(api_views.milestones(runtime))

    def sync(request: Request) -> Response:
        return JSONResponse(runtime.sync(full=True))

    async def sdd_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, SddError)
        return error_response(exc)

    routes: list[Any] = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/status", status, methods=["GET"]),
        Route("/api/graph", graph, methods=["GET"]),
        Route("/api/nodes/{id:path}", node, methods=["GET"]),
        Route("/api/milestones", milestones, methods=["GET"]),
        Route("/api/events", sse.events(runtime), methods=["GET"]),
        Route("/api/sync", sync, methods=["POST"]),
        # M03a: mount /mcp here (streamable_http_app)
    ]
    return Starlette(
        routes=routes,
        middleware=[Middleware(SecurityMiddleware, settings=runtime.settings)],
        exception_handlers={SddError: sdd_error},
    )
