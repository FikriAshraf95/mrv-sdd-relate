"""SPEC-10 §7 checks 3 and 4: ``sdd bench`` on a fixture project (M07.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd.cli import app
from sdd.errors import SddError
from sdd.service import bench
from tests.conftest import MakeProject


def test_spec10_ac03_bench_context_prints_table_and_writes_results(
    project: MakeProject, tmp_path: Path
) -> None:
    root = project("tool_style")
    out = tmp_path / "results"
    res = CliRunner().invoke(app, ["bench", "context", "--project", str(root), "--out", str(out)])
    assert res.exit_code == 0, res.output
    assert "average" in res.output
    assert "M01.1" in res.output
    (js,) = out.glob("*.json")
    (md,) = out.glob("*.md")
    data = json.loads(js.read_text(encoding="utf-8"))["context"]
    assert data["tasks"] == len(data["rows"]) >= 4
    row = data["rows"][0]
    assert row["markdown_tokens"] == bench.tokens_est(row["markdown_chars"])
    assert row["task_chars"] < row["markdown_chars"]
    assert "Graph, `detail=task`" in md.read_text(encoding="utf-8")


def test_bench_context_never_touches_the_project(project: MakeProject) -> None:
    root = project("tool_style")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    bench.bench_context(root, ["m01"])
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_bench_exact_needs_a_key(project: MakeProject, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SddError, match="ANTHROPIC_API_KEY"):
        bench.bench_context(project("tool_style"), exact=True)


def test_bench_restart_reports_the_scripted_edits(project: MakeProject) -> None:
    root = project("tool_style")
    result = bench.bench_restart(root)
    assert result["edits"] == {"sections": 2, "deviations": 1, "tasks_completed": 3}
    assert 0 < result["graph_chars"] < result["markdown_chars"]
    assert "Bench deviation" not in (root / "docs" / "DEVIATIONS.md").read_text()


def test_spec10_ac04_collisions_naive_loses_ticks_graph_none() -> None:
    result = bench.bench_collisions(agents=10, tasks=30, runs=5)
    assert len(result["runs"]) == 5
    assert result["naive_lost_ticks_total"] > 0
    assert result["graph_double_claims_total"] == 0
    assert result["graph_lost_ticks_total"] == 0
