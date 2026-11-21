"""``sdd info`` (SPEC-08 §2): project, store, daemon, counts, schema version."""

from __future__ import annotations

from typing import Any

from sdd.config import Settings
from sdd.graph import schema, store


def info(settings: Settings) -> dict[str, Any]:
    """Describe the project's store without writing anything.

    A missing store reports zero counts. Without a daemon the store is opened read-only, which
    works next to a running writer too. Daemon detection arrives with the daemon (M02).
    """
    path = settings.store_path
    present = store.exists(path)
    counts = schema.Counts(nodes={}, relationships={})
    store_version: int | None = None
    if present:
        # An in-memory store cannot be opened read-only; it is new and empty either way.
        with store.Store.open(path, read_only=not settings.in_memory) as st:
            counts = schema.counts(st)
            store_version = schema.store_schema_version(st)
    return {
        "project": str(settings.project_root),
        "store": path,
        "store_exists": present,
        "daemon": None,
        "schema_version": schema.SCHEMA_VERSION,
        "store_schema_version": store_version,
        "nodes": counts.nodes,
        "relationships": counts.relationships,
        "total_nodes": counts.total_nodes,
        "total_relationships": counts.total_relationships,
    }
