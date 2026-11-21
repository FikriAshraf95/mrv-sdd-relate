"""SPEC-01 §4 Relate access layer: write queue, transactions, retries, reads, snapshots.

Real stores only (SPEC-10 §1): nothing here mocks Relate or the queue.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from sdd.errors import SddError
from sdd.graph import schema
from sdd.graph.store import LOCK_MARKERS, Store, Tx, encode_props, exists


class Flaky(Exception):
    """A failure the engine marks retryable (like ``write-write conflict``)."""

    retryable = True


def count(st: Store, label: str) -> int:
    return int(st.read(f"MATCH (n:{label}) RETURN count(n) AS c")[0]["c"])


# ---------------------------------------------------------------- transactions


def test_spec01_ac04_failed_job_rolls_back(store: Store) -> None:
    def half_done(tx: Tx) -> None:
        tx.run("CREATE (:Task {id: 'M01.1'})")
        tx.run("CREATE (:Task {id: 'M01.2'})")
        raise ValueError("midway")

    with pytest.raises(ValueError, match="midway"):
        store.write(half_done)
    assert count(store, "Task") == 0

    store.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.3'})"))
    assert store.read("MATCH (t:Task) RETURN t.id AS id") == [{"id": "M01.3"}]


def test_spec01_ac04_engine_error_midway_rolls_back(store: Store) -> None:
    store.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))

    def violates(tx: Tx) -> None:
        tx.run("CREATE (:Task {id: 'M01.2'})")
        tx.run("CREATE (:Task {id: 'M01.1'})")  # unique id constraint

    with pytest.raises(Exception, match="uniqueness"):
        store.write(violates)
    assert sorted(r["id"] for r in store.read("MATCH (t:Task) RETURN t.id AS id")) == ["M01.1"]
    store.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.2'})"))
    assert count(store, "Task") == 2


def test_write_returns_job_result(store: Store) -> None:
    result = store.write(lambda tx: tx.run("CREATE (t:Task {id: 'M01.1'}) RETURN t.id AS id"))
    assert result == [{"id": "M01.1"}]


def test_read_never_writes(store: Store) -> None:
    assert store.read("CREATE (t:Task {id: 'M09.1'}) RETURN t.id AS id") == [{"id": "M09.1"}]
    assert count(store, "Task") == 0


def test_sdd_errors_pass_through_unchanged(store: Store) -> None:
    def refuse(tx: Tx) -> None:
        tx.run("CREATE (:Task {id: 'M01.1'})")
        raise SddError("already_claimed", "taken")

    with pytest.raises(SddError) as err:
        store.write(refuse)
    assert err.value.code == "already_claimed"
    assert count(store, "Task") == 0


# ---------------------------------------------------------------- queue


def test_write_queue_runs_jobs_in_submission_order(store: Store) -> None:
    gate = threading.Event()
    store.submit(lambda tx: gate.wait(5))  # hold the writer so the queue fills up
    order: list[int] = []

    def job(i: int) -> object:
        return lambda tx: (order.append(i), tx.run("CREATE (:Event {id: $id})", {"id": f"e{i}"}))

    futures = [store.submit(job(i)) for i in range(25)]
    gate.set()
    for f in futures:
        f.result(timeout=10)
    assert order == list(range(25))
    assert count(store, "Event") == 25


def test_many_threads_read_and_write_one_store(store: Store) -> None:
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(5):
                store.write(
                    lambda tx, n=n, i=i: tx.run("CREATE (:Agent {id: $id})", {"id": f"{n}.{i}"})
                )
                store.read("MATCH (a:Agent) RETURN count(a) AS c")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert count(store, "Agent") == 50


def test_job_cannot_queue_a_job(store: Store) -> None:
    with pytest.raises(RuntimeError, match="cannot queue"):
        store.write(lambda tx: store.read("RETURN 1 AS x"))


def test_closed_store_refuses_jobs(tmp_path: Path) -> None:
    st = Store.open(tmp_path / "g")
    st.close()
    st.close()  # idempotent
    with pytest.raises(RuntimeError, match="closed"):
        st.read("RETURN 1 AS x")


def test_close_drains_queue_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "g"
    st = Store.open(path)
    futures = [
        st.submit(lambda tx, i=i: tx.run("CREATE (:Task {id: $id})", {"id": f"M01.{i}"}))
        for i in range(10)
    ]
    st.close()
    assert all(f.done() and f.exception() is None for f in futures)
    with Store.open(path) as again:
        assert count(again, "Task") == 10


# ---------------------------------------------------------------- retries


def test_retry_runs_job_again_after_rollback(tmp_path: Path) -> None:
    attempts = 0

    def flaky(tx: Tx) -> str:
        nonlocal attempts
        attempts += 1
        tx.run("CREATE (:Task {id: 'M01.1'})")
        if attempts < 3:
            raise Flaky("write-write conflict")
        return "done"

    with Store.open(tmp_path / "g", retry_delays=(0.01, 0.01, 0.01)) as st:
        schema.ensure(st)
        assert st.write(flaky) == "done"
        assert attempts == 3
        assert count(st, "Task") == 1  # earlier attempts were rolled back


def test_retry_gives_up_with_write_conflict(tmp_path: Path) -> None:
    attempts = 0

    def always(tx: Tx) -> None:
        nonlocal attempts
        attempts += 1
        raise Flaky("storage locked")

    with Store.open(tmp_path / "g", retry_delays=(0.01, 0.01, 0.01)) as st:
        with pytest.raises(SddError) as err:
            st.write(always)
        assert err.value.code == "write_conflict"
        assert err.value.retryable is True
        assert attempts == 4  # first run + 3 retries


def test_non_retryable_error_runs_once(store: Store) -> None:
    attempts = 0

    def broken(tx: Tx) -> None:
        nonlocal attempts
        attempts += 1
        raise KeyError("bug")

    with pytest.raises(KeyError):
        store.write(broken)
    assert attempts == 1


# ---------------------------------------------------------------- one writer process

HOLDER = """
import sys, time
from sdd.graph.store import Store
st = Store.open(sys.argv[1])
print("ready", flush=True)
time.sleep(float(sys.argv[2]))
st.close()
"""


def hold_store(path: Path, seconds: float) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path), str(seconds)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    return proc


def test_second_writer_process_gets_daemon_running(tmp_path: Path) -> None:
    path = tmp_path / "g"
    proc = hold_store(path, 10)
    try:
        with pytest.raises(SddError) as err:
            Store.open(path, retry_delays=(0.01, 0.01))
        assert err.value.code == "daemon_running"
        # a read-only snapshot still opens next to the writer
        with Store.open(path, read_only=True) as ro:
            assert ro.read("RETURN 1 AS x") == [{"x": 1}]
    finally:
        proc.kill()
        proc.wait()


def test_open_retries_until_the_lock_is_released(tmp_path: Path) -> None:
    path = tmp_path / "g"
    proc = hold_store(path, 0.2)
    try:
        with Store.open(path, retry_delays=(0.05, 0.2, 0.8, 1.6)) as st:
            assert st.read("RETURN 1 AS x") == [{"x": 1}]
    finally:
        proc.wait()


def test_killed_writer_leaves_no_stale_lock(tmp_path: Path) -> None:
    path = tmp_path / "g"
    proc = hold_store(path, 30)
    proc.kill()  # SIGKILL: no clean close
    proc.wait()
    with Store.open(path, retry_delays=()) as st:
        st.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))


# ---------------------------------------------------------------- read-only and snapshots


def make_store(path: Path) -> None:
    with Store.open(path) as st:
        schema.ensure(st)
        st.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))


def files_under(path: Path) -> set[Path]:
    return {p.relative_to(path) for p in path.rglob("*")}


def test_read_only_open_refuses_writes(tmp_path: Path) -> None:
    path = tmp_path / "g"
    make_store(path)
    before = files_under(path)
    with Store.open(path, read_only=True) as ro:
        assert count(ro, "Task") == 1
        with pytest.raises(SddError) as err:
            ro.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.2'})"))
        assert err.value.code == "read_only"
        ro.read_snapshot("CREATE (:Task {id: 'M01.3'})")  # rolled back, never committed
        assert count(ro, "Task") == 1
        ro.checkpoint()  # a no-op, not an error
    assert files_under(path) == before
    with Store.open(path, read_only=True) as ro:
        assert count(ro, "Task") == 1


def test_read_only_open_of_missing_store_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "nope"
    with pytest.raises(SddError) as err:
        Store.open(path, read_only=True)
    assert err.value.code == "invalid_input"
    assert not path.exists()
    assert not exists(path)


def test_read_only_open_needs_lock_markers(tmp_path: Path) -> None:
    path = tmp_path / "g"
    make_store(path)
    for marker in LOCK_MARKERS:
        (path / marker).unlink()
    for writer in path.rglob(".cypherlite.writer"):
        writer.unlink()
    with pytest.raises(SddError) as err:
        Store.open(path, read_only=True)
    assert err.value.code == "invalid_input"
    assert ".cypherlite.lock" in err.value.message


def test_read_only_open_works_without_writer_markers(tmp_path: Path) -> None:
    path = tmp_path / "g"
    make_store(path)
    for writer in path.rglob(".cypherlite.writer"):
        writer.unlink()
    with Store.open(path, read_only=True) as ro:
        assert count(ro, "Task") == 1
    assert not list(path.rglob(".cypherlite.writer"))


def test_snapshot_sees_committed_data_only(store: Store) -> None:
    store.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))
    gate, inside = threading.Event(), threading.Event()

    def slow(tx: Tx) -> None:
        tx.run("CREATE (:Task {id: 'M01.2'})")
        inside.set()
        gate.wait(5)

    pending = store.submit(slow)
    inside.wait(5)
    # the writer is mid-transaction; the snapshot does not wait for it and does not see it
    rows = store.read_snapshot("MATCH (t:Task) RETURN t.id AS id ORDER BY id")
    gate.set()
    pending.result(timeout=5)
    assert rows == [{"id": "M01.1"}]
    assert len(store.read_snapshot("MATCH (t:Task) RETURN t.id AS id")) == 2


def test_snapshot_limit_and_rollback(store: Store) -> None:
    store.write(lambda tx: tx.run("UNWIND range(1, 10) AS i CREATE (:Event {id: toString(i)})"))
    assert len(store.read_snapshot("MATCH (e:Event) RETURN e.id AS id", limit=3)) == 3
    # a read-only connection takes a write inside a transaction and refuses it only at commit;
    # the snapshot never commits, so the write is discarded
    assert store.read_snapshot("CREATE (e:Event {id: 'x'}) RETURN e.id AS id") == [{"id": "x"}]
    assert count(store, "Event") == 10


def test_in_memory_snapshot_is_rolled_back() -> None:
    with Store.open(":memory:") as st:
        assert st.in_memory
        rows = st.read_snapshot("CREATE (n:Task {id: 'M01.1'}) RETURN count(n) AS c")
        assert rows == [{"c": 1}]
        assert count(st, "Task") == 0
        st.checkpoint()


def test_checkpoint_flushes_to_store_files(store: Store) -> None:
    manifest = Path(store.path) / "manifest.json"
    before = manifest.read_text() if manifest.exists() else ""
    store.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))
    store.checkpoint()
    assert manifest.read_text() != before  # sdd public reopens when this file changes


# ---------------------------------------------------------------- map properties (O10)


def test_map_property_round_trip(store: Store) -> None:
    header = {"Status": "v1 (2026-11-21)", "Owner of": "graph shapes", "n": 2}
    props = encode_props({"title": "Graph", "header": header, "tags": ["a", "b"]})
    assert props["header_json"].startswith("{")
    assert props["tags"] == ["a", "b"]
    store.write(lambda tx: tx.run("CREATE (s:Spec {id: 'SPEC-02'}) SET s += $p", {"p": props}))

    node = store.read("MATCH (s:Spec) RETURN s")[0]["s"]
    assert node == {"id": "SPEC-02", "title": "Graph", "header": header, "tags": ["a", "b"]}
    assert store.read("MATCH (s:Spec) RETURN properties(s) AS p")[0]["p"]["header"] == header
    assert store.read("MATCH (s:Spec) RETURN s.header_json AS header_json") == [{"header": header}]
    assert store.read_snapshot("MATCH (s:Spec) RETURN s")[0]["s"]["header"] == header


def test_map_on_relationship_and_nested_list() -> None:
    data = {"files": ["a.py"], "commit": None}
    props = encode_props({"data": data, "matrix": [[1, 2]], "empty": {}})
    assert set(props) == {"data_json", "matrix_json", "empty_json"}
    with Store.open(":memory:") as st:
        st.write(
            lambda tx: tx.run(
                "CREATE (:Agent {id: 'a'})-[r:CLAIMED]->(:Task {id: 't'}) SET r += $p", {"p": props}
            )
        )
        rel = st.read("MATCH ()-[r:CLAIMED]->() RETURN r")[0]["r"]
    assert rel == {"data": data, "matrix": [[1, 2]], "empty": {}}
