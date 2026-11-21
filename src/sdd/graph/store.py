"""The only door to Relate (SPEC-01 §4). This is the only module that imports ``relate``.

Shape, decided by the M00b experiments (SPEC-00 §8, O5 and O10–O12):

* **One connection, one thread.** Relate connections are thread-affine (a call from another
  thread raises ``WrongThread``, O5). The store's worker thread opens the connection and runs
  every job on it, writes *and* reads, one at a time in submission order. A read therefore
  never sees another job's uncommitted writes.
* **Every job is a transaction.** The connection stays in ``autocommit = False``. A write job
  commits; a read job, a guarded query and any job that raises are rolled back. A job that
  touches several nodes is one transaction.
* **Retries.** A job that fails with a retryable engine error (``write-write conflict``,
  ``storage locked``) is rolled back and run again after 50 / 200 / 800 ms, then fails with
  ``write_conflict``. Jobs must be idempotent. Opening a store another process writes retries
  on the same schedule, then fails with ``daemon_running``.
* **No map properties (O10).** A property whose value is a map, or a list holding maps or lists,
  is stored as a JSON string under ``<name>_json`` (:func:`encode_props`). Results are decoded
  on the way out, so callers always see ``<name>`` as a map.
* **Snapshots (O11, O12).** ``read_only=True`` opens never write a file, so they work on a
  read-only mount, but need the ``.cypherlite.lock`` markers (root and ``wal/``).
  :meth:`Store.read_snapshot` opens a fresh read-only connection on the *calling* thread for
  each guarded query, so those never wait behind the write queue.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, TypeVar

import relate

from sdd.errors import SddError

MEMORY = ":memory:"
RETRY_DELAYS: tuple[float, ...] = (0.05, 0.2, 0.8)
JSON_SUFFIX = "_json"
LOCK_MARKERS = (Path(".cypherlite.lock"), Path("wal") / ".cypherlite.lock")

_RETRY_MARKERS = ("storage locked", "write-write conflict")
_READ_ONLY_KIND = "WriteOnReadOnlyAccessDatabase"

Row = dict[str, Any]
T = TypeVar("T")
_Mode = Literal["write", "read", "flush"]


# ---------------------------------------------------------------- values in and out


def encode_props(props: Mapping[str, Any]) -> dict[str, Any]:
    """Property map → storable map: maps and nested lists become ``<name>_json`` strings."""
    out: dict[str, Any] = {}
    for key, value in props.items():
        if _needs_json(value):
            out[key + JSON_SUFFIX] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            out[key] = value
    return out


def _needs_json(value: Any) -> bool:
    if isinstance(value, dict):
        return True
    return isinstance(value, list | tuple) and any(
        isinstance(v, dict | list | tuple) for v in value
    )


def _decode_map(props: Mapping[str, Any]) -> Row:
    out: Row = {}
    for key, value in props.items():
        if key.endswith(JSON_SUFFIX) and isinstance(value, str):
            out[key[: -len(JSON_SUFFIX)]] = json.loads(value)
        else:
            out[key] = _plain(value)
    return out


def _plain(value: Any) -> Any:
    """Engine value → plain Python: nodes and relationships become their (decoded) properties."""
    if isinstance(value, relate.Node | relate.Relationship):
        return _decode_map(value.properties)
    if isinstance(value, Mapping):
        return _decode_map(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _rows(cursor: relate.Cursor, limit: int | None = None) -> list[Row]:
    records = cursor.fetchall() if limit is None else cursor.fetchmany(limit)
    return [_decode_map(dict(record)) for record in records]


# ---------------------------------------------------------------- errors


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, SddError):
        return False
    if getattr(exc, "retryable", None) is True:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _RETRY_MARKERS)


def _translate(exc: BaseException, path: str) -> BaseException:
    """Engine errors callers must branch on become :class:`SddError`; others pass through."""
    if getattr(exc, "kind", None) == _READ_ONLY_KIND:
        return SddError(
            "read_only",
            f"The store {path} is open read-only here; writes go through the daemon.",
        )
    return exc


def exists(path: str | Path) -> bool:
    """Whether ``path`` holds a directory store (``:memory:`` always 'exists')."""
    if str(path) == MEMORY:
        return True
    root = Path(path)
    return (root / LOCK_MARKERS[0]).is_file() or (root / "manifest.json").is_file()


# ---------------------------------------------------------------- jobs


class Tx:
    """What a write job gets: runs statements inside the job's transaction."""

    def __init__(self, conn: relate.Connection) -> None:
        self._conn = conn

    def run(self, cypher: str, params: Mapping[str, Any] | None = None) -> list[Row]:
        return _rows(self._conn.execute(cypher, dict(params) if params else None))


