"""SPEC-07 §5 checks 5, 6 and 7 (deep-link part), and the static smoke test (SPEC-10 §6)."""

from __future__ import annotations

import re

from starlette.testclient import TestClient

from sdd.web.api import STATIC_DIR

_OWN = {"index.html", "style.css", "app.js", "api.js", "dom.js", "board.js", "graph.js", "query.js"}


def _own_files() -> list[str]:
    return sorted(p.name for p in STATIC_DIR.iterdir() if p.is_file())


def test_dashboard_files_are_all_served(app: TestClient) -> None:
    assert set(_own_files()) >= _OWN
    index = app.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    for name in _own_files():
        assert app.get(f"/{name}").status_code == 200, name
    assert app.get("/vendor/cytoscape.min.js").status_code == 200
    # the API and the dashboard do not shadow each other
    assert app.get("/api/health").json()["ok"] is True
    assert app.get("/api/nope").status_code == 404


def test_spec07_ac06_no_request_outside_the_own_origin() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]*)"', html)
    assert refs
    for ref in refs:
        assert not re.match(r"^(?:[a-z]+:)?//", ref) or ref.startswith("data:"), ref
    for name in _own_files():
        if name == "index.html":
            continue
        text = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://|(?<![:\w])//[a-z]", text), name
        assert "@import" not in text, name
    for path in STATIC_DIR.glob("*.js"):
        # every fetch goes to a relative /api path
        for target in re.findall(
            r"(?:fetch|EventSource)\(\s*[`\"']([^`\"']+)", path.read_text("utf-8")
        ):
            assert target.startswith("/api/") or target == "/api/events", (path.name, target)


def test_spec07_ac05_board_polls_when_the_stream_is_down() -> None:
    # The fallback is browser behaviour; this pins the wiring (the walkthrough exercises it live).
    board = (STATIC_DIR / "board.js").read_text(encoding="utf-8")
    assert "POLL_MS = 5000" in board
    assert "setInterval(refresh, POLL_MS)" in board
    assert "api.board(" in board
    api = (STATIC_DIR / "api.js").read_text(encoding="utf-8")
    assert "es.onerror = () => onState(false)" in api


def test_spec07_ac07_deep_link_targets_resolve_encoded(app: TestClient) -> None:
    # `#impact/<encoded id>` and `#graph/<encoded id>` hand the decoded ID to these calls
    assert app.get("/api/nodes/SPEC-01%231").json()["id"] == "SPEC-01#1"
    assert app.get("/api/graph?focus=SPEC-01%231&depth=1").status_code == 200
    router = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "decodeURIComponent(arg)" in router
    assert "encodeURIComponent(arg)" in router
