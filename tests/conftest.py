"""Test host (SPEC-10 §2).

The network is blocked for every test by pytest-socket (``--disable-socket`` in pyproject).
Fixture repos live in ``tests/fixtures/`` and are copied into ``tmp_path``; tests never touch
the reference projects.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

from sdd import config
from sdd.config import Settings
from sdd.daemon import write_daemon_file
from sdd.graph import schema
from sdd.graph.store import Store
from sdd.service import remote
from sdd.service.runtime import Runtime
from sdd.web.api import create_app

FIXTURES = Path(__file__).parent / "fixtures"
collect_ignore = ["fixtures"]  # fixture repos hold test-shaped files; never collect them


@dataclass(frozen=True)
class Commit:
    """One scripted commit: write ``files`` (path → text, ``None`` deletes), then commit."""

    message: str
    files: dict[str, str | None] = field(default_factory=dict)
    author: str = "Test Author <author@example.invalid>"


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_commit_all(repo: Path, commit: Commit, index: int) -> str:
    """Apply ``commit`` to ``repo`` and commit it with a fixed, increasing date."""
    for rel, text in commit.files.items():
        target = repo / rel
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    name, _, email = commit.author.partition(" <")
    stamp = f"2026-11-01T{10 + index // 60:02d}:{index % 60:02d}:00Z"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email.rstrip(">"),
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email.rstrip(">"),
        "GIT_COMMITTER_DATE": stamp,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "--allow-empty", "-m", commit.message, env=env)
    return _git(repo, "rev-parse", "HEAD", env=env)


MakeProject = Callable[..., Path]


@pytest.fixture
def project(tmp_path: Path) -> MakeProject:
    """Factory: ``project("tool_style", git=True, commits=[Commit(...)])`` → a fresh copy.

    With ``git=True`` the copy is ``git init``-ed and its files committed as the first commit
    ("chore: import fixture"); ``commits`` are then applied in order. Dates are fixed, so SHAs
    are deterministic. Uses the git CLI only, no network.
    """
    counter = 0

    def make(
        name: str = "tool_style",
        *,
        git: bool = False,
        commits: Sequence[Commit] = (),
    ) -> Path:
        nonlocal counter
        source = FIXTURES / name
        if not source.is_dir():
            raise ValueError(f"no fixture repo {name!r} in {FIXTURES}")
        counter += 1
        dest = tmp_path / f"{name}-{counter}"
        shutil.copytree(source, dest)
        if git or commits:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            _git(dest, "init", "-q", "-b", "main", env=env)
            git_commit_all(dest, Commit("chore: import fixture"), 0)
            for i, commit in enumerate(commits, start=1):
                git_commit_all(dest, commit, i)
        return dest

    return make


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """A real Relate directory store in ``tmp_path`` with the SPEC-02 §6 schema (SPEC-10 §2).

    Never mocked. Closed (queue drained, checkpointed) after the test.
    """
    st = Store.open(tmp_path / "store" / "graph")
    schema.ensure(st)
    yield st
    st.close()


# ---------------------------------------------------------------- daemon fixtures (M02)

DAEMON_ENV = {
    "SDD_WATCH": "poll",
    "SDD_POLL_INTERVAL": "0.1",
    "SDD_POLL_CODE_INTERVAL": "0.1",
}
FAKE_PORT = 8770

MakeRuntime = Callable[..., Runtime]


def daemon_settings(root: Path, **env: str) -> Settings:
    """Settings for a daemon test: default store inside the project, fast polling."""
    return config.load(root, None, env={**DAEMON_ENV, **env})


@pytest.fixture
def make_runtime(project: MakeProject) -> Iterator[MakeRuntime]:
    """Factory: ``make_runtime("tool_style", toml=None, SDD_TOKEN="x")`` → a started Runtime.

    Each runtime owns a fresh copy of the fixture project and a real store; all are closed after.
    """
    opened: list[Runtime] = []

    def make(name: str = "tool_style", *, toml: str | None = None, **env: str) -> Runtime:
        root = project(name)
        if toml is not None:
            (root / ".sdd").mkdir(exist_ok=True)
            (root / ".sdd" / "config.toml").write_text(toml, encoding="utf-8")
        settings = daemon_settings(root, **env)
        runtime = Runtime.open(settings)
        opened.append(runtime)
        runtime.sync(full=True)
        return runtime

    yield make
    for runtime in opened:
        runtime.close()


@pytest.fixture
def runtime(make_runtime: MakeRuntime) -> Runtime:
    return make_runtime()


@pytest.fixture
def app(runtime: Runtime) -> TestClient:
    """A test client for the API. ``Host: localhost:8770`` so the loopback Host check passes."""
    return TestClient(create_app(runtime), base_url=f"http://localhost:{FAKE_PORT}")


@dataclass
class FakeDaemon:
    client: TestClient
    seen: list[str] = field(default_factory=list)  # "METHOD /path" of every call the CLI made


@pytest.fixture
def fake_daemon(runtime: Runtime, monkeypatch: pytest.MonkeyPatch) -> FakeDaemon:
    """Make ``remote.TRANSPORT`` reach ``runtime``'s API in-process and write its ``daemon.json``.

    No socket is opened. Any other port refuses the connection.
    """
    client = TestClient(create_app(runtime), base_url=f"http://localhost:{FAKE_PORT}")
    fake = FakeDaemon(client)

    def transport(
        method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, Any]:
        parts = urlsplit(url)
        if parts.port != FAKE_PORT:
            raise ConnectionRefusedError(url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        fake.seen.append(f"{method} {parts.path}")
        # the client sets Host from its base_url, like urllib does for 127.0.0.1:<port>
        response = client.request(method, target, headers=dict(headers), content=body)
        return response.status_code, response.json() if response.content else None

    monkeypatch.setattr(remote, "TRANSPORT", transport)
    write_daemon_file(runtime, "127.0.0.1", FAKE_PORT)
    return fake


def wait_for(check: Callable[[], bool], timeout: float = 5.0, step: float = 0.05) -> bool:
    """Poll ``check`` until it is true or ``timeout`` passes (watcher tests: no fixed sleeps)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(step)
    return check()
