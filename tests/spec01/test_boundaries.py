"""SPEC-01 §3 module boundaries, enforced by import-linter."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).with_name("lint-imports")


def _lint_imports(cwd: Path, src: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(LINT_IMPORTS), "--no-cache"],
        cwd=cwd,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_spec01_ac06_import_linter_passes() -> None:
    result = _lint_imports(ROOT, ROOT / "src")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "relate is imported only in sdd.graph.store KEPT" in result.stdout


def test_spec01_ac06_contract_catches_relate_outside_store(tmp_path: Path) -> None:
    """The contract must actually bite: a copy of the package importing relate from cli fails."""
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "src" / "sdd" / "sync" / "rogue.py").write_text("import relate\n")
    store = tmp_path / "src" / "sdd" / "graph" / "store.py"
    store.write_text("import relate\n")

    result = _lint_imports(tmp_path, tmp_path / "src")

    assert result.returncode != 0
    assert "relate is imported only in sdd.graph.store BROKEN" in result.stdout
    assert "sdd.sync.rogue -> relate" in result.stdout
    assert "sdd.graph.store -> relate" not in result.stdout
