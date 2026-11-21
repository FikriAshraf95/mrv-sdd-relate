"""SPEC-10 §4 invariant 1: ``relate`` is imported only in ``graph/store.py``.

Independent of import-linter: scans the source with ``ast``, so dynamic forms like
``importlib.import_module("relate")`` are caught too.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "sdd"
ALLOWED = SRC / "graph" / "store.py"


def _imports_relate(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "relate" or a.name.startswith("relate.") for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and (mod == "relate" or mod.startswith("relate.")):
                lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute | ast.Name)
            and (getattr(node.func, "attr", None) or getattr(node.func, "id", None))
            in ("import_module", "__import__")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and str(node.args[0].value).split(".")[0] == "relate"
        ):
            lines.append(node.lineno)
    return lines


def test_invariant_01_relate_only_in_store() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path == ALLOWED:
            continue
        for line in _imports_relate(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.relative_to(SRC.parent)}:{line}")
    assert offenders == [], f"relate imported outside graph/store.py: {offenders}"


def test_invariant_01_scanner_detects_forms() -> None:
    src = "import relate\nfrom relate.types import X\nimportlib.import_module('relate')\n"
    assert _imports_relate(ast.parse(src)) == [1, 2, 3]
    assert _imports_relate(ast.parse("import relational\nfrom . import relate\n")) == []
