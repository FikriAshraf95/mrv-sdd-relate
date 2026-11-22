"""``sdd snapshot`` (SPEC-08 §3): the committed copies of a project's store.

Writes ``graph/`` (directory copy), ``graph.rl`` (single file) and ``graph-json/`` (readable
JSON codec) under ``--out``. The ``relate`` CLI makes all three, and works beside a running
daemon (it reads every committed transaction, O3); without it only the plain directory copy is
possible, and only when no daemon holds the writer. Every copy is opened read-only and counted
against the live store before the command reports success.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph import schema, store
from sdd.service import remote

__all__ = ["DEFAULT_OUT", "snapshot"]

DEFAULT_OUT = Path(".sdd") / "snapshots"
_COPIES = ("graph", "graph.rl", "graph-json")


def _counts(path: Path | str) -> dict[str, Any]:
    with store.Store.open(path, read_only=True) as st:
        found = schema.counts(st)
    return {
        "nodes": found.nodes,
        "relationships": found.relationships,
        "total_nodes": found.total_nodes,
        "total_relationships": found.total_relationships,
    }


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def snapshot(settings: Settings, out: Path | None = None) -> dict[str, Any]:
    """Checkpoint, then write the three copies and verify their counts."""
    if settings.in_memory:
        raise SddError("invalid_input", "--store :memory: has no files to snapshot.")
    live = settings.store_path
    if not store.exists(live):
        raise SddError("invalid_input", f"No store at {live}. Run `sdd sync` first.")
    target = (out or (settings.project_root / DEFAULT_OUT)).resolve()
    cli = store.relate_cli() is not None
    daemon = remote.routes_through_daemon(settings) and remote.detect(settings) is not None
    if daemon and not cli:
        raise SddError(
            "daemon_running",
            "A daemon holds the store and the relate command-line tool is not installed, so "
            "no consistent copy is possible: install the `relate` CLI or stop the daemon.",
        )
    checkpointed = False
    if not daemon:
        # the writer lock is the final authority: another writer fails with daemon_running
        with store.Store.open(live) as st:
            st.checkpoint()
        checkpointed = True
    target.mkdir(parents=True, exist_ok=True)
    for name in _COPIES:
        _remove(target / name)
    copies = {"graph": "written", "graph_rl": "skipped", "graph_json": "skipped"}
    if cli:
        store.clone(live, target / "graph")
        store.clone(live, target / "graph.rl")
        store.clone(live, target / "graph-json", codec="json")
        copies["graph_rl"] = copies["graph_json"] = "written"
    else:
        store.copy_store(live, target / "graph")
    expected = _counts(live)
    for name in _COPIES:
        if (target / name).exists():
            found = _counts(target / name)
            if found != expected:
                raise SddError(
                    "invalid_input",
                    f"The copy {target / name} does not match the store.",
                    details={"copy": name, "live": expected, "found": found},
                )
    return {
        "out": str(target),
        "copies": copies,
        "relate_cli": cli,
        "checkpointed": checkpointed,
        "total_nodes": expected["total_nodes"],
        "total_relationships": expected["total_relationships"],
    }
