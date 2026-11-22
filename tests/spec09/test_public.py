"""SPEC-09 §4 and §6 check 7, SPEC-07 §5 check 1, SPEC-11 §9 check 3: ``sdd public``.

The public app runs on a store opened ``read_only`` (the ``public_app`` fixture), without any
network: ``TestClient`` calls the ASGI app in-process.
"""

from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import replace
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from sdd import config
from sdd.errors import SddError
from sdd.public import project_for
from sdd.service import follow as follow_module
from sdd.service.follow import Follower
from sdd.service.runtime import Runtime
from sdd.web.api import create_app
from sdd.web.public import PUBLIC_PATHS, RATE_QUERY, PublicMiddleware, RateLimiter, client_ip
from tests.conftest import MakePublic, MakeRuntime, wait_for
from tests.spec_tables import spec07_endpoints

HEADERS = {
    "content-security-policy": "default-src 'self'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


def _code(response: object) -> str:
    return str(response.json()["error"]["code"])  # type: ignore[attr-defined]


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_spec09_ac07_public_mcp_404_writes_403(public_app: TestClient) -> None:
    for path in ("/mcp", "/mcp/"):
        assert public_app.post(path, json={}).status_code == 404
        assert public_app.get(path).status_code == 404
    writes = [
        "/api/tasks/M01.1/claim",
        "/api/tasks/M01.1/release",
        "/api/tasks/M01.1/complete",
        "/api/deviations",
        "/api/milestones/M01/complete",
        "/api/sync",
    ]
    for path in writes:
        response = public_app.post(path, json={"agent": "evil"})
        assert response.status_code == 403, path
        assert _code(response) == "read_only", path


def test_spec07_ac01_public_write_endpoints_read_only(public_app: TestClient) -> None:
    rows = spec07_endpoints()
    writes = [e for e in rows if not e.public and e.method == "POST"]
    assert len(writes) == 6  # endpoints 17 (3), 18 (2) and 19
    for endpoint in writes:
        response = public_app.post(_fill(endpoint.path), json={})
        assert response.status_code == 403, endpoint
        assert _code(response) == "read_only", endpoint
    assert public_app.get("/mcp").status_code == 404


def test_public_reads_answer_and_the_store_stays_read_only(
    public_app: TestClient, public_runtime: Runtime
) -> None:
    health = public_app.get("/api/health").json()
    assert health["mode"] == "public"
    assert health["base_url"] is None
    assert public_runtime.store.read_only
    assert public_app.get("/api/board").status_code == 200
    with pytest.raises(SddError) as err:
        public_runtime.store.write(lambda tx: tx.run("CREATE (:Probe {id: 'x'})"))
    assert err.value.code == "read_only"


def test_every_public_get_endpoint_answers_without_5xx(public_app: TestClient) -> None:
    targets = {
        "/api/nodes/{id}": "M01",
        "/api/sections/{ref}": "SPEC-01 §1",
        "/api/tasks/{id}/context": "M01.1",
        "/api/presets/{name}": "schema",
    }
    count = 0
    for method, template in sorted(PUBLIC_PATHS):
        if method != "GET" or template == "/api/events":  # an SSE stream never ends
            continue
        path = template
        for key, value in targets.items():
            if template == key:
                path = template.replace(re.search(r"\{[^}]+\}", template).group(0), value)  # type: ignore[union-attr]
        path = _fill(path)
        for query in ("", "?agent=evil", "?agent=evil&since=last_session", "?target=x&path=x"):
            response = public_app.get(path + query)
            assert response.status_code < 500, (path + query, response.text)
            count += 1
    assert count >= 40
    # `agent` is ignored: nothing was written, so no Agent node exists
    rows = public_app.post("/api/query", json={"cypher": "MATCH (a:Agent) RETURN a.name"}).json()
    assert rows["rows"] == []


def test_query_still_runs_through_the_guard(public_app: TestClient) -> None:
    ok = public_app.post("/api/query", json={"cypher": "MATCH (t:Task) RETURN t.id LIMIT 3"})
    assert ok.status_code == 200
    bad = public_app.post("/api/query", json={"cypher": "MATCH (n) DETACH DELETE n"})
    assert bad.status_code == 400
    assert _code(bad) == "query_rejected"


def test_presets_only_mode_rejects_query_but_runs_presets(make_public: MakePublic) -> None:
    client = TestClient(create_app(make_public(SDD_PUBLIC_QUERY="presets"), public=True))
    response = client.post("/api/query", json={"cypher": "MATCH (t:Task) RETURN t.id"})
    assert response.status_code == 400
    assert _code(response) == "query_rejected"
    assert "presets" in response.json()["error"]["message"]
    assert client.get("/api/health").json()["public_query"] == "presets"
    assert client.get("/api/presets/schema").status_code == 200


def test_security_headers_on_every_response(public_app: TestClient) -> None:
    for path in ("/", "/api/health", "/api/nope", "/style.css", "/api/tasks/M01.1/claim"):
        response = public_app.post(path) if path.endswith("claim") else public_app.get(path)
        for name, value in HEADERS.items():
            assert response.headers.get(name) == value, (path, name)


def test_unhandled_errors_leak_no_trace_or_path(public_runtime: Runtime) -> None:
    async def boom(request: Request) -> Response:
        raise RuntimeError("secret /workspace/internal/path")

    app = create_app(public_runtime, public=True)
    app.router.routes.insert(0, Route("/boom", boom, methods=["GET"]))
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert "/" not in response.text.replace("Internal Server Error", "")
    assert "secret" not in response.text
    assert response.headers["x-frame-options"] == "DENY"


def test_public_app_refuses_mcp_mounting(public_runtime: Runtime) -> None:
    with pytest.raises(ValueError, match="never mounts /mcp"):
        create_app(public_runtime, mcp_app=Starlette(), public=True)


def test_no_host_token_or_origin_checks_in_public_mode(make_public: MakePublic) -> None:
    client = TestClient(create_app(make_public(SDD_TOKEN="tok"), public=True))
    response = client.get(
        "/api/health", headers={"Host": "demo.example.com", "Origin": "https://evil.example"}
    )
    assert response.status_code == 200


# ---------------------------------------------------------------- rate limit and client IP


def test_rate_limit_query_429_with_retry_after(public_app: TestClient) -> None:
    body = {"cypher": "MATCH (t:Task) RETURN t.id LIMIT 1"}
    for _ in range(RATE_QUERY):
        assert public_app.post("/api/query", json=body).status_code == 200
    blocked = public_app.post("/api/query", json=body)
    assert blocked.status_code == 429
    assert _code(blocked) == "rate_limited"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60
    assert blocked.headers["x-frame-options"] == "DENY"
    assert public_app.get("/api/health").status_code == 200  # the other bucket is separate


def test_rate_limiter_window_and_pruning() -> None:
    now = [100.0]
    limiter = RateLimiter(window=60.0, clock=lambda: now[0])
    assert [limiter.hit("a", "q", 2) for _ in range(2)] == [None, None]
    assert limiter.hit("a", "q", 2) == 60
    assert limiter.hit("b", "q", 2) is None  # another client
    now[0] = 130.0
    assert limiter.hit("a", "q", 2) == 30
    now[0] = 161.0
    assert limiter.hit("a", "q", 2) is None  # the old hits left the window
    now[0] = 500.0
    limiter.hit("c", "q", 2)
    assert set(limiter._hits) == {("c", "q")}  # empty buckets are dropped


def _scope(host: str | None, **headers: str) -> dict[str, object]:
    return {
        "type": "http",
        "client": (host, 1234) if host else None,
        "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()],
    }


def test_client_ip_trusts_proxy_headers_only_inside_the_network() -> None:
    net = ipaddress.ip_network("10.0.0.0/8")
    inside = _scope(
        "10.1.2.3", cf_connecting_ip="203.0.113.7", x_forwarded_for="198.51.100.1, 10.0.0.1"
    )
    assert client_ip(inside, net) == "203.0.113.7"  # type: ignore[arg-type]
    xff = _scope("10.1.2.3", x_forwarded_for="198.51.100.1, 10.0.0.1")
    assert client_ip(xff, net) == "198.51.100.1"  # type: ignore[arg-type]
    outside = _scope("192.168.1.9", cf_connecting_ip="203.0.113.7", x_forwarded_for="198.51.100.1")
    assert client_ip(outside, net) == "192.168.1.9"  # type: ignore[arg-type]
    junk = _scope("10.1.2.3", cf_connecting_ip="not-an-ip")
    assert client_ip(junk, net) == "10.1.2.3"  # type: ignore[arg-type]
    assert client_ip(inside, None) == "10.1.2.3"  # type: ignore[arg-type]
    assert client_ip(_scope(None), net) == "unknown"  # type: ignore[arg-type]
    assert client_ip(_scope("testclient", cf_connecting_ip="1.2.3.4"), net) == "testclient"  # type: ignore[arg-type]


def test_rate_limit_counts_per_forwarded_ip_only_from_the_trusted_net(
    public_runtime: Runtime,
) -> None:
    settings = replace(public_runtime.settings, trusted_proxy_net="10.0.0.0/8")

    async def ok(request: Request) -> Response:
        return Response("ok")

    inner = Starlette(routes=[Route("/api/query", ok, methods=["POST"])])
    limiter = RateLimiter()
    wrapped = PublicMiddleware(inner, settings, limiter)
    import asyncio  # noqa: PLC0415

    async def call(host: str, **headers: str) -> int:
        status = 0
        messages: list[dict[str, object]] = []
        scope = {
            **_scope(host, **headers),
            "method": "POST",
            "path": "/api/query",
            "query_string": b"",
            "root_path": "",
            "scheme": "http",
            "http_version": "1.1",
            "server": ("x", 80),
        }

        async def receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        await wrapped(scope, receive, send)  # type: ignore[arg-type]
        for m in messages:
            if m["type"] == "http.response.start":
                status = int(m["status"])  # type: ignore[call-overload]
        return status

    async def scenario() -> tuple[int, int, int]:
        for _ in range(RATE_QUERY):  # one forwarded client fills its bucket, via the proxy
            await call("10.0.0.2", cf_connecting_ip="203.0.113.7")
        proxied = await call("10.0.0.2", cf_connecting_ip="203.0.113.7")
        other = await call("10.0.0.2", cf_connecting_ip="203.0.113.8")
        # from outside the network the header cannot pick the bucket: same socket, same bucket
        for _ in range(RATE_QUERY):
            await call("192.168.1.9", cf_connecting_ip="203.0.113.50")
        spoofed = await call("192.168.1.9", cf_connecting_ip="203.0.113.51")
        return proxied, other, spoofed

    proxied, other, spoofed = asyncio.run(scenario())
    assert (proxied, other, spoofed) == (429, 200, 429)


# ---------------------------------------------------------------- project_for and the follower


def test_project_for_infers_from_the_store_path(tmp_path: Path) -> None:
    store = tmp_path / "run" / ".sdd" / "graph"
    assert project_for(store, None) == (tmp_path / "run").resolve()
    assert project_for(store, tmp_path / "other") == tmp_path / "other"
    with pytest.raises(SddError) as err:
        project_for(tmp_path / "somewhere" / "graph", None)
    assert err.value.code == "invalid_input"


def test_public_bind_rule_is_the_daemons(make_public: MakePublic) -> None:
    from sdd.public import prepare  # noqa: PLC0415

    settings = make_public().settings
    outside = replace(settings, in_container=False, allow_remote=False, token=None)
    with pytest.raises(SddError):
        prepare(outside, "0.0.0.0")
    runtime = prepare(replace(outside, allow_remote=True, in_container=True), "0.0.0.0")
    try:
        assert runtime.mode == "public"
    finally:
        runtime.close()


def test_spec11_ac03_public_follows_writer_within_2s(
    make_runtime: MakeRuntime, make_public: MakePublic
) -> None:
    from sdd.service import coordination  # noqa: PLC0415

    writer = make_runtime()
    writer.store.checkpoint()
    settings = config.load(writer.settings.project_root, None, env={"SDD_WATCH": "poll"})
    public = Runtime.open_public(settings)
    client = TestClient(create_app(public, public=True))
    follower = Follower(public, interval=0.05, close_delay=0.05)
    published: list[tuple[str, dict[str, object]]] = []
    import asyncio  # noqa: PLC0415

    loop = asyncio.new_event_loop()
    sub = public.events.subscribe(loop)
    follower.start()
    try:
        assert client.get("/api/health").json()["mode"] == "public"
        board = client.get("/api/board").json()
        todo = board["columns"]["todo"]
        assert todo
        task = todo[0]["id"]
        coordination.claim_task(writer, task, "sonnet-1")
        writer.store.checkpoint()

        def claimed() -> bool:
            cols = client.get("/api/board").json()["columns"]
            return any(c["id"] == task for c in cols["claimed"])

        started = time.monotonic()
        assert wait_for(claimed, timeout=2.0)
        assert time.monotonic() - started <= 2.0
        for _ in range(3):  # drain what the loop received
            try:
                published.append(loop.run_until_complete(asyncio.wait_for(sub.get(), 0.5)))
            except TimeoutError:
                break
        types = [t for t, _ in published]
        assert "task" in types
        event = next(d for t, d in published if t == "task")
        assert event["id"] == task
        assert event["claimed_by"] == "sonnet-1"
        assert "graph_changed" in types
    finally:
        follower.stop()
        sub.close()
        loop.close()


def test_follower_survives_a_missing_manifest_and_a_failed_open(
    make_runtime: MakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = make_runtime()
    writer.store.checkpoint()
    settings = config.load(writer.settings.project_root, None, env={})
    public = Runtime.open_public(settings)
    follower = Follower(public, interval=0.05, close_delay=0.01)
    try:
        kept = public.store
        # no manifest (the writer has not flushed yet, or it is being swapped): keep waiting
        moved = follower.manifest.with_name("manifest.moved")
        follower.manifest.rename(moved)
        assert follower.check() is False
        assert public.store is kept
        moved.rename(follower.manifest)
        # a manifest change whose open fails: keep the old store, try again at the next check
        real_open = follow_module.Store.open

        def failing(*args: object, **kwargs: object) -> object:
            raise SddError("invalid_input", "no store here (simulated)")

        monkeypatch.setattr(follow_module.Store, "open", failing)
        follower._seen = None
        assert follower.check() is False
        assert public.store is kept
        # the next check succeeds and swaps
        monkeypatch.setattr(follow_module.Store, "open", real_open)
        assert follower.check() is True
        assert public.store is not kept
        assert public.store.read("MATCH (m:Milestone) RETURN count(m) AS n")[0]["n"] >= 1
        assert follower.check() is False  # unchanged manifest: nothing to do
    finally:
        follower.stop()
