"""Finding the project's daemon and talking to it (SPEC-01 §1 rule 3, §5; plan M02 §7.1).

``.sdd/daemon.json`` alone proves nothing: PIDs are reused and a killed daemon leaves the file
behind. A daemon counts as running only when its port answers ``/api/health`` with the same
``instance`` the file names. ``TRANSPORT`` is the one network seam (stdlib ``urllib``); tests
replace it so nothing opens a socket.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph import store

__all__ = [
    "TRANSPORT",
    "DaemonClient",
    "DaemonInfo",
    "daemon_file",
    "detect",
    "ensure_no_daemon",
    "routes_through_daemon",
]

# method, url, headers, body, timeout seconds -> (HTTP status, decoded JSON or None)
Transport = Callable[[str, str, Mapping[str, str], bytes | None, float], tuple[int, Any]]
HEALTH_TIMEOUT = 1.0
CALL_TIMEOUT = 30.0


@dataclass(frozen=True)
class DaemonInfo:
    port: int
    instance: str
    pid: int
    started_at: str
    auth_ok: bool  # False: something answers with 401, so a token is needed


def _urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


TRANSPORT: Transport = _urllib_transport  # tests monkeypatch this module attribute


def daemon_file(settings: Settings) -> Path:
    return settings.sdd_dir / "daemon.json"


def routes_through_daemon(settings: Settings) -> bool:
    """Only the project's default store goes through a daemon, not ``:memory:`` or another path."""
    return (not settings.in_memory) and settings.store_path == str(settings.sdd_dir / "graph")


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if settings.token:
        headers["Authorization"] = f"Bearer {settings.token}"
    return headers


def detect(settings: Settings) -> DaemonInfo | None:
    """The running daemon of this project, or ``None``. Never deletes a stale ``daemon.json``."""
    try:
        data = json.loads(daemon_file(settings).read_text(encoding="utf-8"))
        port, instance = int(data["port"]), str(data["instance"])
        pid, started_at = int(data.get("pid", 0)), str(data.get("started_at", ""))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        status, body = TRANSPORT(
            "GET", f"http://127.0.0.1:{port}/api/health", _headers(settings), None, HEALTH_TIMEOUT
        )
    except Exception:  # connection refused, timeout, DNS: the file is stale
        return None
    if status == 200 and isinstance(body, dict) and body.get("instance") == instance:
        return DaemonInfo(port, instance, pid, started_at, auth_ok=True)
    if status == 401:
        return DaemonInfo(port, instance, pid, started_at, auth_ok=False)
    return None


def ensure_no_daemon(settings: Settings, *, check_store: bool = False) -> None:
    """Raise ``daemon_running`` if a daemon runs for this project's default store.

    ``check_store`` also opens the store writable once (``ids --write`` never opens it
    otherwise): Relate's writer lock is the final authority (SPEC-01 §1 rule 3).
    """
    if not routes_through_daemon(settings):
        return
    info = detect(settings)
    if info is not None:
        raise SddError(
            "daemon_running",
            f"A daemon runs for this project on port {info.port}; use its API "
            "(or `sdd status`, which routes through it), or stop it first.",
            details={"port": info.port, "pid": info.pid},
        )
    if check_store and store.exists(settings.store_path):
        store.Store.open(settings.store_path).close()


class DaemonClient:
    """A small JSON client for the daemon's ``/api`` (stdlib transport, bearer token)."""

    def __init__(self, settings: Settings, info: DaemonInfo) -> None:
        self._settings = settings
        self._base = f"http://127.0.0.1:{info.port}"
        if not info.auth_ok:
            raise SddError(
                "unauthorized",
                f"The daemon on port {info.port} needs a token. Set SDD_TOKEN to the same value.",
            )

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._call("GET", path, params, None)

    def post(self, path: str, body: Mapping[str, Any] | None = None) -> Any:
        return self._call("POST", path, None, None if body is None else dict(body))

    def _call(
        self, method: str, path: str, params: Mapping[str, Any] | None, body: dict[str, Any] | None
    ) -> Any:
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = _headers(self._settings)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            status, payload = TRANSPORT(method, url, headers, data, CALL_TIMEOUT)
        except OSError as exc:
            raise SddError(
                "daemon_running", f"The daemon on {self._base} did not answer: {exc}."
            ) from None
        if status < 400:
            return payload
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("code"):
            raise SddError(
                str(error["code"]),
                str(error.get("message", "")),
                retryable=error.get("retryable"),
                details=error.get("details") or None,
            )
        raise SddError("invalid_input", f"The daemon answered HTTP {status} for {method} {path}.")
