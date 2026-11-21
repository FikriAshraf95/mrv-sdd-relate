"""Test helpers for sync tests: a controllable clock, ``sync_project`` and a graph ``dump``."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sdd import config
from sdd.graph.store import Store, Tx
from sdd.sync import indexer, pipeline

Rels = Counter[tuple[str, str, str, frozenset[tuple[str, str]]]]


@dataclass
class Clock:
    """A settable clock (SPEC-10 §1): ``Settings.clock`` calls it."""

    now: datetime = field(default_factory=lambda: datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.now

    def tick(self, minutes: int = 1) -> str:
        self.now += timedelta(minutes=minutes)
        return config.iso_utc(self.now)


def settings_for(root: Path, clock: Clock | None = None) -> config.Settings:
    return config.load(root, config.MEMORY_STORE, env={}, clock=clock or Clock())


def sync_project(
    root: Path, store: Store, clock: Clock | None = None, *, writeback: bool | None = None
) -> indexer.SyncReport:
    settings = settings_for(root, clock)
    if writeback is not None:
        settings = replace(settings, writeback=writeback)
    return indexer.full_sync(store, settings)


@dataclass
class Sync:
    """One project, one store and one :class:`SyncState`, like the daemon's runtime (M04a)."""

    root: Path
    store: Store
    clock: Clock = field(default_factory=Clock)
    max_files: int | None = None
    git_max_commits: int | None = None
    state: pipeline.SyncState = field(init=False)

    def __post_init__(self) -> None:
        self.state = pipeline.SyncState.new(self.settings())

    def settings(self) -> config.Settings:
        settings = settings_for(self.root, self.clock)
        if self.max_files is not None:
            settings = replace(settings, max_files=self.max_files)
        if self.git_max_commits is not None:
            settings = replace(settings, git_max_commits=self.git_max_commits)
        return settings

    def full(self) -> indexer.SyncReport:
        self.clock.tick()
        return pipeline.run(self.store, self.settings(), self.state, full=True)

    def batch(self, *paths: str) -> indexer.SyncReport:
        """A watcher batch of ``paths`` (the SDD set is the current one)."""
        self.clock.tick()
        settings = self.settings()
        sdd = indexer.discover(settings)
        return pipeline.run(
            self.store, settings, self.state, full=False, paths=paths, sdd_files=sdd
        )

    def head(self) -> indexer.SyncReport:
        """What the HEAD poller triggers: a git sync only."""
        self.clock.tick()
        return pipeline.run(self.store, self.settings(), self.state, full=False, git_sync=True)


def dump(
    store: Store,
    *,
    drop_labels: Iterable[str] = (),
    drop_props: Iterable[str] = (),
    drop_rel_types: Iterable[str] = (),
    drop_rel_srcs: Iterable[str] = (),
) -> tuple[dict[str, tuple[str, dict[str, Any]]], Rels]:
    """All nodes (``id`` → label, props) and relationships (a Counter of type, ends, props)."""
    skip_labels, skip_props = set(drop_labels), set(drop_props)
    skip_types, skip_srcs = set(drop_rel_types), set(drop_rel_srcs)
    nodes: dict[str, tuple[str, dict[str, Any]]] = {}
    for row in store.read("MATCH (n) RETURN n.id AS id, labels(n) AS labels, properties(n) AS p"):
        label = row["labels"][0]
        if label in skip_labels:
            continue
        nodes[row["id"]] = (label, {k: v for k, v in row["p"].items() if k not in skip_props})
    rels: Rels = Counter()
    for row in store.read(
        "MATCH (a)-[r]->(b) RETURN type(r) AS type, a.id AS f, b.id AS t, properties(r) AS p"
    ):
        if row["type"] in skip_types or row["p"].get("src") in skip_srcs:
            continue
        if row["f"] not in nodes or row["t"] not in nodes:
            continue  # an endpoint was dropped with its label
        props = frozenset((k, json.dumps(v, sort_keys=True)) for k, v in row["p"].items())
        rels[(row["type"], row["f"], row["t"], props)] += 1
    return nodes, rels


def counts(store: Store) -> tuple[int, int]:
    nodes = store.read("MATCH (n) RETURN count(n) AS n")[0]["n"]
    rels = store.read("MATCH ()-[r]->() RETURN count(r) AS n")[0]["n"]
    return int(nodes), int(rels)


def write_files(root: Path, files: dict[str, str | None]) -> Path:
    """Write (or, for ``None``, delete) project files; text uses ``\\n``."""
    for rel, text in files.items():
        target = root / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    return root


SPEC_A = """# SPEC-01 — Alpha

> **Status:** v1

## 1. First

See [SPEC-02 §1](SPEC-02-beta.md#1-one) for details.

## 2. Second

Nothing here.
"""

SPEC_B = """# SPEC-02 — Beta

> **Status:** v1

## 1. One

Text of one.

## 2. Two

Text of two.
"""

MILESTONE = """# M01 — First

> **Depends on:** nothing
> **Read first:** [SPEC-01 §1](../specs/SPEC-01-alpha.md#1-first) · [SPEC-02 §2](../specs/SPEC-02-beta.md#2-two)

## Goal
Do the first thing.

## Tasks
- [ ] **M01.1** First task
- [ ] **M01.2** Second task (after M01.1)

## Acceptance criteria
1. It works.

**Status:**
"""  # noqa: E501


def mini_project(tmp_path: Path, name: str = "mini") -> Path:
    """A tiny project: two specs (one links to the other) and one milestone reading both."""
    root = tmp_path / name
    root.mkdir()
    return write_files(
        root,
        {
            "docs/specs/SPEC-01-alpha.md": SPEC_A,
            "docs/specs/SPEC-02-beta.md": SPEC_B,
            "docs/milestones/M01-first.md": MILESTONE,
        },
    )


def claim(store: Store, task_id: str, agent: str, at: str = "2026-11-22T09:00:00Z") -> None:
    """What M03a's claim will do, written directly: graph-only state on a Task."""

    def job(tx: Tx) -> None:
        tx.run(
            "MATCH (t:Task {id: $id}) SET t.claimed_by = $a, t.claimed_at = $at, "
            "t.status = 'claimed'",
            {"id": task_id, "a": agent, "at": at},
        )
        tx.run(
            "MERGE (g:Agent {id: $gid}) SET g.name = $a, g.first_seen = $at, g.last_seen = $at",
            {"gid": f"agent:{agent}", "a": agent, "at": at},
        )
        tx.run(
            "MATCH (g:Agent {id: $gid}) MATCH (t:Task {id: $id}) "
            "CREATE (g)-[:CLAIMED {src: 'tool', at: $at}]->(t)",
            {"gid": f"agent:{agent}", "id": task_id, "at": at},
        )

    store.write(job)


def events(store: Store) -> list[tuple[str, str, str]]:
    """``(kind, actor, target_id)`` of every Event, sorted."""
    rows = store.read(
        "MATCH (e:Event) RETURN e.kind AS k, e.actor AS a, e.target_id AS t, e.id AS id"
    )
    return sorted((r["k"], r["a"], r["t"]) for r in rows)
