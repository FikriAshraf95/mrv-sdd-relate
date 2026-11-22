"""``sdd public``: the read-only public server (SPEC-09 §4, SPEC-01 §1 rule 4).

A different process from the daemon. It opens the store ``read_only``, never mounts ``/mcp`` and
serves no write route. A follower thread reopens the store when the writer's ``manifest.json``
changes. Like :mod:`sdd.daemon` it wires parts together and imports anything but ``relate``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

from sdd import config
from sdd.config import Settings
from sdd.daemon import check_bind
from sdd.errors import SddError
from sdd.service.follow import Follower
from sdd.service.runtime import Runtime
from sdd.web.api import create_app

__all__ = ["build_app", "prepare", "project_for", "run"]

log = logging.getLogger("sdd.public")

FOLLOW_SECONDS = 2.0


def project_for(store: Path, project: Path | None) -> Path:
    """The project root: ``--project``, else ``PATH/../..`` when ``PATH`` ends in ``.sdd/graph``."""
    if project is not None:
        return project
    resolved = store.resolve()
    if resolved.name == "graph" and resolved.parent.name == ".sdd":
        return resolved.parent.parent
    raise SddError(
        "invalid_input",
        f"Cannot infer the project from --store {store} (it does not end in .sdd/graph): "
        "pass --project DIR.",
    )


def prepare(settings: Settings, host: str) -> Runtime:
    """Check the bind rule, then open the store read-only."""
    check_bind(host, settings)
    return Runtime.open_public(settings)


def build_app(runtime: Runtime) -> Starlette:
    return create_app(runtime, public=True)


def run(
    store: Path,
    *,
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8780,
    interval: float = FOLLOW_SECONDS,
) -> None:
    """Serve until SIGINT or SIGTERM."""
    settings = config.load(project_for(store, project), str(store.resolve()))
    runtime = prepare(settings, host)
    follower = Follower(runtime, interval=interval)
    server = uvicorn.Server(
        uvicorn.Config(
            build_app(runtime),
            host=host,
            port=port,
            workers=1,
            log_level="info",
            proxy_headers=False,
            timeout_graceful_shutdown=2,
        )
    )
    try:
        follower.start()
        server.run()
    except KeyboardInterrupt:
        pass  # Uvicorn re-raises SIGINT after a graceful stop
    finally:
        follower.stop()
