"""The daemon's shared state: store, event bus, parse cache and the sync lock (plan M02 §4).

One :class:`Runtime` per daemon. Every sync (startup, watcher batch, ``POST /api/sync``) and every
tick goes through ``sync_lock``, so the parse cache and the report are never used by two threads.
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
from sdd.graph.store import Store
from sdd.ids import InvalidIdError, label_of
from sdd.service import indexing
from sdd.service.events import EventBus
from sdd.sync import indexer
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
    cache: indexer.ParseCache = field(default_factory=dict)
    last_report: indexer.SyncReport | None = None
    synced_at: str | None = None
    tracked: set[str] = field(default_factory=set)  # SDD paths of the last sync

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

    def sync(self, *, full: bool = True, files: Mapping[str, str] | None = None) -> dict[str, Any]:
        """One sync under the lock; publishes one ``graph_changed`` if anything changed."""
        with self.sync_lock:
            tracked = dict(files) if files is not None else indexer.discover(self.settings)
            report = indexer.sync(
                self.store, self.settings, full=full, files=tracked, cache=self.cache
            )
            counts = schema.counts(self.store)
            self.tracked = set(tracked)
            self.last_report = report
            self.synced_at = self.settings.now_iso()
        if report.changed_ids:
            publish_changed(self.events, report.changed_ids)
        return indexing.report_dict(self.settings, report, counts)

    def synced(self) -> str | None:
        """The last sync time (``synced_at`` on every tool result, SPEC-05 §1 rule 4)."""
        if self.synced_at is not None:
            return self.synced_at
        rows = self.store.read("MATCH (m:Meta {id: 'meta'}) RETURN m.last_full_sync AS at")
        return rows[0]["at"] if rows else None

    def on_batch(self, batch: Batch) -> None:
        """Watcher callback: sync only when the batch touched an SDD document."""
        if not any(p in batch.sdd_files or p in self.tracked for p in batch.paths):
            return  # M04a: code paths are handled here
        try:
            self.sync(full=False, files=batch.sdd_files)
        except SddError as exc:
            log.error("sync of %d paths failed: %s", len(batch.paths), exc.code)

    def close(self) -> None:
        """Drain the write queue, checkpoint and close the store."""
        self.store.close()
