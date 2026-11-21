"""SPEC-10 §2 test host and §7 check 1."""

from __future__ import annotations

import socket
import subprocess
from pathlib import Path

import pytest
from pytest_socket import SocketBlockedError

from tests.conftest import Commit, MakeProject


@pytest.mark.filterwarnings("ignore:A test tried to use socket:UserWarning")
def test_spec10_ac01_network_blocked() -> None:
    with pytest.raises(SocketBlockedError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)  # TEST-NET-1, never routed
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_project_fixture_copies_into_tmp(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    assert root.parent == tmp_path
    assert (root / "docs" / "specs" / "SPEC-01-timer.md").is_file()
    assert not (root / ".git").exists()
    # copies are independent
    (root / "CLAUDE.md").write_text("changed")
    assert project("tool_style").joinpath("CLAUDE.md").read_text() != "changed"


def test_project_fixture_scripted_git_is_deterministic(project: MakeProject) -> None:
    commits = [
        Commit("feat: brew model [M01.1]", {"src/kettle/model.py": "TEAS = ['green']\n"}),
        Commit("chore: drop model", {"src/kettle/model.py": None}),
    ]
    a, b = project(git=True, commits=commits), project(git=True, commits=commits)

    def log(repo: Path) -> list[str]:
        out = subprocess.run(
            ["git", "log", "--format=%H %aI %s"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.splitlines()

    assert log(a) == log(b)
    assert [line.split(" ", 2)[2] for line in log(a)] == [
        "chore: drop model",
        "feat: brew model [M01.1]",
        "chore: import fixture",
    ]
    assert not (a / "src" / "kettle" / "model.py").exists()
