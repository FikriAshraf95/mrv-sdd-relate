"""The JSON API (SPEC-07 §2): endpoints 1–19 and 21, and ``/mcp``.

Each handler validates its input, calls one ``service/`` function and returns its JSON. Read
handlers are plain ``def`` functions, which Starlette runs in its thread pool, so a blocking store
read never stalls the event loop; write handlers read the JSON body, then do the same through
``run_in_threadpool``. ``/mcp`` is built by the daemon (``sdd.mcp`` and ``sdd.web`` stay
independent) and passed in as ``mcp_app``.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from sdd.errors import SddError
from sdd.service import api_views, changes, context, coordination, exports, impact, query_guard
from sdd.service.runtime import Runtime
from sdd.web import sse
from sdd.web.errors import HTTP_STATUS, error_response
from sdd.web.public import PublicMiddleware
from sdd.web.security import SecurityMiddleware

__all__ = ["HTTP_STATUS", "STATIC_DIR", "create_app"]

STATIC_DIR = Path(__file__).parent / "static"


def _int(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise SddError("invalid_input", f"{name}={raw!r} is not an integer.") from None


def _q(request: Request, name: str) -> str | None:
    return request.query_params.get(name) or None


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise SddError("invalid_input", "The request body is not valid JSON.") from None
    if not isinstance(data, dict):
        raise SddError("invalid_input", "The request body must be a JSON object.")
    return data


def _str(data: dict[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is not None and not isinstance(value, str):
        raise SddError("invalid_input", f"{name} must be a string.")
    return value


def _strs(data: dict[str, Any], name: str) -> list[str] | None:
    value = data.get(name)
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SddError("invalid_input", f"{name} must be a list of strings.")
    return value


def _bool(data: dict[str, Any], name: str) -> bool:
    value = data.get(name, False)
    if not isinstance(value, bool):
        raise SddError("invalid_input", f"{name} must be true or false.")
    return value


class _GetOnly:
    """Public mode: the dashboard answers GET and HEAD; any other method on an unknown path is a
    404 (so ``POST /mcp`` is 404, not the static handler's 405)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in ("GET", "HEAD"):
            await Response("Not Found", status_code=404, media_type="text/plain")(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)


def create_app(  # noqa: PLR0915 - one flat closure per endpoint
    runtime: Runtime, *, mcp_app: Starlette | None = None, public: bool = False
) -> Starlette:
    """The API. ``public=True`` is ``sdd public`` (SPEC-09 §4): no ``/mcp``, the write routes answer
    403 ``read_only``, ``agent`` parameters are ignored, and :class:`PublicMiddleware` replaces
    the daemon's security middleware."""
    if public and mcp_app is not None:
        raise ValueError("public mode never mounts /mcp")

    def agent_of(request: Request) -> str | None:
        return None if public else _q(request, "agent")

    def health(request: Request) -> Response:
        return JSONResponse(api_views.health(runtime))

    def status(request: Request) -> Response:
        return JSONResponse(api_views.status(runtime, agent_of(request)))

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

    def board(request: Request) -> Response:
        return JSONResponse(api_views.board(runtime, _q(request, "milestone")))

    def milestones(request: Request) -> Response:
        return JSONResponse(api_views.milestones(runtime))

    def next_tasks(request: Request) -> Response:
        result = coordination.next_tasks(
            runtime, _q(request, "milestone"), _int(request, "limit", 10), agent_of(request)
        )
        return JSONResponse(result)

    def what_changed(request: Request) -> Response:
        since = request.query_params.get("since", "")
        return JSONResponse(changes.what_changed(runtime, since, agent_of(request)))

    def section(request: Request) -> Response:
        ref = request.path_params["ref"]
        return JSONResponse(context.read_section(runtime, ref, agent_of(request)))

    def task_context(request: Request) -> Response:
        result = context.get_context(
            runtime,
            request.path_params["id"],
            request.query_params.get("detail") or "task",
            _int(request, "max_chars", 24000),
            agent_of(request),
        )
        return JSONResponse(result)

    def impact_(request: Request) -> Response:
        result = impact.impact(
            runtime,
            request.query_params.get("target", ""),
            _int(request, "depth", 3),
            agent_of(request),
        )
        return JSONResponse(result)

    def explain(request: Request) -> Response:
        result = impact.explain(runtime, request.query_params.get("path", ""), agent_of(request))
        return JSONResponse(result)

    def find(request: Request) -> Response:
        result = impact.find_code(
            runtime,
            feature=_q(request, "feature"),
            domain=_q(request, "domain"),
            table=_q(request, "table"),
            spec=_q(request, "spec"),
            text=_q(request, "text"),
            agent=agent_of(request),
        )
        return JSONResponse(result)

    def preset_list(request: Request) -> Response:
        return JSONResponse(impact.presets())

    def preset_graph(request: Request) -> Response:
        return JSONResponse(impact.preset(runtime, request.path_params["name"]))

    def mermaid(request: Request) -> Response:
        # presets only, never Cypher: safe in public mode too (SPEC-07 endpoint 15)
        name = request.query_params.get("preset", "").strip()
        if not name:
            raise SddError("invalid_input", "preset is required, e.g. ?preset=schema.")
        text = exports.render_mermaid(impact.preset(runtime, name))
        return Response(text, media_type="text/plain; charset=utf-8")

    async def query(request: Request) -> Response:
        if public and runtime.settings.public_query == "presets":
            raise SddError("query_rejected", "Only the named presets run on this server.")
        data = await _body(request)
        params = data.get("params")
        if params is not None and not isinstance(params, dict):
            raise SddError("invalid_input", "params must be a JSON object.")
        result = await run_in_threadpool(
            query_guard.run_query,
            runtime,
            _str(data, "cypher") or "",
            params,
            None if public else _str(data, "agent"),
        )
        return JSONResponse(result)

    def sync(request: Request) -> Response:
        return JSONResponse(runtime.sync(full=True))

    def writer(fn: Callable[[Request, dict[str, Any]], dict[str, Any]]) -> Any:
        async def endpoint(request: Request) -> Response:
            data = await _body(request)
            return JSONResponse(await run_in_threadpool(fn, request, data))

        return endpoint

    def claim(request: Request, data: dict[str, Any]) -> dict[str, Any]:
        return coordination.claim_task(runtime, request.path_params["id"], _str(data, "agent"))

    def release(request: Request, data: dict[str, Any]) -> dict[str, Any]:
        return coordination.release_task(
            runtime,
            request.path_params["id"],
            _str(data, "agent"),
            _str(data, "reason"),
            _bool(data, "force"),
        )

    def complete(request: Request, data: dict[str, Any]) -> dict[str, Any]:
        return coordination.complete_task(
            runtime,
            request.path_params["id"],
            _str(data, "agent"),
            notes=_str(data, "notes"),
            files_touched=_strs(data, "files_touched"),
            commit=_str(data, "commit"),
        )

    def deviation(request: Request, data: dict[str, Any]) -> dict[str, Any]:
        return coordination.log_deviation(
            runtime,
            _str(data, "task_id") or "",
            _str(data, "agent"),
            title=_str(data, "title") or "",
            spec_says=_str(data, "spec_says") or "",
            implementation_does=_str(data, "implementation_does") or "",
            why=_str(data, "why") or "",
            consequences=_str(data, "consequences"),
            amends=_strs(data, "amends") or [],
            affects=_strs(data, "affects"),
            status=_str(data, "status") or "open",
        )

    def milestone_done(request: Request, data: dict[str, Any]) -> dict[str, Any]:
        return coordination.complete_milestone(
            runtime,
            request.path_params["id"],
            _str(data, "agent"),
            _str(data, "verification") or "",
        )

    async def read_only(request: Request) -> Response:
        raise SddError("read_only", "This is the read-only public demo.")

    async def sdd_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, SddError)
        return error_response(exc)

    def gated(endpoint: Any) -> Any:
        """The write routes stay registered in public mode and answer 403 ``read_only``."""
        return read_only if public else endpoint

    routes: list[Any] = [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/status", status, methods=["GET"]),
        Route("/api/graph", graph, methods=["GET"]),
        Route("/api/nodes/{id:path}", node, methods=["GET"]),
        Route("/api/board", board, methods=["GET"]),
        Route("/api/milestones", milestones, methods=["GET"]),
        Route("/api/sections/{ref:path}", section, methods=["GET"]),
        Route("/api/tasks/{id}/context", task_context, methods=["GET"]),
        Route("/api/impact", impact_, methods=["GET"]),
        Route("/api/explain", explain, methods=["GET"]),
        Route("/api/find", find, methods=["GET"]),
        Route("/api/changes", what_changed, methods=["GET"]),
        Route("/api/presets", preset_list, methods=["GET"]),
        Route("/api/presets/{name:path}", preset_graph, methods=["GET"]),
        Route("/api/mermaid", mermaid, methods=["GET"]),
        Route("/api/query", query, methods=["POST"]),
        Route("/api/events", sse.events(runtime), methods=["GET"]),
        Route("/api/tasks/{id}/claim", gated(writer(claim)), methods=["POST"]),
        Route("/api/tasks/{id}/release", gated(writer(release)), methods=["POST"]),
        Route("/api/tasks/{id}/complete", gated(writer(complete)), methods=["POST"]),
        Route("/api/deviations", gated(writer(deviation)), methods=["POST"]),
        Route("/api/milestones/{id}/complete", gated(writer(milestone_done)), methods=["POST"]),
        Route("/api/sync", gated(sync), methods=["POST"]),
        Route("/api/next", next_tasks, methods=["GET"]),
    ]
    lifespan = None
    if mcp_app is not None:
        routes += list(mcp_app.routes)

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            # the SDK's session manager runs inside the MCP sub-app's lifespan
            async with mcp_app.router.lifespan_context(mcp_app):
                yield

    # the dashboard goes last so that /api and /mcp win
    dashboard: ASGIApp = StaticFiles(directory=STATIC_DIR, html=True)
    routes.append(Mount("/", _GetOnly(dashboard) if public else dashboard, name="dashboard"))
    middleware = (
        Middleware(PublicMiddleware, settings=runtime.settings)
        if public
        else Middleware(SecurityMiddleware, settings=runtime.settings)
    )
    return Starlette(
        routes=routes,
        middleware=[middleware],
        exception_handlers={SddError: sdd_error},
        lifespan=lifespan,
    )
