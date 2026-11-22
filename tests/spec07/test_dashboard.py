"""SPEC-07 §5 checks 5, 6 and 7 (deep-link part), and the static smoke test (SPEC-10 §6).

No JavaScript runtime exists in the dev container (no build step, no Node), so the browser-side
behaviour of checks 5 and 7 is exercised by the milestone walkthrough; these tests pin what can be
checked from Python: what is served, what the files reference and the API calls deep links make.
"""

from __future__ import annotations

import re

from starlette.testclient import TestClient

from sdd.graph import schema
from sdd.web.api import STATIC_DIR, create_app
from tests.conftest import FAKE_PORT, MakeRuntime

_OWN = {
    "index.html",
    "style.css",
    "app.js",
    "api.js",
    "dom.js",
    "board.js",
    "graph.js",
    "query.js",
    "cystyle.js",
    "impact.js",
    "explain.js",
    "presets.js",
}


def _all_files() -> list[str]:
    return sorted(
        p.relative_to(STATIC_DIR).as_posix() for p in STATIC_DIR.rglob("*") if p.is_file()
    )


def _own_text() -> dict[str, str]:
    """Every dashboard file except the vendored library."""
    return {
        name: (STATIC_DIR / name).read_text(encoding="utf-8")
        for name in _all_files()
        if not name.startswith("vendor/") and name.endswith((".html", ".css", ".js", ".svg"))
    }


def test_dashboard_files_are_all_served(app: TestClient) -> None:
    files = _all_files()
    assert set(files) >= _OWN
    assert "vendor/cytoscape.min.js" in files
    assert "vendor/LICENSE-cytoscape.txt" in files
    index = app.get("/")
    assert index.status_code == 200
    assert "text/html" in index.headers["content-type"]
    for name in files:
        assert app.get(f"/{name}").status_code == 200, name
    # the API and the dashboard do not shadow each other
    assert app.get("/api/health").json()["ok"] is True
    assert app.get("/api/nope").status_code == 404
    assert app.get("/../pyproject.toml").status_code == 404


def test_every_asset_the_page_references_is_served(app: TestClient) -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    refs = re.findall(r'(?:src|href)="([^"]*)"', html)
    assert {"style.css", "app.js", "vendor/cytoscape.min.js", "favicon.svg"} <= set(refs)
    for ref in refs:
        assert app.get(f"/{ref}").status_code == 200, ref
    imports = re.findall(r'from "\./([^"]+)"', "".join(_own_text().values()))
    assert imports
    for ref in imports:
        assert app.get(f"/{ref}").status_code == 200, ref


def test_spec07_ac06_no_request_outside_the_own_origin() -> None:
    for name, text in _own_text().items():
        if name == "favicon.svg":  # the SVG namespace is an identifier, not a request
            assert "href=" not in text
            continue
        assert not re.search(r"https?://|(?<![:\w])//[a-z]", text), name
        assert "@import" not in text, name
        for url in re.findall(r"url\(\s*['\"]?([^'\")]+)", text):
            assert not re.match(r"^(?:[a-z]+:)?//|^data:", url), (name, url)
    for ref in re.findall(
        r'(?:src|href)="([^"]*)"', (STATIC_DIR / "index.html").read_text("utf-8")
    ):
        assert not re.match(r"^(?:[a-z]+:)?//|^data:", ref), ref
    # the only network calls are in api.js and all go to /api/...
    api = _own_text()["api.js"]
    targets = re.findall(r"(?:request|fetch|EventSource)\(\s*[`\"']([^`\"']+)", api)
    assert len(targets) >= 8
    assert all(t.startswith("/api/") or t == "examples.json" for t in targets), targets
    # the static demo's backend (M08) and its WASM worker read their own files by relative URL
    adapters = {"api.js", "static.js", "relate-worker.js"}
    for name in ("static.js", "relate-worker.js"):
        for ref in re.findall(r"fetch\(\s*(?:new URL\(\s*)?[`\"']([^`\"']+)", _own_text()[name]):
            assert not re.match(r"^(?:[a-z]+:)?//|^/", ref), (name, ref)
    for name, text in _own_text().items():
        if name.endswith(".js") and name not in adapters:
            assert not re.search(
                r"\b(?:fetch|XMLHttpRequest|EventSource|WebSocket|sendBeacon)\b", text
            ), name


def test_dashboard_is_ready_for_the_public_csp() -> None:
    # SPEC-09 §4 sets `default-src 'self'` for public mode: no inline style, script or data: URL
    for name, text in _own_text().items():
        assert "innerHTML" not in text, name
        assert "outerHTML" not in text, name
        assert "insertAdjacentHTML" not in text, name
        assert 'style="' not in text, name
        assert "style='" not in text, name
        assert 'setAttribute("style"' not in text, name
        assert not re.search(r"data:[a-z]+/", text), name  # a data: URL, not an object key
    html = _own_text()["index.html"]
    assert not re.search(r"<script(?![^>]*\ssrc=)", html)
    assert not re.search(r"\son[a-z]+=", html)


