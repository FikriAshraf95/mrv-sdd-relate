"""SPEC-02 §1: ID formats and ``ids.normalise()``."""

from __future__ import annotations

import pytest

from sdd import ids

SHA = "0123456789abcdef0123456789abcdef01234567"
ULID = "01JD7Q8ZK3V5N2X4M6P8R0T2W4"

# canonical ID → (label, typed forms that must normalise to it)
ROUND_TRIPS: dict[str, tuple[str, list[str]]] = {
    "SPEC-03": ("Spec", ["SPEC-03", "spec-03", "SPEC-3", "spec-3", "SPEC 3", " SPEC-03 "]),
    "SPEC-03#5.2": (
        "Section",
        [
            "SPEC-03 §5.2",
            "SPEC-03§5.2",
            "spec-03#5.2",
            "SPEC-3 5.2",
            "SPEC-03 # 5.2",
            "SPEC-3§5.2",
            "SPEC-03#5.2",
        ],
    ),
    "SPEC-03#5": ("Section", ["SPEC-03 §5", "spec-3#5", "SPEC-3 5"]),
    "SPEC-10#4.1.2": ("Section", ["SPEC-10 §4.1.2", "spec-10#4.1.2"]),
    "SPEC-02#attachments": (
        "Section",
        [
            "SPEC-02#attachments",
            "spec-2#Attachments",
            "SPEC-02 §attachments",
            "SPEC-02 attachments",
        ],
    ),
    "SPEC-02#graph-only-state-canonical-list": (
        "Section",
        ["SPEC-02#graph-only-state-canonical-list"],
    ),
    "SPEC-03#ac6": (
        "AcceptanceCheck",
        ["SPEC-03#ac6", "spec-3#AC6", "SPEC-03 ac6", "SPEC-03§ac06"],
    ),
    "SPEC-100": ("Spec", ["SPEC-100", "spec-100"]),
    "M02": ("Milestone", ["M02", "m02", "m2", "M2", "M002"]),
    "M20f": ("Milestone", ["M20f", "m20F", "M20F"]),
    "M100": ("Milestone", ["M100", "m100"]),
    "M00a": ("Milestone", ["M00a", "m0a", "M0A"]),
    "M02.3": ("Task", ["M02.3", "m2.3", "M2.3", "m02.03"]),
    "M20f.12": ("Task", ["M20f.12", "m20F.12"]),
    "D012": ("Deviation", ["D012", "d12", "D12", "d-12", "D0012"]),
    "D100": ("Deviation", ["D100", "d100"]),
    "doc:docs/IDEA.md": ("Doc", ["doc:docs/IDEA.md", "doc:./docs/IDEA.md", "doc:docs\\IDEA.md"]),
    "doc:CLAUDE.md": ("Doc", ["doc:CLAUDE.md"]),
    "dir:src/sdd": ("Folder", ["dir:src/sdd", "dir:src/sdd/", "dir:./src/sdd"]),
    "file:src/sdd/cli.py": ("File", ["file:src/sdd/cli.py", "FILE:src\\sdd\\cli.py"]),
    f"commit:{SHA}": ("Commit", [f"commit:{SHA}", f"commit:{SHA.upper()}"]),
    "table:attachments": ("Table", ["table:attachments", "Table:attachments"]),
    "column:attachments.owner_id": ("Column", ["column:attachments.owner_id"]),
    "feature:file-sharing": ("Feature", ["feature:file-sharing", "feature:File-Sharing"]),
    "domain:billing": ("Domain", ["domain:billing"]),
    "agent:sonnet-2": ("Agent", ["agent:sonnet-2"]),
    f"event:{ULID}": ("Event", [f"event:{ULID}", f"event:{ULID.lower()}"]),
    "meta": ("Meta", ["meta", "Meta"]),
}

CASES = [(canonical, typed) for canonical, (_, forms) in ROUND_TRIPS.items() for typed in forms]


@pytest.mark.parametrize(("canonical", "typed"), CASES)
def test_spec02_ac01_ids_round_trip(canonical: str, typed: str) -> None:
    assert ids.normalise(typed) == canonical
    # canonical IDs are fixed points
    assert ids.normalise(canonical) == canonical
    assert ids.label_of(canonical) == ROUND_TRIPS[canonical][0]


def test_spec02_ac01_every_label_is_covered() -> None:
    labels = {label for label, _ in ROUND_TRIPS.values()}
    assert labels == {
        "Spec", "Section", "AcceptanceCheck", "Milestone", "Task", "Deviation", "Doc",
        "Folder", "File", "Commit", "Table", "Column", "Feature", "Domain", "Agent", "Event",
        "Meta",
    }  # fmt: skip


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "SPEC",
        "SPEC-",
        "SPEC-035.2",  # no separator between spec and section: ambiguous
        "M",
        "M2.x",
        "X12",
        "D",
        "doc:",
        "doc:/etc/passwd",
        "file:C:/x.py",
        "file:../outside.py",
        "commit:abc123",  # not a full sha
        "event:not-a-ulid",
        "column:no_table",
        "feature:has space",
        "unknown:thing",
    ],
)
def test_normalise_rejects(bad: str) -> None:
    with pytest.raises(ids.InvalidIdError):
        ids.normalise(bad)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("SPEC-03-markdown-parsing.md", "SPEC-03"),
        ("SPEC-3-x.md", "SPEC-03"),
        ("M2-x.md", "M02"),
        ("M02-sync-daemon.md", "M02"),
        ("M20f-attachments.md", "M20f"),
        ("M00a-plan.md", "M00a"),
        ("M100-big.md", "M100"),
        ("D12-title.md", "D012"),
        ("docs/deviations/D001-first.md", "D001"),
        ("README.md", None),
        ("Makefile", None),
        ("MEMORY.md", None),
    ],
)
def test_id_from_filename_pads(name: str, expected: str | None) -> None:
    assert ids.id_from_filename(name) == expected
