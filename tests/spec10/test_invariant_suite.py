"""SPEC-10 §7 check 2: the invariant suite holds items 1 to 7 of SPEC-10 §4 and passes."""

from __future__ import annotations

import re
from pathlib import Path

from tests.spec_tables import section_text

INVARIANTS = Path(__file__).resolve().parents[1] / "invariants"


def test_spec10_ac02_invariant_suite_is_complete() -> None:
    text = section_text("SPEC-10-testing-and-benchmark.md", "SPEC-10#4")
    listed = [int(n) for n in re.findall(r"^(\d+)\.\s", text, flags=re.M)]
    assert listed == [1, 2, 3, 4, 5, 6, 7]
    for number in listed:
        files = sorted(INVARIANTS.glob(f"test_inv{number:02d}_*.py"))
        assert files, f"invariant {number} has no file in tests/invariants/"
        assert re.search(r"^def test_", files[0].read_text(encoding="utf-8"), re.M), files[0].name
