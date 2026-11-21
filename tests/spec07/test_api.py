"""SPEC-07 §5 checks 2 (API part) and 3, and the M02 endpoints 1–4, 6 and 19 (plan M02 §8)."""

from __future__ import annotations

import asyncio
import json

from starlette.testclient import TestClient

from sdd import errors
from sdd.service import api_views
from sdd.service.runtime import Runtime
from sdd.web.api import HTTP_STATUS
from sdd.web.sse import event_stream


def _error(response: object) -> str:
    body = response.json()  # type: ignore[attr-defined]
    return str(body["error"]["code"])


def test_health_shape(app: TestClient, runtime: Runtime) -> None:
    body = app.get("/api/health").json()
    assert body["ok"] is True
    assert body["mode"] == "daemon"
    assert body["schema_version"] == 1
    assert body["instance"] == runtime.instance
    assert body["project"] == runtime.settings.project_root.name
    assert body["synced_at"] == runtime.synced_at


def test_status_matches_the_service(app: TestClient, runtime: Runtime) -> None:
    body = app.get("/api/status").json()
    assert body == api_views.status(runtime)
    assert [m["id"] for m in body["milestones"]] == ["M01", "M02"]
    assert body["milestones"][0]["total"] == 4


def test_milestones_in_order_with_counts(app: TestClient) -> None:
    body = app.get("/api/milestones").json()
    assert body == [
        {
            "id": "M01",
            "title": "Timer",
            "status": "in_progress",
            "order": "0001",
            "done": 1,
            "claimed": 0,
            "total": 4,
        },
        {
            "id": "M02",
            "title": "Ingestion",
            "status": "todo",
            "order": "0002",
            "done": 0,
            "claimed": 0,
            "total": 3,
        },
    ]


def test_node_by_percent_encoded_section_and_file_ids(app: TestClient) -> None:
    section = app.get("/api/nodes/SPEC-01%231")
    assert section.status_code == 200
    body = section.json()
    assert (body["id"], body["label"]) == ("SPEC-01#1", "Section")
    assert body["props"]["title"] == "Brewing"
    assert any(r["id"] == "SPEC-01" for r in body["relationships"]["HAS_SECTION"])

    file = app.get("/api/nodes/file%3Asrc%2Fkettle%2Fbrew.py")  # a path-keyed ID with `:` and `/`
    assert file.status_code == 200  # code files get File nodes from M04a
    assert file.json()["id"] == "file:src/kettle/brew.py"
    assert file.json()["props"]["language"] == "python"
    md = app.get("/api/nodes/file%3Adocs%2Fspecs%2FSPEC-01-timer.md")
    assert md.status_code == 200
    assert md.json()["id"] == "file:docs/specs/SPEC-01-timer.md"


def test_unknown_node_is_404_in_the_error_shape(app: TestClient) -> None:
    response = app.get("/api/nodes/SPEC-99%231")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "node_not_found"
    assert response.json()["error"]["details"] == {"id": "SPEC-99#1"}
    assert app.get("/api/nodes/nonsense").status_code == 400


def test_bad_query_parameters_are_400(app: TestClient) -> None:
    assert app.get("/api/graph?depth=0").status_code == 400
    assert app.get("/api/graph?depth=x").status_code == 400
    assert app.get("/api/graph?limit=5000").status_code == 400
    assert app.get("/api/graph?labels=Nope").status_code == 400
    assert _error(app.get("/api/graph?focus=SPEC-99%231")) == "node_not_found"


def test_graph_without_focus_lists_nodes_and_edges_among_them(app: TestClient) -> None:
    body = app.get("/api/graph").json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"SPEC-01", "SPEC-01#1", "M01", "M01.1", "D001"} <= ids
    assert all(n["label"] not in ("Event", "Meta", "Agent") for n in body["nodes"])
    assert all(e["source"] in ids and e["target"] in ids for e in body["edges"])
    assert {"source": "SPEC-01", "target": "SPEC-01#1", "type": "HAS_SECTION"} in body["edges"]
    only_tasks = app.get("/api/graph?labels=Task&limit=2").json()
    assert [n["label"] for n in only_tasks["nodes"]] == ["Task", "Task"]


