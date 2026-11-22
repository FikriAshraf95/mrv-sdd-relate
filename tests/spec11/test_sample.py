"""SPEC-11 §5 and M06a: the committed Courtside sample (docs, bundle, built store, snapshots).

These tests read only files committed in this repository, on copies in ``tmp_path``. Rebuild the
sample with ``uv run python scripts/make_sample.py`` when one of them reports a difference.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sdd import config
from sdd.graph import schema, store
from sdd.service import impact, indexing
from sdd.service.runtime import Runtime

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "samples" / "courtside"
BUNDLE = ROOT / "samples" / "courtside.bundle"
SKIP = {".sdd", "__pycache__", ".pytest_cache"}
SKIP_FILES = {"replay.toml"}  # demo tooling (SPEC-11 §5): not in the bundle
GROUPS = (
    "specs",
    "sections",
    "tables",
    "features",
    "files",
    "tasks_open",
    "tasks_done",
    "deviations",
    "tests",
    "commits",
)


def _files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
        and not SKIP & set(p.relative_to(root).parts)
        and p.relative_to(root).as_posix() not in SKIP_FILES
    }


@pytest.fixture
def sample_copy(tmp_path: Path) -> Path:
    """The sample project (docs and code, without ``.sdd``) copied into ``tmp_path``."""
    dest = tmp_path / "courtside"
    shutil.copytree(SAMPLE, dest, ignore=shutil.ignore_patterns(*SKIP))
    return dest


def test_sample_doctor_reports_zero_warnings(sample_copy: Path) -> None:
    report = indexing.doctor(config.load(sample_copy, ":memory:", env={}))
    assert report["warnings_by_severity"] == {"error": 0, "warning": 0, "info": 0}
    assert report["counts"]["unresolved_links"] == 0
    counts = report["counts"]
    assert counts["specs"] == 7
    assert counts["milestones"] == 8
    assert counts["deviations"] == 6
    assert counts["tables"] == 8
    assert counts["legacy_task_lines"] == 0


def test_sample_never_names_the_reference_projects() -> None:
    forbidden = ("office-suite", "office-rag", "attachments")
    for rel, data in _files(SAMPLE).items():
        text = data.decode("utf-8", errors="replace").lower()
        assert not any(word in text for word in forbidden), rel


def test_sample_committed_store_fills_every_impact_group_for_bookings(tmp_path: Path) -> None:
    live = tmp_path / "graph"
    shutil.copytree(SAMPLE / ".sdd" / "graph", live)
    with store.Store.open(live, read_only=True) as st:
        runtime = Runtime(settings=config.load(SAMPLE, ":memory:", env={}), store=st)
        result = impact.impact(runtime, "bookings")
    assert result["target"]["id"] == "table:bookings"
    empty = [g for g in GROUPS if not result["counts"][g]]
    assert not empty, f"empty groups: {empty}"
    commit = result["groups"]["commits"][0]
    assert commit["via"][-2] == "<-COMPLETES"
    tables = {i["id"] for i in result["groups"]["tables"]}
    assert {"table:payments", "table:waitlist_entries", "table:reminders"} <= tables
    deviations = {i["id"] for i in result["groups"]["deviations"]}
    assert {"D002", "D003", "D005", "D006"} <= deviations


def test_sample_snapshot_copies_open_read_only_with_the_same_counts(tmp_path: Path) -> None:
    snaps = SAMPLE / ".sdd" / "snapshots"
    expected = schema.Counts(nodes={}, relationships={})
    with store.Store.open(SAMPLE / ".sdd" / "graph", read_only=True) as st:
        expected = schema.counts(st)
    copies = [snaps / "graph", snaps / "graph.rl", snaps / "graph-json"]
    assert all(c.exists() for c in copies)
    for copy in copies:
        with store.Store.open(copy, read_only=True) as st:
            assert schema.counts(st) == expected, copy.name
    assert not list((SAMPLE / ".sdd").rglob(".cypherlite.writer"))


def test_sample_json_copy_holds_no_absolute_paths() -> None:
    text = (SAMPLE / ".sdd" / "snapshots" / "graph-json" / "graph.json").read_text(encoding="utf-8")
    json.loads(text)
    for fragment in ("/tmp", "/workspace", "make-sample", "C:\\", "/Users/"):
        assert fragment not in text, fragment


def test_sample_bundle_tip_tree_matches_the_sample(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    subprocess.run(
        ["git", "clone", "-q", str(BUNDLE), str(clone)],  # the bundle carries HEAD
        check=True,
        capture_output=True,
        env={**env, "HOME": str(tmp_path)},
    )
    cloned = {
        p.relative_to(clone).as_posix(): p.read_bytes()
        for p in sorted(clone.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(clone).parts
    }
    assert cloned == _files(SAMPLE)
    log = subprocess.run(
        ["git", "-C", str(clone), "log", "--format=%an|%s"],
        check=True,
        capture_output=True,
        text=True,
        env={**env, "HOME": str(tmp_path)},
    ).stdout.splitlines()
    assert len(log) >= 30
    assert any(line.endswith("[M03a.3]") for line in log)
    assert {line.split("|")[0] for line in log} == {"Nadia Okafor", "Tomás Reyes", "Mei Lin Chua"}