@dataclass
class _Job:
    mode: _Mode
    fn: Callable[[relate.Connection], Any]
    retry: bool
    future: Future[Any] = field(default_factory=Future)


_STOP = object()


# ---------------------------------------------------------------- the store


class Store:
    """One Relate store, owned by one worker thread. Use :meth:`open`, then :meth:`close`."""

    def __init__(
        self, path: str, *, read_only: bool, retry_delays: tuple[float, ...] = RETRY_DELAYS
    ) -> None:
        self.path = path
        self.read_only = read_only
        self.retry_delays = retry_delays
        self._queue: queue.SimpleQueue[_Job | object] = queue.SimpleQueue()
        self._closed = False
        self._submit_lock = threading.Lock()
        self._ready: Future[None] = Future()
        self._thread = threading.Thread(target=self._work, name=f"sdd-store:{path}", daemon=True)

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        read_only: bool = False,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
    ) -> Store:
        """Open ``path`` (a directory, or ``:memory:``) and start the worker thread.

        Writable: creates the store if missing; ``daemon_running`` if another process keeps it
        locked past the retries. Read-only: never creates or writes a file; ``invalid_input``
        if there is no store.
        """
        text = MEMORY if str(path) == MEMORY else str(Path(path))
        store = cls(text, read_only=read_only, retry_delays=retry_delays)
        store._thread.start()
        store._ready.result()
        return store

    @property
    def in_memory(self) -> bool:
        return self.path == MEMORY

    # ------------------------------------------------------------ public API

    def submit(self, fn: Callable[[Tx], T]) -> Future[T]:
        """Queue a write job without waiting. Jobs run one at a time, in submission order."""
        if self.read_only:
            raise SddError(
                "read_only",
                f"The store {self.path} is open read-only here; writes go through the daemon.",
            )
        return self._submit("write", lambda conn: fn(Tx(conn)), retry=True)

    def write(self, fn: Callable[[Tx], T]) -> T:
        """Run ``fn`` as one transaction on the writer thread and return its result.

        Committed on return, rolled back if ``fn`` raises. Retried from the start on a
        retryable engine error, so ``fn`` must be idempotent.
        """
        return self.submit(fn).result()

    def read(self, cypher: str, params: Mapping[str, Any] | None = None) -> list[Row]:
        """Run a read statement on the worker thread, after every job queued before it.

        Runs in a transaction that is always rolled back, so a stray write changes nothing.
        """
        future = self._submit("read", lambda conn: _rows(_exec(conn, cypher, params)), retry=False)
        return future.result()

    def read_snapshot(
        self, cypher: str, params: Mapping[str, Any] | None = None, *, limit: int | None = None
    ) -> list[Row]:
        """Run a statement on a fresh ``read_only`` snapshot, in a rolled-back transaction.

        It runs on the *calling* thread and never waits behind the write queue. The snapshot
        holds everything committed so far. ``limit`` caps the rows fetched. An in-memory or
        read-only store has no separate snapshot, so the statement runs as a rolled-back job on
        the worker thread instead.
        """
        return self._on_snapshot(lambda conn: _rows(_exec(conn, cypher, params), limit))

    def query_snapshot(
        self, cypher: str, params: Mapping[str, Any] | None = None, *, limit: int
    ) -> tuple[list[str], list[list[Any]]]:
        """As :meth:`read_snapshot`, for guarded queries (SPEC-09 §3): ``(columns, rows)``,
        each row a list in column order, at most ``limit`` rows fetched. Columns are known even
        when no row comes back. Values are decoded like every result (nodes → properties)."""

        def run(conn: relate.Connection) -> tuple[list[str], list[list[Any]]]:
            cursor = _exec(conn, cypher, params)
            columns = [str(c) for c in cursor.columns]
            rows = [[_plain(dict(r)[c]) for c in columns] for r in cursor.fetchmany(limit)]
            return columns, rows

        return self._on_snapshot(run)

    def _on_snapshot(self, fn: Callable[[relate.Connection], T]) -> T:
        if self.in_memory or self.read_only:
            return self._submit("read", fn, retry=False).result()
        try:
            conn = relate.connect(self.path, read_only=True)
        except relate.Error as exc:
            raise _open_error(exc, self.path, read_only=True) from None
        try:
            conn.autocommit = False
            return fn(conn)
        except relate.Error as exc:
            raise _translate(exc, self.path) from None
        finally:
            conn.close()  # rolls back the open transaction first

    def checkpoint(self) -> None:
        """Flush committed data into the store files (SPEC-01 §4); no-op read-only or in memory."""
        self._submit("flush", lambda conn: conn.flush(), retry=False).result()

    def close(self) -> None:
        """Run every queued job, checkpoint, close the connection and stop the worker."""
        with self._submit_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(_STOP)
        if threading.current_thread() is not self._thread:
            self._thread.join()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------ worker

    def _submit(
        self, mode: _Mode, fn: Callable[[relate.Connection], T], *, retry: bool
    ) -> Future[T]:
        if threading.current_thread() is self._thread:
            raise RuntimeError("a store job cannot queue another job; use its Tx instead")
        job = _Job(mode, fn, retry)
        with self._submit_lock:
            if self._closed:
                raise RuntimeError(f"store {self.path} is closed")
            self._queue.put(job)
        return job.future

    def _work(self) -> None:
        try:
            conn = self._connect()
            conn.autocommit = False
        except BaseException as exc:
            self._closed = True
            self._ready.set_exception(exc)
            return
        self._ready.set_result(None)
        try:
            while True:
                item = self._queue.get()
                if item is _STOP:
                    break
                assert isinstance(item, _Job)
                if not item.future.set_running_or_notify_cancel():
                    continue
                try:
                    item.future.set_result(self._run(conn, item))
                except BaseException as exc:
                    item.future.set_exception(exc)
        finally:
            if not self.read_only and not self.in_memory:
                conn.flush()
            conn.close()

    def _connect(self) -> relate.Connection:
        if self.read_only and not exists(self.path):
            raise SddError(
                "invalid_input",
                f"No store at {self.path}. Run `sdd sync` (or start the daemon) to create it.",
                details={"store": self.path},
            )
        delays = iter(self.retry_delays)
        while True:
            try:
                return relate.connect(self.path, read_only=self.read_only)
            except relate.Error as exc:
                delay = next(delays, None)
                if not _retryable(exc) or delay is None:
                    raise _open_error(exc, self.path, read_only=self.read_only) from None
                time.sleep(delay)

    def _run(self, conn: relate.Connection, job: _Job) -> Any:
        if job.mode == "flush":
            if not self.read_only and not self.in_memory:
                conn.flush()
            return None
        delays = iter(self.retry_delays)
        while True:
            try:
                result = job.fn(conn)
                if job.mode == "write":
                    conn.commit()
                else:
                    conn.rollback()
                return result
            except BaseException as exc:
                _rollback_quietly(conn)
                delay = next(delays, None) if job.retry and _retryable(exc) else None
                if delay is None:
                    if job.retry and _retryable(exc):
                        raise SddError(
                            "write_conflict",
                            f"The write kept conflicting after {len(self.retry_delays)} "
                            "retries. Try again.",
                        ) from exc
                    translated = _translate(exc, self.path)
                    if translated is exc:
                        raise
                    raise translated from exc
                time.sleep(delay)


def _exec(conn: relate.Connection, cypher: str, params: Mapping[str, Any] | None) -> relate.Cursor:
    return conn.execute(cypher, dict(params) if params else None)


def _rollback_quietly(conn: relate.Connection) -> None:
    # the original error is the one worth reporting
    with contextlib.suppress(relate.Error):
        conn.rollback()


def _open_error(exc: relate.Error, path: str, *, read_only: bool) -> SddError:
    message = str(exc)
    if _retryable(exc):
        return SddError(
            "daemon_running",
            f"Another process writes the store {path} (a running `sdd daemon`?). "
            "Use its API, or stop it first.",
            details={"store": path},
        )
    if read_only and "requires an existing" in message:
        markers = ", ".join(str(m) for m in LOCK_MARKERS)
        return SddError(
            "invalid_input",
            f"{path} is not a complete store: a read-only open needs {markers}. "
            "Copy stores with `sdd snapshot`, which keeps them.",
            details={"store": path},
        )
    return SddError(
        "invalid_input", f"Cannot open the store {path}: {message}", details={"store": path}
    )
