"""``sdd daemon``: the one process that owns the store (SPEC-01 §5; plan M02 §7.2).

Lifecycle: check the bind rule and that no daemon answers, open the store writable, run the startup
full scan, start the watcher, serve HTTP, and write ``.sdd/daemon.json`` once the socket is bound.
On SIGINT/SIGTERM Uvicorn stops serving, then the watcher stops, the write queue drains, the store
is checkpointed and closed, and ``daemon.json`` is removed (only if it is ours).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

import uvicorn

from sdd.config import Settings
from sdd.errors import SddError
from sdd.service import remote
from sdd.service.runtime import Runtime
from sdd.sync.watcher import Watcher
from sdd.web.api import create_app

__all__ = ["check_bind", "prepare", "remove_daemon_file", "run", "write_daemon_file"]

log = logging.getLogger("sdd.daemon")

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def check_bind(host: str, settings: Settings) -> None:
    """SPEC-09 §2 rule 1: a non-loopback bind needs SDD_ALLOW_REMOTE and a token or container."""
    if host in LOOPBACK:
        return
    if not settings.allow_remote:
        raise SddError(
            "invalid_input",
            f"Refusing to bind {host}: set SDD_ALLOW_REMOTE=1 (and SDD_TOKEN) to listen beyond "
            "loopback.",
        )
    if not (settings.token or settings.in_container):
        raise SddError(
            "invalid_input",
            f"Refusing to bind {host}: outside a container SDD_ALLOW_REMOTE=1 also needs a token.",
        )


def prepare(settings: Settings, host: str = "127.0.0.1") -> Runtime:
    """Steps 1 to 4 of SPEC-01 §5: checks, writable store, startup scan. No server, no watcher."""
    check_bind(host, settings)
    if settings.in_memory:
        raise SddError("invalid_input", "A daemon needs a store on disk; drop --store :memory:.")
    info = remote.detect(settings)
    if info is not None:
        raise SddError(
            "daemon_running",
            f"A daemon already runs for this project on port {info.port}.",
            details={"port": info.port, "pid": info.pid},
        )
    runtime = Runtime.open(settings)  # the writer lock: daemon_running if another process holds it
    try:
        runtime.sync(full=True)  # startup scan; # M04a: git sync
    except BaseException:
        runtime.close()
        raise
    return runtime


def write_daemon_file(runtime: Runtime, host: str, port: int) -> None:
    """``.sdd/daemon.json`` through a temp file and ``os.replace`` (it is not Markdown)."""
    settings = runtime.settings
    token = settings.token
    data: dict[str, Any] = {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "instance": runtime.instance,
        "started_at": runtime.started_at,
        "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None,
        "project": settings.project_root.name,
    }
    path = remote.daemon_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def remove_daemon_file(settings: Settings, instance: str) -> bool:
    """Delete ``daemon.json`` only if it names ``instance``; True if it was removed."""
    path: Path = remote.daemon_file(settings)
    try:
        current = json.loads(path.read_text(encoding="utf-8")).get("instance")
    except (OSError, ValueError, AttributeError):
        return False
    if current != instance:
        return False
    with contextlib.suppress(OSError):
        path.unlink()
        return True
    return False


class _Server(uvicorn.Server):
    """Uvicorn, with ``daemon.json`` written after the bind and cleanup before signals re-raise."""

    def __init__(self, config: uvicorn.Config, runtime: Runtime, host: str, port: int) -> None:
        super().__init__(config)
        self.runtime = runtime
        self.host, self.port = host, port
        self.watcher = Watcher(runtime.settings, runtime.on_batch)
        self.cleaned = False

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            write_daemon_file(self.runtime, self.host, self.port)

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        await super().shutdown(sockets=sockets)
        self.cleanup()

    def cleanup(self) -> None:
        """Stop the watcher, drain and close the store, remove our ``daemon.json`` (once)."""
        if self.cleaned:
            return
        self.cleaned = True
        self.watcher.stop()
        self.runtime.close()
        remove_daemon_file(self.runtime.settings, self.runtime.instance)


def run(settings: Settings, *, host: str = "127.0.0.1", port: int = 8770) -> None:
    """Run the daemon until SIGINT or SIGTERM."""
    runtime = prepare(settings, host)
    config = uvicorn.Config(
        create_app(runtime),
        host=host,
        port=port,
        workers=1,
        log_level="info",
        timeout_graceful_shutdown=2,
    )
    server = _Server(config, runtime, host, port)
    try:
        server.watcher.start()
        server.run()
    except KeyboardInterrupt:
        pass  # Uvicorn re-raises SIGINT after a graceful stop
    finally:
        server.cleanup()
