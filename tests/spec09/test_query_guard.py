"""SPEC-09 §3 the query guard (checks 4, 5, 6 and 9)."""

from __future__ import annotations

import dataclasses
import time

import pytest
from starlette.testclient import TestClient

from sdd.errors import SddError
from sdd.service import query_guard
from sdd.service.runtime import Runtime
from sdd.web.api import create_app
from tests.conftest import FAKE_PORT, wait_for

# About a second of engine work on the test host: long enough to outlast a short limit.
SLOW = "UNWIND range(1, 2000000) AS x WITH x WHERE x % 7 = 0 RETURN count(x) AS n"


def _code(fn: object, *args: object) -> str:
    with pytest.raises(SddError) as err:
        fn(*args)  # type: ignore[operator]
    return err.value.code


def _counts(runtime: Runtime) -> tuple[int, int]:
    nodes = runtime.store.read("MATCH (n) RETURN count(n) AS n")[0]["n"]
    rels = runtime.store.read("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    return int(nodes), int(rels)


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) DETACH DELETE n",
        "CREATE (:X)",
        "MATCH (n) SET n.x = 1",
        "CALL db.labels()",
        "MATCH (n) RETURN n; MATCH (m) RETURN m",
    ],
)
def test_spec09_ac04_guard_rejects_writes(cypher: str) -> None:
    assert _code(query_guard.check, cypher) == "query_rejected"


def test_spec09_ac04_guard_accepts_a_read(runtime: Runtime) -> None:
    query_guard.check("MATCH (n:Task) RETURN n.id LIMIT 5")
    result = query_guard.run_query(runtime, "MATCH (n:Task) RETURN n.id LIMIT 5")
    assert result["columns"] == ["n.id"]
    assert sorted(r[0] for r in result["rows"]) == ["M01.1", "M01.2", "M01.3", "M01.4"]
    assert result["truncated"] is False
    assert result["synced_at"]


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) WHERE n.title = 'CREATE (:X)' RETURN n.id",  # in a string
        'MATCH (n) WHERE n.title = "a;b" RETURN n.id',
        "MATCH (n) RETURN n.id // DELETE n",  # in a comment
        "MATCH (n) /* SET n.x = 1 */ RETURN n.id",
        "MATCH (n) RETURN n.`set` AS s",  # a backticked name
        "MATCH (n) RETURN n.set, $create",  # a property and a parameter
        "MATCH (n) RETURN count(*) AS n;",  # one trailing semicolon
        "RETURN [x IN range(1, 3) | x * 2] AS xs",
        "MATCH (a)-[*2]->(b) RETURN count(*) AS n",
        "MATCH (a)-[:LINKS_TO*1..3]->(b) RETURN count(*) AS n",
        "MATCH (a)<-[r:HAS_SECTION *..4]-(b) RETURN count(r) AS n",
    ],
)
def test_guard_accepts_reads_that_look_like_writes(cypher: str) -> None:
    query_guard.check(cypher)


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH p=(a)-[*]->(b) RETURN p",
        "MATCH p=(a)-[*2..]->(b) RETURN p",
        "MATCH p=(a)-[*..5]->(b) RETURN p",
        "MATCH p=(a)-[*5]->(b) RETURN p",
        "MATCH p=(a)<-[:X*]-(b) RETURN p",
        "MATCH p=shortestPath((a)-[*]-(b)) RETURN p",
    ],
)
def test_spec09_ac09_unbounded_variable_length_rejected(cypher: str) -> None:
    assert _code(query_guard.check, cypher) == "query_rejected"


def test_spec09_ac09_bounded_variable_length_accepted(runtime: Runtime) -> None:
    result = query_guard.run_query(runtime, "MATCH p=(a)-[*..4]->(b) RETURN p LIMIT 5")
    assert result["columns"] == ["p"]
    assert len(result["rows"]) == 5


def test_spec09_ac05_rollback_alone_keeps_the_store_unchanged(runtime: Runtime) -> None:
    before = _counts(runtime)
    # the writes do run inside the transaction (O11) ...
    created = "CREATE (:Task {id: 'M09.1', title: 'injected'}) RETURN 1 AS ok"
    assert query_guard.run_query(runtime, created, tokens_checked=False)["rows"] == [[1]]
    deleted = "MATCH (n) DETACH DELETE n RETURN count(*) AS n"
    assert query_guard.run_query(runtime, deleted, tokens_checked=False)["rows"][0][0] > 0
    changed = "MATCH (t:Task {id: 'M01.1'}) SET t.title = 'changed' RETURN t.title AS title"
    assert query_guard.run_query(runtime, changed, tokens_checked=False)["rows"] == [["changed"]]
    # ... and none of them lands
    assert _counts(runtime) == before
    title = runtime.store.read("MATCH (t:Task {id: 'M01.1'}) RETURN t.title AS t")[0]["t"]
    assert title == "Brew model with default steep times (SPEC-01 §1)"


def test_row_cap_and_params(runtime: Runtime) -> None:
    result = query_guard.run_query(runtime, "UNWIND range(1, 500) AS x RETURN x")
    assert len(result["rows"]) == query_guard.MAX_ROWS
    assert result["truncated"] is True
    found = query_guard.run_query(
        runtime, "MATCH (t:Task {id: $id}) RETURN t.status AS s", {"id": "M01.4"}
    )
    assert found["rows"] == [["done"]]
    assert _code(query_guard.run_query, runtime, "RETURN 1", ["x"]) == "invalid_input"
    assert _code(query_guard.run_query, runtime, "MATCH (n RETURN n") == "invalid_input"
    assert _code(query_guard.run_query, runtime, "   ") == "invalid_input"


def test_spec09_ac06_slow_query_times_out_and_server_stays_responsive(runtime: Runtime) -> None:
    runtime.settings = dataclasses.replace(runtime.settings, query_timeout=0.3)
    client = TestClient(create_app(runtime), base_url=f"http://localhost:{FAKE_PORT}")
    started = time.monotonic()
    slow = client.post("/api/query", json={"cypher": SLOW})
    assert slow.status_code == 503
    assert slow.json()["error"]["code"] == "query_timeout"
    assert slow.json()["error"]["retryable"] is True
    assert time.monotonic() - started < 1.0
    # the store and the API still answer while the abandoned query runs on
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/health").status_code == 200
    # one guarded query at a time: the next one waits, then times out too
    if runtime.query_gate.locked():
        busy = client.post("/api/query", json={"cypher": "RETURN 1 AS one"})
        assert busy.json()["error"]["code"] == "query_timeout"
    assert wait_for(lambda: not runtime.query_gate.locked(), timeout=30)
    ok = client.post("/api/query", json={"cypher": "RETURN 1 AS one"})
    assert ok.status_code == 200
    assert ok.json()["rows"] == [[1]]
