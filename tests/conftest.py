"""Test host (SPEC-10 §2).

The network is blocked for every test by pytest-socket (``--disable-socket`` in pyproject).
Fixture repos live in ``tests/fixtures/`` and are copied into ``tmp_path``; tests never touch
the reference projects.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


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
