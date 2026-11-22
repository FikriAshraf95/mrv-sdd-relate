"""SPEC-05 §4 item 5: the ``code`` part of a context packet, on real synced data (M04b.6)."""

from __future__ import annotations

from pathlib import Path

from sdd.service import context
from sdd.service.runtime import Runtime
from tests.conftest import Commit, git_commit_all
from tests.graph_dump import write_files
from tests.spec06.conftest import MakeHistory


def test_code_part_of_a_task_governed_by_a_feature_spec(hist: Runtime) -> None:
    code = context.get_context(hist, "M01.1")["code"]
    assert code["features"] == ["brewing"]
    assert "src/kettle/brew.py" in code["files"]
    assert code["files"] == ["src/kettle/__init__.py", "src/kettle/brew.py"]
    assert code["tables"] == []  # brews and teas are defined nowhere, so nothing to link
    assert {"short": code["recent_commits"][0]["short"], "message": "feat: brew model [M01.1]"} in [
        {"short": c["short"], "message": c["message"]} for c in code["recent_commits"]
    ]


def test_code_part_with_a_table_mention(hist: Runtime) -> None:
    code = context.get_context(hist, "M02.1")["code"]
    assert code["tables"] == ["documents"]  # the task line mentions `documents`
    assert code["features"] == ["ingestion"]
    assert code["files"] == [
        "src/ingest/__init__.py",
        "src/ingest/chunker.py",
        "src/ingest/loader.py",
    ]
    messages = [c["message"] for c in code["recent_commits"]]
    assert messages == ["chore: tidy (M02)", "feat: loader [M02.1]", "chore: import fixture"]


def test_file_and_commit_caps(history_runtime: MakeHistory) -> None:
    def many(root: Path) -> None:
        write_files(root, {f"src/ingest/gen/g{i:03}.py": f"x = {i}\n" for i in range(60)})

    runtime = history_runtime(before=many)
    code = context.get_context(runtime, "M02.1")["code"]
    assert len(code["files"]) == context.MAX_FILES == 50
    assert code["files"] == sorted(code["files"])

    # six more commits changing the loader: only the newest five are listed
    root = runtime.settings.project_root
    for i in range(1, 7):
        change: dict[str, str | None] = {"src/ingest/loader.py": f"x = {i}\n"}
        git_commit_all(root, Commit(f"fix: loader {i}", change), 20 + i)
    runtime.sync(full=True)
    recent = context.get_context(runtime, "M02.1")["code"]["recent_commits"]
    assert len(recent) == context.MAX_COMMITS == 5
    assert [c["message"] for c in recent] == [f"fix: loader {i}" for i in range(6, 1, -1)]
