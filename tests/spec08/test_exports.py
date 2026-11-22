"""SPEC-08 §4 checks 4–7: Mermaid, Cypher, CLAUDE.md status block and snapshot (M06a.5).

Real stores on ``tool_style`` (with its scripted history); copies live in ``tmp_path``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sdd.cli import app
from sdd.errors import SddError
from sdd.graph import schema, store
from sdd.service import exports, snapshot
from sdd.service.runtime import Runtime
from tests.conftest import FakeDaemon, MakeProject, daemon_settings

runner = CliRunner()
GOLDEN = Path(__file__).parent / "golden"
UPDATE = os.environ.get("SDD_UPDATE_GOLDEN") == "1"


def _golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if UPDATE:
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.read_text(encoding="utf-8") == text


def _node(label: str, ident: str, title: str | None = None) -> dict[str, Any]:
    return {"id": ident, "label": label, "title": title or ident, "props": {"id": ident}}


# ---------------------------------------------------------------- check 4: Mermaid


def test_spec08_ac04_mermaid_presets_match_golden(hist: Runtime) -> None:
    _golden("schema.mmd", exports.export_mermaid(hist, "schema"))
    _golden("impact_documents.mmd", exports.export_mermaid(hist, "impact:documents"))


def test_spec08_ac04_mermaid_starts_at_the_root_and_is_deterministic(hist: Runtime) -> None:
    first = exports.export_mermaid(hist, "impact:documents")
    assert first == exports.export_mermaid(hist, "impact:documents")
    lines = first.splitlines()
    assert lines[0] == "flowchart LR"
    assert lines[1] == '    n0[("table:documents: documents")]'  # the target is n0, a Table
    assert first.endswith("\n")


def test_spec08_ac04_mermaid_shapes_escaping_and_classes() -> None:
    graph = {
        "nodes": [
            _node("Table", "table:t"),
            _node("Spec", "SPEC-01", 'Say "hi" <b>'),
            _node("Section", "SPEC-01#1", "line\nbreak"),
            _node("Task", "M01.1"),
            _node("Deviation", "D001"),
            _node("File", "file:a.py"),
            _node("Milestone", "M01"),
            _node("Feature", "feature:f"),
            _node("Commit", "commit:abc"),
        ],
        "edges": [
            {"source": "M01", "target": "M01.1", "type": "INCLUDES"},
            {"source": "M01.1", "target": "ghost", "type": "X"},
        ],
    }
    lines = exports.render_mermaid(graph).splitlines()
    # the root is first; the rest sort by (label, id)
    assert lines[1:10] == [
        '    n0[("table:t")]',
        '    n1["commit:abc"]',
        '    n2{{"D001"}}',
        '    n3>"feature:f"]',
        '    n4[/"file:a.py"/]',
        '    n5(["M01"])',
        '    n6["SPEC-01#1: line break"]',
        '    n7[["SPEC-01: Say #quot;hi#quot; #lt;b#gt;"]]',
        '    n8("M01.1")',
    ]
    assert "    n5 -->|INCLUDES| n8" in lines
    assert not any("ghost" in line for line in lines)
    assert "    classDef table fill:#4ade80,stroke:#15803d,color:#111" in lines
    assert "    class n0 table" in lines
    assert "    class n6 section" in lines


def test_spec08_ac04_mermaid_truncates_at_sixty_nodes() -> None:
    nodes = [_node("Task", f"M01.{i}") for i in range(1, 62)]
    edges = [{"source": "M01.1", "target": "M01.9", "type": "BLOCKED_BY"}]
    text = exports.render_mermaid({"nodes": nodes, "edges": edges})
    drawn = [ln for ln in text.splitlines() if ln.startswith("    n") and '("' in ln]
    assert len(drawn) == 60
    assert text.splitlines()[-1] == "%% truncated 1 nodes"
    assert "BLOCKED_BY" not in text  # its target (M01.9 sorts last) was dropped
    assert "%%" not in exports.render_mermaid({"nodes": nodes[:60], "edges": []})


def test_spec08_ac04_mermaid_long_labels_and_counts() -> None:
    long_id = "file:" + "x" * 90
    graph = {
        "nodes": [_node("Label", "Task", "Task (12)"), _node("File", long_id)],
        "edges": [{"source": "Task", "target": long_id, "type": "TOUCHES", "count": 3}],
    }
    lines = exports.render_mermaid(graph).splitlines()
    assert '    n0["Task (12)"]' in lines  # the schema labels show their title
    assert any(line.endswith('…"/]') for line in lines)
    assert '    n0 -->|"TOUCHES (3)"| n1' in lines


def test_spec08_ac04_mermaid_argument_detection() -> None:
    assert exports.is_cypher("MATCH (n) RETURN n")
    assert exports.is_cypher("  optional   match (n) RETURN n")
    assert exports.is_cypher("WITH 1 AS x RETURN x")
    assert not exports.is_cypher("schema")
    assert not exports.is_cypher("impact:documents")
    assert not exports.is_cypher("matches")


def test_spec08_ac04_mermaid_from_cypher(hist: Runtime) -> None:
    text = exports.export_mermaid(
        hist,
        "MATCH (m:Milestone {id: 'M02'})-[r:INCLUDES]->(t:Task) "
        "RETURN m.id AS source, t.id AS target, type(r) AS type",
    )
    lines = text.splitlines()
    assert lines[0] == "flowchart LR"
    assert lines[1].startswith('    n0(["M02')  # the first node of the first row is the root
    assert any("-->|INCLUDES|" in line for line in lines)
    nodes_only = exports.export_mermaid(hist, "MATCH (t:Task {id: 'M02.1'}) RETURN t")
    assert "-->" not in nodes_only
    assert 'n0("M02.1' in nodes_only
    with pytest.raises(SddError) as err:
        exports.export_mermaid(hist, "MATCH (n) DETACH DELETE n")
    assert err.value.code == "query_rejected"


def test_spec08_ac04_export_mermaid_command(project: MakeProject, tmp_path: Path) -> None:
    root = str(project("tool_style"))
    base = ["--project", root, "--store", ":memory:"]
    out = tmp_path / "out" / "schema.mmd"
    result = runner.invoke(app, ["export", "--mermaid", "schema", "--out", str(out), *base])
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("flowchart LR\n")
    stdout = runner.invoke(app, ["export", "--mermaid", "schema", *base])
    assert stdout.stdout == out.read_text(encoding="utf-8")
    assert runner.invoke(app, ["export", *base]).exit_code == 2
    assert runner.invoke(app, ["export", "--cypher", "--json", *base]).exit_code == 2
    assert runner.invoke(app, ["export", "--mermaid", "milestone:M99", *base]).exit_code == 3


# ---------------------------------------------------------------- check 5: Cypher


def _counts(st: store.Store) -> tuple[dict[str, int], dict[str, int]]:
    found = schema.counts(st)
    return found.nodes, found.relationships


def test_spec08_ac05_cypher_reproduces_the_counts(hist: Runtime) -> None:
    script = exports.export_cypher(hist)
    lines = script.split("\n")
    assert lines[0].startswith("// sdd export --cypher · ")
    statements = [ln for ln in lines if ln and not ln.startswith("//")]
    assert all(ln.endswith(";") for ln in statements)
    assert script == exports.export_cypher(hist)  # nothing time-dependent
    with store.Store.open(":memory:") as fresh:
        assert exports.load_cypher(fresh, script) == len(statements)
        assert _counts(fresh) == _counts(hist.store)
        exports.load_cypher(fresh, script)  # idempotent
        assert _counts(fresh) == _counts(hist.store)


def test_spec08_ac05_cypher_round_trips_json_props_and_awkward_strings(hist: Runtime) -> None:
    awkward = "it's a \\ back\nslash, a tab\t, \r, and `ticks`   done"
    hist.store.write(
        lambda tx: tx.run(
            "MATCH (s:Spec {id: 'SPEC-01'}) SET s.note = $note, s.`odd key` = 'v'",
            {"note": awkward},
        )
    )
    script = exports.export_cypher(hist)
    with store.Store.open(":memory:") as fresh:
        exports.load_cypher(fresh, script)
        query = "MATCH (s:Spec {id: 'SPEC-01'}) RETURN properties(s) AS p"
        (row,) = fresh.read(query)
        (orig,) = hist.store.read(query)
        props = row["p"]
        assert props["note"] == awkward
        assert props["odd key"] == "v"
        assert isinstance(props["header"], dict)  # header_json came back as a map
        assert props == orig["p"]


def test_spec08_ac05_export_json(hist: Runtime) -> None:
    data = json.loads(exports.export_json(hist))
    ids = [n["id"] for n in data["nodes"]]
    assert ids == sorted(ids)
    assert {"id", "label", "title", "props"} <= set(data["nodes"][0])
    assert data["edges"] == sorted(
        data["edges"], key=lambda e: (e["source"], e["type"], e["target"])
    )
    assert len(data["nodes"]) == sum(_counts(hist.store)[0].values())


# ---------------------------------------------------------------- check 6: CLAUDE.md block

BEFORE = "# Guide\n\nHand-written intro.\n\n## Status\n\n"
BETWEEN = "old line one\nold line two\n"
AFTER = "\nHand-written outro.\n\n- keep `me`\n"
OPEN, CLOSE = "<!-- sdd:status -->\n", "<!-- /sdd:status -->\n"


def _guide() -> str:
    return f"{BEFORE}{OPEN}{BETWEEN}{CLOSE}{AFTER}"


def _status_runtime(project: MakeProject, claude: str | None) -> tuple[Runtime, Path]:
    root = project("tool_style")
    path = root / "CLAUDE.md"
    m01 = root / "docs" / "milestones" / "M01-timer.md"
    m01.write_text(
        m01.read_text(encoding="utf-8").replace("**Status:**", "**Status:** DONE (2026-01-02)."),
        encoding="utf-8",
        newline="\n",
    )
    if claude is not None:
        path.write_bytes(claude.encode("utf-8"))
    runtime = Runtime.open(daemon_settings(root))
    runtime.sync(full=True)
    return runtime, path


def test_spec08_ac06_claude_status_changes_only_the_markers(project: MakeProject) -> None:
    runtime, path = _status_runtime(project, _guide())
    try:
        runtime.store.write(
            lambda tx: tx.run(
                "MATCH (t:Task {id: 'M02.1'}) SET t.claimed_by = 'sonnet-1', t.status = 'claimed'"
            )
        )
        assert exports.claude_status(runtime) == {"path": "CLAUDE.md", "changed": True}
        text = path.read_text(encoding="utf-8")
        assert text.startswith(BEFORE + OPEN)
        assert text.endswith(CLOSE + AFTER)
        block = text[len(BEFORE + OPEN) : -len(CLOSE + AFTER)]
        assert "old line" not in block
        assert block.splitlines()[0].startswith("_Generated by `sdd export --claude-status`")
        assert "- **Done:** M01 Timer (2026-01-02)\n" in block
        assert "- **Next:** [M02 Ingestion](docs/milestones/M02-ingestion.md) (3/3 tasks" in block
        assert "Read first: SPEC-02 §2 · SPEC-02 §3\n" in block
        assert "D002 Document titles may be empty (M02)" in block
        assert "- **Active claims:** M02.1 by sonnet-1" in block
        assert exports.claude_status(runtime) == {"path": "CLAUDE.md", "changed": False}
        assert path.read_text(encoding="utf-8") == text
    finally:
        runtime.close()


def test_spec08_ac06_claude_status_keeps_crlf(project: MakeProject) -> None:
    runtime, path = _status_runtime(project, _guide().replace("\n", "\r\n"))
    try:
        exports.claude_status(runtime)
        data = path.read_bytes()
        assert data.count(b"\r\n") == data.count(b"\n")
        assert data.startswith(BEFORE.replace("\n", "\r\n").encode())
    finally:
        runtime.close()


def test_spec08_ac06_claude_status_without_markers_is_invalid_input(
    project: MakeProject,
) -> None:
    runtime, path = _status_runtime(project, "# Guide\n\nNo markers here.\n")
    try:
        with pytest.raises(SddError) as err:
            exports.claude_status(runtime)
        assert err.value.code == "invalid_input"
        assert "<!-- sdd:status -->" in err.value.message
        assert path.read_text(encoding="utf-8") == "# Guide\n\nNo markers here.\n"
    finally:
        runtime.close()
    root = project("tool_style")
    (root / "CLAUDE.md").unlink()
    result = runner.invoke(
        app, ["export", "--claude-status", "--project", str(root), "--store", ":memory:"]
    )
    assert result.exit_code == 2
    assert "sdd:status" in result.output


def test_spec08_ac06_claude_status_command(project: MakeProject) -> None:
    root = project("tool_style")
    (root / "CLAUDE.md").write_text(_guide(), encoding="utf-8", newline="\n")
    args = ["export", "--claude-status", "--project", str(root), "--store", ":memory:"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert "updated" in first.stdout
    assert "already up to date" in runner.invoke(app, args).stdout


# ---------------------------------------------------------------- check 7: snapshot


def _check_copy(path: Path, live: tuple[dict[str, int], dict[str, int]]) -> None:
    with store.Store.open(path, read_only=True) as st:
        assert _counts(st) == live


def test_spec08_ac07_snapshot_copies_open_read_only_with_the_live_counts(
    runtime: Runtime, fake_daemon: FakeDaemon, tmp_path: Path
) -> None:
    out = tmp_path / "snaps"
    result = snapshot.snapshot(runtime.settings, out)
    live = _counts(runtime.store)
    assert result["total_nodes"] == sum(live[0].values())
    _check_copy(out / "graph", live)
    assert list(out.rglob(".cypherlite.writer")) == []
    assert (out / "graph" / ".cypherlite.lock").is_file()
    assert (out / "graph" / "wal" / ".cypherlite.lock").is_file()
    if store.relate_cli() is None:
        pytest.skip("the relate CLI is not on PATH")
    assert result["checkpointed"] is False  # a daemon holds the store: clone reads its WAL
    assert result["copies"] == {"graph": "written", "graph_rl": "written", "graph_json": "written"}
    assert (out / "graph.rl").is_file()
    assert (out / "graph-json" / "graph.json").is_file()
    _check_copy(out / "graph.rl", live)
    _check_copy(out / "graph-json", live)
    again = snapshot.snapshot(runtime.settings, out)  # replaces the copies
    assert again["total_nodes"] == result["total_nodes"]
    _check_copy(out / "graph", live)


def test_spec08_ac07_snapshot_checkpoints_without_a_daemon(
    runtime: Runtime, tmp_path: Path
) -> None:
    settings = runtime.settings
    live = _counts(runtime.store)
    runtime.close()
    result = snapshot.snapshot(settings, tmp_path / "snaps")
    assert result["checkpointed"] is True
    _check_copy(tmp_path / "snaps" / "graph", live)
    default = snapshot.snapshot(settings)  # default folder: <project>/.sdd/snapshots
    assert Path(default["out"]) == settings.project_root.resolve() / ".sdd" / "snapshots"


def test_spec08_ac07_snapshot_refuses_memory_and_a_busy_store(
    runtime: Runtime, tmp_path: Path
) -> None:
    root = str(runtime.settings.project_root)
    result = runner.invoke(app, ["snapshot", "--project", root, "--store", ":memory:", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_input"
    # the runtime holds the writer and no daemon answers: the checkpoint cannot open the store
    with pytest.raises(SddError) as err:
        snapshot.snapshot(runtime.settings, tmp_path / "snaps")
    assert err.value.code == "daemon_running"


def test_spec08_ac07_snapshot_command(
    runtime: Runtime, fake_daemon: FakeDaemon, tmp_path: Path
) -> None:
    root = str(runtime.settings.project_root)
    result = runner.invoke(app, ["snapshot", "--out", str(tmp_path / "s"), "--project", root])
    assert result.exit_code == 0, result.output
    assert "nodes" in result.stdout
    assert (tmp_path / "s" / "graph").is_dir()


def test_spec08_ac07_copy_store_fallback_without_the_cli(runtime: Runtime, tmp_path: Path) -> None:
    settings = runtime.settings
    live = _counts(runtime.store)
    runtime.close()
    store.copy_store(settings.store_path, tmp_path / "copy")
    assert list((tmp_path / "copy").rglob(".cypherlite.writer")) == []
    _check_copy(tmp_path / "copy", live)
