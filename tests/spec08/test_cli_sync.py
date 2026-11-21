"""SPEC-08 §4 check 3 and the M01b commands: ``sdd sync``, ``status``, ``doctor``, ``ids``."""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from sdd.cli import app
from tests.conftest import MakeProject
from tests.graph_dump import write_files

runner = CliRunner()


def _run(*args: str, input_: str | None = None) -> tuple[int, str]:
    result = runner.invoke(app, list(args), input=input_)
    return result.exit_code, result.output


def _json(*args: str) -> dict[str, object]:
    code, out = _run("--json", *args)
    assert code == 0, out
    parsed: dict[str, object] = json.loads(out)
    return parsed


# ---------------------------------------------------------------- sdd ids --write


def test_spec08_ac03_ids_write_suite_fixture(project: MakeProject) -> None:
    root = project("suite_style")
    # one file keeps CRLF line endings
    m17 = root / "docs/milestones/M17-photo-attachments.md"
    original = m17.read_text(encoding="utf-8")
    m17.write_bytes(original.replace("\n", "\r\n").encode("utf-8"))
    untouched = {p: p.read_bytes() for p in (root / "docs/milestones").glob("M20f*.md")}

    code, out = _run("ids", "--write", "--yes", "--project", str(root), "--store", ":memory:")
    assert code == 0, out

    after = m17.read_bytes()
    assert b"\r\n" in after
    assert b"\n" not in after.replace(b"\r\n", b"")  # no lone LF
    new = after.decode("utf-8").replace("\r\n", "\n")
    assert re.findall(r"\*\*(M17\.\d+)\*\*", new) == ["M17.1", "M17.2", "M17.3"]
    # the only change is the inserted ID on each legacy line
    assert re.sub(r"\*\*M17\.\d+\*\* ", "", new) == original
    assert {p: p.read_bytes() for p in untouched} == untouched  # stable IDs: not rewritten

    # every legacy task has an ID now, and a re-sync has no task_unstable_id warning
    synced = _json("sync", "--project", str(root), "--store", ":memory:")
    codes = {w["code"] for w in synced["warnings"]}  # type: ignore[attr-defined]
    assert "task_unstable_id" not in codes
    assert _json("doctor", "--project", str(root))["counts"]["legacy_task_lines"] == 0  # type: ignore[index]

    # a second run finds nothing to do
    snapshot = {p: p.read_bytes() for p in root.rglob("*.md")}
    code, out = _run("ids", "--write", "--yes", "--project", str(root))
    assert code == 0
    assert "No legacy task lines." in out
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == snapshot


def test_ids_without_write_only_shows_the_diff(project: MakeProject) -> None:
    root = project("suite_style")
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    code, out = _run("ids", "--project", str(root))
    assert code == 0
    assert "+- [x] **M17.1** Store uploaded photos on disk" in out
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before


def test_ids_asks_before_writing_and_json_needs_yes(project: MakeProject) -> None:
    root = project("suite_style")
    before = {p: p.read_bytes() for p in root.rglob("*.md")}
    code, out = _run("ids", "--write", "--project", str(root), input_="n\n")
    assert code == 1
    assert {p: p.read_bytes() for p in root.rglob("*.md")} == before
    code, out = _run("--json", "ids", "--write", "--project", str(root))
    assert code == 2
    assert json.loads(out)["error"]["code"] == "invalid_input"


def test_ids_unknown_milestone_is_not_found(project: MakeProject) -> None:
    code, out = _run("--json", "ids", "--milestone", "M99", "--project", str(project("rag_style")))
    assert code == 3
    assert json.loads(out)["error"]["code"] == "milestone_not_found"


# ---------------------------------------------------------------- sync, status, doctor


def test_sync_in_memory_prints_counts_and_writes_nothing(
    project: MakeProject, tmp_path: Path
) -> None:
    root = project("rag_style")
    code, out = _run("sync", "--project", str(root), "--store", ":memory:")
    assert code == 0, out
    assert "initial sync: 13 files scanned" in out
    assert "task_unstable_id" in out
    assert not (root / ".sdd").exists()


def test_sync_json_and_second_run_is_a_noop(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    store = str(tmp_path / "graph")
    first = _json("sync", "--project", str(root), "--store", store)
    assert first["initial"] is True
    assert first["unresolved_total"] == 2
    assert first["events"] == 0
    second = _json("sync", "--project", str(root), "--store", store)
    assert second["initial"] is False
    assert (second["changed"], second["removed"], second["relinked"]) == ([], [], 0)
    assert second["nodes"] == first["nodes"]
    assert second["relationships"] == first["relationships"]


def test_sync_reset_json_requires_yes(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    store = str(tmp_path / "graph")
    _json("sync", "--project", str(root), "--store", store)
    code, out = _run("--json", "sync", "--reset", "--project", str(root), "--store", store)
    assert code == 2
    assert json.loads(out)["error"]["code"] == "invalid_input"
    again = _json("sync", "--reset", "--yes", "--project", str(root), "--store", store)
    assert again["initial"] is True  # emptied in place, then synced from scratch
    assert again["created"] > 0


def test_status_lists_milestones_and_tasks(project: MakeProject) -> None:
    root = project("tool_style")
    data = _json("status", "--project", str(root), "--store", ":memory:")
    milestones = data["milestones"]
    assert [m["id"] for m in milestones] == ["M01"]  # type: ignore[index]
    m01 = milestones[0]  # type: ignore[index]
    assert (m01["done"], m01["total"]) == (1, 4)
    assert [t["id"] for t in m01["tasks"]] == ["M01.1", "M01.2", "M01.3", "M01.4"]
    assert data["writeback"] is True
    assert data["claims"] == []
    assert set(data) == {
        "milestones",
        "claims",
        "unresolved",
        "warnings",
        "unticked_completed",
        "writeback",
    }
    code, out = _run("status", "--project", str(root), "--store", ":memory:")
    assert code == 0
    assert "M01 Timer [in_progress] 1/4" in out
    assert "[x] M01.4" in out


def test_status_reads_a_synced_store_and_needs_one(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    store = str(tmp_path / "graph")
    code, out = _run("--json", "status", "--project", str(root), "--store", store)
    assert code == 2
    assert "sdd sync" in json.loads(out)["error"]["message"]
    _json("sync", "--project", str(root), "--store", store)
    data = _json("status", "--project", str(root), "--store", store)
    assert [m["id"] for m in data["milestones"]] == ["M01"]  # type: ignore[attr-defined,index]
    assert data["unresolved"] == {"D001": ["brews", "src/kettle/brew.py"]}


def test_doctor_exit_codes(project: MakeProject) -> None:
    root = project("tool_style")
    code, out = _run("doctor", "--project", str(root))
    assert code == 0, out
    assert "warnings: 0 error" in out
    write_files(root, {"docs/specs/SPEC-x-broken.md": "# nothing\n"})
    code, out = _run("doctor", "--project", str(root))
    assert code == 1
    assert "error bad_filename" in out
    data = json.loads(_run("--json", "doctor", "--project", str(root))[1])
    assert data["ok"] is False
    assert data["warnings_by_severity"]["error"] == 1


def test_doctor_never_opens_the_store(project: MakeProject, tmp_path: Path) -> None:
    root = project("rag_style")
    store = tmp_path / "graph"
    code, out = _run("doctor", "--project", str(root), "--store", str(store))
    assert code == 0, out
    assert not store.exists()
    counts = _json("doctor", "--project", str(root))["counts"]
    assert counts["milestones"] == 2  # type: ignore[index]
    assert counts["legacy_task_lines"] == 7  # type: ignore[index]