def test_spec07_ac05_board_has_a_polling_fallback() -> None:
    # The fallback itself is browser behaviour (walkthrough: abort /api/events, watch a card move).
    # Pinned here: the stream reports its state, an error means polling, and a retry storm of
    # EventSource errors must not restart the poll timer (the bug the walkthrough found).
    api = _own_text()["api.js"]
    assert re.search(r"onerror\s*=\s*\(\)\s*=>\s*onState\(false\)", api)
    assert "typeof EventSource" in api
    board = _own_text()["board.js"]
    assert re.search(r"setInterval\(\s*refresh\s*,\s*POLL_MS\s*\)", board)
    assert re.search(r"POLL_MS\s*=\s*5000", board)
    assert re.search(r"if \(on === live && started\) return", board)
    assert "api.board(" in board


def test_spec07_ac07_deep_link_targets_resolve_encoded(app: TestClient) -> None:
    # `#graph/<encoded id>` and `#impact/<encoded id>` hand the decoded ID to these calls
    node = app.get("/api/nodes/SPEC-01%231").json()
    assert node["id"] == "SPEC-01#1"
    focus = app.get("/api/graph?focus=SPEC-01%231&depth=1").json()
    assert "SPEC-01#1" in {n["id"] for n in focus["nodes"]}
    file = app.get("/api/nodes/file%3Asrc%2Fkettle%2Fbrew.py")
    assert file.status_code == 200
    assert file.json()["id"] == "file:src/kettle/brew.py"
    # the router decodes what it reads and encodes what it writes; the adapter encodes every ID
    router = _own_text()["app.js"]
    assert "decodeURIComponent(arg)" in router
    assert "encodeURIComponent(arg)" in router
    api = _own_text()["api.js"]
    assert "/api/nodes/${enc(id)}" in api
    assert "const enc = encodeURIComponent" in api


def test_graph_labels_offered_match_the_schema() -> None:
    dom = _own_text()["dom.js"]
    block = re.search(r"const KNOWN = \[(.*?)\];", dom, re.S)
    assert block
    offered = set(re.findall(r'"(\w+)"', block.group(1)))
    assert offered == set(schema.LABELS) - {"Event", "Meta"}
    css = _own_text()["style.css"]
    for label in offered:
        assert f"--l-{label}:" in css, label


def test_spec09_ac02_dashboard_static_files_need_no_token(make_runtime: MakeRuntime) -> None:
    # SPEC-09 §6 check 2: under SDD_TOKEN the shell and its files load, the data does not
    client = TestClient(
        create_app(make_runtime(SDD_TOKEN="s3cret-token")), base_url=f"http://localhost:{FAKE_PORT}"
    )
    assert client.get("/").status_code == 200
    for name in _all_files():
        assert client.get(f"/{name}").status_code == 200, name
    assert client.get("/api/board").status_code == 401
    assert client.get("/api/presets").status_code == 401
    ok = client.get("/api/board", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 200


def test_dashboard_sends_the_token_as_a_header_only() -> None:
    # Browser behaviour (the password field, "Forget token") is walked through by hand; pinned here:
    api = _own_text()["api.js"]
    assert "sessionStorage" in api
    assert re.search(r"Authorization:\s*`Bearer \$\{token\}`", api)
    assert re.search(r"if \(res\.status === 401\)", api)
    # every storage access sits in a try/catch, and the token never goes into a URL or cookie
    assert api.count("try {") >= 2
    assert "document.cookie" not in "".join(_own_text().values())
    assert not re.search(r"[?&]token=|\$\{token\}`\s*\)", api.replace("Bearer ${token}", ""))
    # with a token EventSource is skipped, so the Board polls
    assert re.search(r'typeof EventSource === "undefined" \|\| getToken\(\)', api)
    app = _own_text()["app.js"]
    assert "onUnauthorized(" in app
    assert 'type: "password"' in app
    assert "Forget token" in _own_text()["index.html"]


def test_dashboard_needs_no_inline_style_under_the_public_csp() -> None:
    """SPEC-09 §4 `default-src 'self'`: Cytoscape injects an inline <style> unless an element
    with this id exists, so the stylesheet link carries it and style.css holds the rule."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="__________cytoscape_stylesheet"' in html
    assert "<style" not in html
    assert " style=" not in html
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert ".__________cytoscape_container" in css
