"""The daemon's shared state: store, event bus, sync state and the sync lock (plan M02 §4, M04a §6).

One :class:`Runtime` per daemon. Every sync (startup, watcher batch, HEAD change,
``POST /api/sync``) and every tick goes through ``sync_lock``, so the parse cache, the code cache
and the report are never used by two threads. All of them run the one order of
:func:`sdd.sync.pipeline.run`.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph import schema
from sdd.graph.store import QueryProcess, Store
from sdd.ids import InvalidIdError, label_of
from sdd.service import indexing
from sdd.service.events import EventBus
from sdd.sync import indexer, pipeline
from sdd.sync.watcher import Batch

__all__ = ["Runtime", "publish_changed"]

log = logging.getLogger("sdd.runtime")


def publish_changed(events: EventBus, ids: Iterable[str]) -> None:
    """Publish one ``graph_changed`` ``{ids, kinds}`` (kinds: the distinct labels, sorted)."""
    ordered = sorted(set(ids))
    kinds: set[str] = set()
    for node_id in ordered:
        try:
            kinds.add(label_of(node_id))
        except InvalidIdError:
            continue
    events.publish("graph_changed", {"ids": ordered, "kinds": sorted(kinds)})


@dataclass
class Runtime:
    settings: Settings
    store: Store
    events: EventBus = field(default_factory=EventBus)
    mode: str = "daemon"
    instance: str = field(default_factory=lambda: secrets.token_hex(8))
    started_at: str = ""
    sync_lock: threading.Lock = field(default_factory=threading.Lock)
    query_gate: threading.Lock = field(default_factory=threading.Lock)  # SPEC-09 §3 step 3
    cache: indexer.ParseCache = field(default_factory=dict)
    last_report: indexer.SyncReport | None = None
    synced_at: str | None = None
    state: pipeline.SyncState | None = None  # parse cache, code cache, ignore rules, tracked
    _queries: QueryProcess | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.state is None:
            self.state = pipeline.SyncState.new(self.settings, self.cache)

    def queries(self) -> QueryProcess:
        """The guarded-query worker process (SPEC-09 §3 step 3), made on first use."""
        if self._queries is None:
            self._queries = QueryProcess(self.settings.query_memory_mb)
        return self._queries

    @classmethod
    def open(cls, settings: Settings) -> Runtime:
        """Open the store writable (``daemon_running`` if another process holds it)."""
        store = Store.open(settings.store_path)
        try:
            schema.ensure(store)
        except BaseException:
            store.close()
            raise
        return cls(settings=settings, store=store, started_at=settings.now_iso())

    @classmethod
    def open_public(cls, settings: Settings) -> Runtime:
        """Open the store ``read_only`` for ``sdd public`` (SPEC-09 §4): no schema work."""
        store = Store.open(settings.store_path, read_only=True)
        return cls(settings=settings, store=store, mode="public", started_at=settings.now_iso())

    def sync(
        self,
        *,
        full: bool = True,
        files: Mapping[str, str] | None = None,
        paths: Iterable[str] | None = None,
        git: bool = False,
    ) -> dict[str, Any]:
        """One sync under the lock; publishes one ``graph_changed`` if anything changed.

        ``files`` is an explicit set of SDD documents (``{path: kind}``) for a non-full sync; with
        no ``paths`` they are the paths the sync looks at.
        """
        report = self._run(full=full, files=files, paths=paths, git=git)
        return indexing.report_dict(self.settings, report, schema.counts(self.store))

    def _run(
        self,
        *,
        full: bool,
        files: Mapping[str, str] | None = None,
        paths: Iterable[str] | None = None,
        git: bool = False,
    ) -> indexer.SyncReport:
        assert self.state is not None
        if paths is None:
            paths = files.keys() if files is not None else ()
        with self.sync_lock:
            report = pipeline.run(
                self.store,
                self.settings,
                self.state,
                full=full,
                paths=paths,
                sdd_files=files,
                git_sync=git,
            )
            if report.indexed:
                self.last_report = report
            self.synced_at = self.settings.now_iso()
        if report.changed_ids:
            publish_changed(self.events, report.changed_ids)
        return report

    def synced(self) -> str | None:
        """The last sync time (``synced_at`` on every tool result, SPEC-05 §1 rule 4)."""
        if self.synced_at is not None:
            return self.synced_at
        rows = self.store.read("MATCH (m:Meta {id: 'meta'}) RETURN m.last_full_sync AS at")
        return rows[0]["at"] if rows else None

    def on_batch(self, batch: Batch) -> None:
        """Watcher callback: every batch goes through the pipeline (code paths included)."""
        try:
            self._run(full=False, files=batch.sdd_files, paths=batch.paths)
        except SddError as exc:
            log.error("sync of %d paths failed: %s", len(batch.paths), exc.code)

    def on_head(self, sha: str) -> None:
        """HEAD poller callback: sync the new commits (the code step covers their new files)."""
        try:
            self._run(full=False, git=True)
        except SddError as exc:
            log.error("git sync at %s failed: %s", sha[:7], exc.code)

    def close(self) -> None:
        """Stop the query worker; drain the write queue, checkpoint and close the store."""
        if self._queries is not None:
            self._queries.close()
        self.store.close()
