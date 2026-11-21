"""config.py and errors.py basics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sdd import config
from sdd.errors import SddError
from tests.conftest import MakeProject


def test_load_walks_up_to_project_root(project: MakeProject) -> None:
    root = project()
    s = config.load(cwd=root / "docs" / "milestones", env={})
    assert s.project_root == root.resolve()
    assert s.store_path == str(root.resolve() / ".sdd" / "graph")
    assert not s.in_memory
    assert s.paths == config.DEFAULT_PATHS
    assert s.writeback is True


def test_load_finds_sdd_dir(tmp_path: Path) -> None:
    (tmp_path / ".sdd").mkdir()
    (tmp_path / "a" / "b").mkdir(parents=True)
    assert config.load(cwd=tmp_path / "a" / "b", env={}).project_root == tmp_path.resolve()


def test_load_without_project_is_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(SddError) as exc:
        config.load(cwd=tmp_path, env={})
    assert exc.value.code == "invalid_input"


def test_memory_store(project: MakeProject) -> None:
    assert config.load(project(), ":memory:", env={}).in_memory


def test_config_toml_overrides(project: MakeProject) -> None:
    root = project()
    (root / ".sdd").mkdir()
    (root / ".sdd" / "config.toml").write_text(
        'specs = "spec/*.md"\nmilestones = ["plan/M*.md"]\nwriteback = false\n'
    )
    s = config.load(root, env={})
    assert s.paths["specs"] == ("spec/*.md",)
    assert s.paths["milestones"] == ("plan/M*.md",)
    assert s.paths["deviations"] == config.DEFAULT_PATHS["deviations"]
    assert s.writeback is False


@pytest.mark.parametrize(
    "body", ["specz = 'x'\n", "writeback = 'no'\n", "specs = 3\n", "not toml ==\n"]
)
def test_bad_config_toml(project: MakeProject, body: str) -> None:
    root = project()
    (root / ".sdd").mkdir()
    (root / ".sdd" / "config.toml").write_text(body)
    with pytest.raises(SddError) as exc:
        config.load(root, env={})
    assert exc.value.code == "invalid_input"


def test_env(project: MakeProject) -> None:
    s = config.load(
        project(),
        env={
            "SDD_WATCH": "POLL",
            "SDD_POLL_INTERVAL": "0.1",
            "SDD_CLAIM_TTL": "60",
            "SDD_TOKEN": "s3cret",
            "SDD_ALLOW_REMOTE": "1",
            "SDD_ALLOWED_HOSTS": "demo.example.org, other.example.org",
            "SDD_REPLAY_SEED": "42",
        },
    )
    assert s.watch == "poll"
    assert s.poll_interval == 0.1
    assert s.claim_ttl == 60
    assert s.allow_remote
    assert s.allowed_hosts == ("demo.example.org", "other.example.org")
    assert s.replay_seed == 42
    assert "s3cret" not in repr(s)  # secrets never in logs


@pytest.mark.parametrize(
    "env", [{"SDD_WATCH": "inotify"}, {"SDD_POLL_INTERVAL": "fast"}, {"SDD_MAX_FILES": "-1"}]
)
def test_bad_env(project: MakeProject, env: dict[str, str]) -> None:
    with pytest.raises(SddError) as exc:
        config.load(project(), env=env)
    assert exc.value.code == "invalid_input"


def test_injected_clock(project: MakeProject) -> None:
    fixed = datetime(2026, 11, 21, 10, 42, 0, tzinfo=UTC)
    s = config.load(project(), env={}, clock=lambda: fixed)
    assert s.now_iso() == "2026-11-21T10:42:00Z"


def test_error_shape() -> None:
    err = SddError("already_claimed", "taken", details={"claimed_by": "sonnet-2"})
    assert err.to_dict() == {
        "error": {
            "code": "already_claimed",
            "message": "taken",
            "retryable": False,
            "details": {"claimed_by": "sonnet-2"},
        }
    }
    assert SddError("write_conflict", "busy").retryable
    with pytest.raises(ValueError, match="unknown error code"):
        SddError("made_up", "x")
