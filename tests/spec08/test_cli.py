"""SPEC-08 §1–2: the ``sdd`` entry point, global options, exit codes."""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from sdd import __version__
from sdd.cli import EXIT_CODES, app, fail
from sdd.errors import CODES, SddError
from sdd.graph.schema import SCHEMA_VERSION
from sdd.graph.store import Store
from tests.conftest import MakeProject

runner = CliRunner()


def test_version_prints_both_versions() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        f"sdd {__version__}",
        f"relate-db {version('relate-db')}",
    ]


def test_version_json() -> None:
    result = runner.invoke(app, ["--json", "--version"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "sdd": __version__,
        "relate_db": version("relate-db"),
    }


def test_global_options_are_accepted() -> None:
    result = runner.invoke(app, ["--project", ".", "--store", ":memory:", "--json", "--version"])
    assert result.exit_code == 0, result.output


def test_no_command_prints_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "--project" in result.stdout
    assert "--store" in result.stdout
    assert "--json" in result.stdout


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        ("invalid_input", 2),
        ("ambiguous_target", 2),
        ("task_not_found", 3),
        ("unknown_section", 3),
        ("already_claimed", 4),
        ("daemon_running", 4),
        ("write_conflict", 5),
        ("query_rejected", 1),
    ],
)
def test_exit_codes(code: str, exit_code: int, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit) as exc:
        fail(SddError(code, "boom"), as_json=True)
    assert exc.value.exit_code == exit_code
    assert json.loads(capsys.readouterr().out)["error"]["code"] == code


def test_exit_code_table_uses_known_codes() -> None:
    assert set(EXIT_CODES) <= CODES
    # every *_not_found code exits 3
    assert all(EXIT_CODES[c] == 3 for c in CODES if c.endswith("_not_found"))


# ---------------------------------------------------------------- sdd info


def test_info_on_missing_store_prints_zero_counts(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    store = tmp_path / "s"
    result = runner.invoke(app, ["info", "--project", str(root), "--store", str(store)])
    assert result.exit_code == 0, result.output
    lines = dict(line.split(None, 1) for line in result.stdout.splitlines() if " " in line)
    assert lines["nodes"].strip() == "0"
    assert lines["relationships"].strip() == "0"
    assert lines["schema"].split() == ["version", str(SCHEMA_VERSION), "(store:", "not", "set)"]
    assert not store.exists()  # a read command creates nothing


def test_info_json_counts(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    path = tmp_path / "s"
    with Store.open(path) as st:
        st.write(
            lambda tx: tx.run(
                "CREATE (:Milestone {id: 'M01'})-[:INCLUDES]->(:Task {id: 'M01.1'}),"
                " (:Meta {id: 'meta', schema_version: 1})"
            )
        )
    result = runner.invoke(app, ["--json", "info", "--project", str(root), "--store", str(path)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["store_exists"] is True
    assert data["daemon"] is None
    assert data["nodes"] == {"Meta": 1, "Milestone": 1, "Task": 1}
    assert data["relationships"] == {"INCLUDES": 1}
    assert (data["schema_version"], data["store_schema_version"]) == (SCHEMA_VERSION, 1)
    assert data["project"] == str(root)


def test_info_in_memory(project: MakeProject) -> None:
    root = project("tool_style")
    result = runner.invoke(app, ["info", "--json", "--project", str(root), "--store", ":memory:"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["total_nodes"] == 0


def test_info_next_to_a_running_writer(project: MakeProject, tmp_path: Path) -> None:
    root = project("tool_style")
    path = tmp_path / "s"
    with Store.open(path) as st:
        st.write(lambda tx: tx.run("CREATE (:Task {id: 'M01.1'})"))
        result = runner.invoke(
            app, ["--json", "info", "--project", str(root), "--store", str(path)]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["nodes"] == {"Task": 1}
