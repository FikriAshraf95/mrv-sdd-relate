"""SPEC-09 §6 checks 1, 2, 3 and 8: the local daemon's bind rule, token, Host and Origin checks."""

from __future__ import annotations

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from sdd.daemon import check_bind
from sdd.errors import SddError
from sdd.service.runtime import Runtime
from sdd.web.api import create_app
from tests.conftest import FAKE_PORT, MakeRuntime, daemon_settings

TOKEN = "s3cret-token"


def _client(runtime: Runtime) -> TestClient:
    return TestClient(create_app(runtime), base_url=f"http://localhost:{FAKE_PORT}")


def _code(response: object) -> str:
    return str(response.json()["error"]["code"])  # type: ignore[attr-defined]


def test_spec09_ac01_bind_rule(make_runtime: MakeRuntime) -> None:
    base = make_runtime().settings
    outside = replace(base, in_container=False, allow_remote=False, token=None)

    check_bind("127.0.0.1", outside)  # loopback always works
    check_bind("localhost", outside)
    check_bind("::1", outside)

    with pytest.raises(SddError) as plain:  # not loopback, nothing allowed
        check_bind("0.0.0.0", outside)
    assert plain.value.code == "invalid_input"

    with pytest.raises(SddError):  # allow_remote alone is not enough outside a container
        check_bind("0.0.0.0", replace(outside, allow_remote=True))
    check_bind("0.0.0.0", replace(outside, allow_remote=True, token=TOKEN))

    in_container = replace(outside, in_container=True)
    with pytest.raises(SddError):  # inside a container the flag is still required
        check_bind("0.0.0.0", in_container)
    check_bind("0.0.0.0", replace(in_container, allow_remote=True))


def test_bind_rule_is_read_from_the_environment(make_runtime: MakeRuntime) -> None:
    root = make_runtime().settings.project_root
    settings = daemon_settings(root, SDD_ALLOW_REMOTE="1", SDD_TOKEN=TOKEN)
    assert settings.allow_remote
    assert settings.token == TOKEN


def test_spec09_ac02_token(make_runtime: MakeRuntime) -> None:
    client = _client(make_runtime(SDD_TOKEN=TOKEN))
    missing = client.get("/api/status")
    assert missing.status_code == 401
    assert _code(missing) == "unauthorized"
    assert client.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/api/health").status_code == 401  # health too
    ok = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200
    assert "milestones" in ok.json()


def test_without_a_token_no_header_is_needed(app: TestClient) -> None:
    assert app.get("/api/status").status_code == 200


def test_spec09_ac03_foreign_origin_rejected(app: TestClient) -> None:
    # the claim endpoint arrives in M03a, which extends this test; POST /api/sync is a write too
    response = app.post("/api/sync", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert _code(response) == "forbidden_origin"
    other_port = app.post("/api/sync", headers={"Origin": "http://localhost:9999"})
    assert other_port.status_code == 403
    # reads have no Origin check (the Host check covers rebinding)
    assert app.get("/api/status", headers={"Origin": "https://evil.example"}).status_code == 200


def test_spec09_ac08_host_check(app: TestClient) -> None:
    evil = app.get("/api/health", headers={"Host": "evil.example"})
    assert evil.status_code == 403
    assert _code(evil) == "forbidden_host"
    assert app.post("/api/sync", headers={"Host": "evil.example:8770"}).status_code == 403
    for host in ("127.0.0.1:8770", "localhost", "[::1]:8770"):
        assert app.get("/api/health", headers={"Host": host}).status_code == 200

    # own origin: Host and Origin agree, so the write goes through
    ok = app.post(
        "/api/sync", headers={"Host": "localhost:8770", "Origin": "http://localhost:8770"}
    )
    assert ok.status_code == 200
    # the Compose port mapping: a loopback Host on another port, with the matching Origin
    mapped = app.post(
        "/api/sync", headers={"Host": "127.0.0.1:18770", "Origin": "http://127.0.0.1:18770"}
    )
    assert mapped.status_code == 200


def test_allowed_hosts_extend_the_loopback_list(make_runtime: MakeRuntime) -> None:
    client = _client(make_runtime(SDD_ALLOWED_HOSTS="sdd.lan, other.lan"))
    assert client.get("/api/health", headers={"Host": "sdd.lan:8770"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "OTHER.lan"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403


def test_token_never_appears_in_errors(make_runtime: MakeRuntime) -> None:
    client = _client(make_runtime(SDD_TOKEN=TOKEN))
    response = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}x"})
    assert TOKEN not in response.text
