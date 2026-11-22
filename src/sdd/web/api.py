"""The JSON API (SPEC-07 §2): endpoints 1–14, 16–19 and 21, and ``/mcp``.

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
from typing import Any

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from sdd.errors import SddError
from sdd.service import api_views, changes, context, coordination, impact, query_guard
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


def create_app(runtime: Runtime, *, mcp_app: Starlette | None = None) -> Starlette:
    def health(request: Request) -> Response:
        return JSONResponse(api_views.health(runtime))

    def status(request: Request) -> Response:
        return JSONResponse(api_views.status(runtime, _q(request, "agent")))

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
            runtime, _q(request, "milestone"), _int(request, "limit", 10), _q(request, "agent")
        )
        return JSONResponse(result)

    def what_changed(request: Request) -> Response:
        since = request.query_params.get("since", "")
        return JSONResponse(changes.what_changed(runtime, since, _q(request, "agent")))

    def section(request: Request) -> Response:
        ref = request.path_params["ref"]
        return JSONResponse(context.read_section(runtime, ref, _q(request, "agent")))

    def task_context(request: Request) -> Response:
        result = context.get_context(
            runtime,
            request.path_params["id"],
            request.query_params.get("detail") or "task",
            _int(request, "max_chars", 24000),
            _q(request, "agent"),
        )
        return JSONResponse(result)

    def impact_(request: Request) -> Response:
        result = impact.impact(
            runtime,
            request.query_params.get("target", ""),
            _int(request, "depth", 3),
            _q(request, "agent"),
        )
        return JSONResponse(result)

    def explain(request: Request) -> Response:
        result = impact.explain(runtime, request.query_params.get("path", ""), _q(request, "agent"))
        return JSONResponse(result)

    def find(request: Request) -> Response:
        result = impact.find_code(
            runtime,
            feature=_q(request, "feature"),
            domain=_q(request, "domain"),
            table=_q(request, "table"),
            spec=_q(request, "spec"),
            text=_q(request, "text"),
            agent=_q(request, "agent"),
        )
        return JSONResponse(result)

    def preset_list(request: Request) -> Response:
        return JSONResponse(impact.presets())

    def preset_graph(request: Request) -> Response:
        return JSONResponse(impact.preset(runtime, request.path_params["name"]))

    async def query(request: Request) -> Response:
        data = await _body(request)
        params = data.get("params")
        if params is not None and not isinstance(params, dict):
            raise SddError("invalid_input", "params must be a JSON object.")
        result = await run_in_threadpool(
            query_guard.run_query,
            runtime,
            _str(data, "cypher") or "",
            params,
            _str(data, "agent"),
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

    async def sdd_error(request: Request, exc: Exception) -> Response:
        assert isinstance(exc, SddError)
        return error_response(exc)

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
        Route("/api/query", query, methods=["POST"]),
        Route("/api/events", sse.events(runtime), methods=["GET"]),
        Route("/api/tasks/{id}/claim", writer(claim), methods=["POST"]),
        Route("/api/tasks/{id}/release", writer(release), methods=["POST"]),
        Route("/api/tasks/{id}/complete", writer(complete), methods=["POST"]),
        Route("/api/deviations", writer(deviation), methods=["POST"]),
        Route("/api/milestones/{id}/complete", writer(milestone_done), methods=["POST"]),
        Route("/api/sync", sync, methods=["POST"]),
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

    return Starlette(
        routes=routes,
        middleware=[Middleware(SecurityMiddleware, settings=runtime.settings)],
        exception_handlers={SddError: sdd_error},
        lifespan=lifespan,
    )
