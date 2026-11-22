"""SPEC-10 §4 invariant 5: in public mode no route outside the public list answers, and ``/mcp``
is absent. Built from the daemon app's route table, so a new route is covered automatically."""

from __future__ import annotations

import re

from starlette.routing import Route
from starlette.testclient import TestClient

from sdd.daemon import build_app
from sdd.service.runtime import Runtime
from sdd.web.api import create_app
from sdd.web.public import PUBLIC_PATHS


def _normal(path: str) -> str:
    return re.sub(r"\{(\w+):path\}", r"{\1}", path)


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def daemon_routes(runtime: Runtime) -> list[tuple[str, str]]:
    """``(method, path template)`` of every route of the daemon app; ``MCP`` for ``/mcp``."""
    out: list[tuple[str, str]] = []
    for route in build_app(runtime).routes:
        if not isinstance(route, Route):
            continue  # the dashboard mount
        if route.path == "/mcp":
            out.append(("MCP", "/mcp"))
            continue
        for method in sorted(route.methods or ()):
            if method not in ("HEAD", "OPTIONS"):
                out.append((method, _normal(route.path)))
    return out


def test_inv05_public_routes(runtime: Runtime, public_runtime: Runtime) -> None:
    client = TestClient(create_app(public_runtime, public=True))
    routes = daemon_routes(runtime)
    assert len(routes) >= 24
    for method, path in routes:
        if method == "MCP":
            for mcp in ("/mcp", "/mcp/"):
                assert client.get(mcp).status_code == 404, mcp
                assert client.post(mcp, json={}).status_code == 404, mcp
            continue
        if (method, path) in PUBLIC_PATHS:
            if path == "/api/events":
                continue  # an SSE stream never ends; covered by the route being public
            response = client.request(method, _fill(path), json={} if method == "POST" else None)
            body = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            code = body.get("error", {}).get("code") if isinstance(body, dict) else None
            assert code != "read_only", (method, path)
            assert response.status_code != 405, (method, path)
        else:
            response = client.request(method, _fill(path), json={})
            assert response.status_code in (403, 404), (method, path, response.status_code)
            if response.status_code == 403:
                assert response.json()["error"]["code"] == "read_only", (method, path)
    registered = set(routes)
    assert registered >= PUBLIC_PATHS, sorted(PUBLIC_PATHS - registered)