def test_spec07_ac03_graph_focus_depth1(app: TestClient, runtime: Runtime) -> None:
    body = app.get("/api/graph?focus=SPEC-01%231&depth=1").json()
    got = {n["id"] for n in body["nodes"]}
    rows = runtime.store.read(
        "MATCH (a:Section {id: 'SPEC-01#1'})-[]-(b) WHERE NOT 'Event' IN labels(b) "
        "AND NOT 'Meta' IN labels(b) AND NOT 'Agent' IN labels(b) RETURN DISTINCT b.id AS id"
    )
    expected = {"SPEC-01#1"} | {r["id"] for r in rows}
    assert len(expected) > 2
    assert got == expected  # the section and exactly its direct neighbours
    assert {e["source"] for e in body["edges"]} | {e["target"] for e in body["edges"]} <= got
    # depth 2 reaches further, depth 1 does not leak the second ring
    wider = {n["id"] for n in app.get("/api/graph?focus=SPEC-01%231&depth=2").json()["nodes"]}
    assert got < wider


def test_every_error_code_has_an_http_status() -> None:
    assert set(HTTP_STATUS) == errors.CODES
    assert HTTP_STATUS["daemon_running"] == 409
    assert HTTP_STATUS["unauthorized"] == 401
    assert HTTP_STATUS["rate_limited"] == 429


def test_spec07_ac02_write_publishes_sse(app: TestClient, runtime: Runtime) -> None:
    loop = asyncio.new_event_loop()
    sub = runtime.events.subscribe(loop)
    try:
        spec = runtime.settings.project_root / "docs/specs/SPEC-01-timer.md"
        text = spec.read_text(encoding="utf-8")
        spec.write_text(text.replace("120 seconds", "125 seconds"), encoding="utf-8")
        response = app.post("/api/sync")
        assert response.status_code == 200
        assert response.json()["changed"] == ["docs/specs/SPEC-01-timer.md"]
        type_, data = loop.run_until_complete(asyncio.wait_for(sub.get(), 2))
        assert type_ == "graph_changed"
        assert "SPEC-01#3" in data["ids"]
        assert "file:docs/specs/SPEC-01-timer.md" in data["ids"]
    finally:
        sub.close()
        loop.close()


def test_event_stream_formats_server_sent_events(runtime: Runtime) -> None:
    async def go() -> tuple[dict[str, str], dict[str, str]]:
        sub = runtime.events.subscribe(asyncio.get_running_loop())
        stream = event_stream(sub)
        runtime.events.publish("task", {"id": "M01.1", "status": "done"})
        runtime.events.publish("graph_changed", {"ids": ["M01.1"], "kinds": ["Task"]})
        first = await asyncio.wait_for(anext(stream), 2)
        second = await asyncio.wait_for(anext(stream), 2)
        await stream.aclose()
        return first, second

    first, second = asyncio.run(go())
    assert first["event"] == "task"
    assert json.loads(first["data"]) == {"id": "M01.1", "status": "done"}
    assert second["event"] == "graph_changed"
    assert json.loads(second["data"])["kinds"] == ["Task"]


def test_a_slow_subscriber_is_dropped_not_blocking(runtime: Runtime) -> None:
    async def go() -> int:
        sub = runtime.events.subscribe(asyncio.get_running_loop(), maxsize=2)
        for n in range(10):  # publish never blocks, however slow the consumer
            runtime.events.publish("task", {"n": n})
        await asyncio.sleep(0.05)
        got = 0
        try:
            while True:
                await asyncio.wait_for(sub.get(), 0.2)
                got += 1
        except asyncio.QueueShutDown:
            pass
        return got

    assert asyncio.run(go()) <= 2
