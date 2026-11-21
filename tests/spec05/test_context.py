"""SPEC-05 §4 ``get_context`` and tool 6 ``read_section`` (checks 5, 6 and 10)."""

from __future__ import annotations

from typing import Any

import pytest

from sdd.errors import SddError
from sdd.service import context, coordination
from sdd.service.runtime import Runtime
from tests.conftest import MakeRuntime
from tests.spec05.helpers import write_file

# An invented SPEC-00 whose §6 has two long subsections (always included, never governing).
SPEC00 = f"""# SPEC-00 — Overview

> **Status:** v1 (2026-11-02)

## 1. Purpose

Brew tea.

## 6. Conventions

Short.

### 6.1 Names

{"Names are short. " * 120}

### 6.2 Errors

{"Errors carry a code. " * 200}
"""


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["id"] for i in items]


def _rag(make_runtime: MakeRuntime, **kwargs: str) -> Runtime:
    """rag_style with a stable ID on M00's first task (legacy lines have positional IDs, which
    the tools do not take; `sdd ids --write` gives them real ones)."""
    runtime = make_runtime("rag_style", **kwargs)
    rel = "docs/milestones/M00-foundation.md"
    text = (runtime.settings.project_root / rel).read_text(encoding="utf-8")
    write_file(runtime, rel, text.replace("- [ ] `git init`", "- [ ] **M00.1** `git init`"))
    return runtime


def _feature(runtime: Runtime) -> None:
    """A Feature on the walker's File node, as M04b will create it (so `code` has content)."""
    runtime.store.write(
        lambda tx: tx.run(
            "MATCH (p:Spec {id: 'SPEC-01'}) MATCH (x:File {id: 'file:src/kettle/brew.py'}) "
            "CREATE (f:Feature {id: 'feature:brewing', name: 'Brewing', slug: 'brewing'}) "
            "CREATE (f)-[:SPECIFIED_BY {src: 'test'}]->(p) "
            "CREATE (f)-[:IMPLEMENTED_IN {src: 'walker'}]->(x)"
        )
    )


# ---------------------------------------------------------------- get_context


def test_spec05_ac05_open_deviation_on_governing_section(runtime: Runtime) -> None:
    packet = context.get_context(runtime, "M01.1")
    first = packet["sections"][0]
    assert first["id"] == "SPEC-01#1"
    assert first["why"] == "governs task"
    assert first["text"] == "A brew has a tea and a steep time in seconds."
    assert first["amended_by"] == ["D001"]
    [dev] = packet["deviations"]
    assert dev["id"] == "D001"
    assert dev["status"] == "open"
    assert dev["implementation_does"] == "The default comes from a setting."
    assert dev["amends"] == ["SPEC-01#1"]
    # the milestone's other reading is outlined, not included
    assert packet["outline"] == [
        {"id": "SPEC-01#2", "title": "Teas", "why": "milestone reads", "chars": 60}
    ]
    assert packet["task"] == {
        "id": "M01.1",
        "title": "Brew model with default steep times (SPEC-01 §1)",
        "group": "Backend",
        "status": "todo",
        "blocked_by": [],
    }
    assert packet["milestone"]["model"] == "Sonnet"
    assert packet["milestone"]["acceptance"] == ["A green tea brew counts down from 120 seconds."]
    assert packet["size"]["truncated"] == []
    assert packet["size"]["tokens_est"] == -(-packet["size"]["chars"] // 4)
    assert packet["synced_at"]


def test_resolved_deviations_carry_the_title_only(runtime: Runtime) -> None:
    write_file(
        runtime,
        "docs/deviations/D001-steep-time-default.md",
        (runtime.settings.project_root / "docs/deviations/D001-steep-time-default.md")
        .read_text(encoding="utf-8")
        .replace("**Status:** Open", "**Status:** Resolved → spec updated"),
    )
    [dev] = context.get_context(runtime, "M01.1")["deviations"]
    assert dev["status"] == "resolved"
    assert "implementation_does" not in dev


def test_checks_upstream_and_blocked_by(runtime: Runtime) -> None:
    coordination.claim_task(runtime, "M01.1", "sonnet-1")
    coordination.complete_task(
        runtime, "M01.1", "sonnet-1", notes="Model done.", files_touched=["src/kettle/brew.py"]
    )
    packet = context.get_context(runtime, "M01.2", agent="sonnet-2")
    assert packet["task"]["blocked_by"] == ["M01.1"]
    # a task that governs nothing gets the milestone's READS sections instead
    assert [(s["id"], s["why"]) for s in packet["sections"]] == [
        ("SPEC-01#1", "milestone reads"),
        ("SPEC-01#2", "milestone reads"),
    ]
    assert packet["outline"] == []
    upstream = {u["id"]: u for u in packet["upstream"]}
    assert upstream["M01.1"]["notes"] == "Model done."
    assert upstream["M01.1"]["files_touched"] == ["src/kettle/brew.py"]
    assert "M01.4" in upstream  # a done task of the same milestone

    checks = context.get_context(runtime, "M01.4")["checks"]
    assert _ids(checks) == ["SPEC-01#ac1", "SPEC-01#ac2", "SPEC-01#ac3"]
    assert checks[0]["text"] == "A green tea brew defaults to 120 seconds."


def test_sections_come_with_descendants_and_always_include(make_runtime: MakeRuntime) -> None:
    runtime = _rag(make_runtime)
    # M00.1 is governed by SPEC-11 §2; SPEC-00 §6 is always included, with §6.1 and §6.2
    packet = context.get_context(runtime, "M00.1")
    assert [(s["id"], s["why"]) for s in packet["sections"]] == [
        ("SPEC-11#2", "governs task"),
        ("SPEC-00#6", "always include"),
        ("SPEC-00#6.1", "always include (SPEC-00#6)"),
        ("SPEC-00#6.2", "always include (SPEC-00#6)"),
    ]
    # SPEC-02 (whole file) appears as its section list
    assert "SPEC-02#3" in _ids(packet["outline"])
    assert "SPEC-00#6" not in _ids(packet["outline"])

    full = context.get_context(runtime, "M00.1", detail="milestone")
    assert {"SPEC-02#1", "SPEC-02#8"} <= set(_ids(full["sections"]))
    assert full["outline"] == []


def test_always_include_is_configurable(make_runtime: MakeRuntime) -> None:
    runtime = _rag(make_runtime, toml='always_include = ["SPEC-02 `documents`"]\n')
    ids = _ids(context.get_context(runtime, "M00.1")["sections"])
    assert ids == ["SPEC-11#2", "SPEC-02#2"]


def test_spec05_ac06_truncation_order_never_cuts_a_section(runtime: Runtime) -> None:
    write_file(runtime, "docs/specs/SPEC-00-overview.md", SPEC00)
    _feature(runtime)
    full = context.get_context(runtime, "M01.1", max_chars=context.MAX_CHARS)
    assert full["size"]["truncated"] == []
    assert full["code"]["features"] == ["brewing"]
    assert full["code"]["files"] == ["src/kettle/brew.py"]
    assert _ids(full["upstream"]) == ["M01.4"]
    assert _ids(full["outline"]) == ["SPEC-01#2"]
    texts = {s["id"]: s["text"] for s in full["sections"]}
    assert list(texts) == ["SPEC-01#1", "SPEC-00#6", "SPEC-00#6.1", "SPEC-00#6.2"]
    expected = ["code", "upstream", "outline", "SPEC-00#6.2", "SPEC-00#6.1", "SPEC-00#6"]
    top = full["size"]["chars"]
    limits = [*range(top, top - 600, -5), *range(top - 600, context.MIN_CHARS - 1, -100)]
    seen_lengths = set()
    for limit in limits:
        packet = context.get_context(runtime, "M01.1", max_chars=limit)
        dropped = packet["size"]["truncated"]
        assert dropped == expected[: len(dropped)]
        seen_lengths.add(len(dropped))
        if len(dropped) < len(expected):
            assert packet["size"]["chars"] <= limit
        for s in packet["sections"]:
            assert s["text"] == texts[s["id"]]  # whole, never cut
        assert "SPEC-01#1" in _ids(packet["sections"])  # governing: never dropped
        assert set(_ids(packet["sections"])) | set(dropped) >= set(texts)
    # at MIN_CHARS the packet may already fit before the short SPEC-00#6 itself goes
    assert seen_lengths >= set(range(len(expected)))
    smallest = context.get_context(runtime, "M01.1", max_chars=context.MIN_CHARS)
    assert smallest["code"] == {"features": [], "files": [], "tables": [], "recent_commits": []}
    assert smallest["upstream"] == smallest["outline"] == []
    assert _ids(smallest["sections"])[0] == "SPEC-01#1"
    assert not {"SPEC-00#6.1", "SPEC-00#6.2"} & set(_ids(smallest["sections"]))
    assert _ids(smallest["deviations"]) == ["D001"]


def test_get_context_errors(runtime: Runtime) -> None:
    with pytest.raises(SddError) as missing:
        context.get_context(runtime, "M01.99")
    assert missing.value.code == "task_not_found"
    for kwargs in ({"detail": "everything"}, {"max_chars": 10}, {"task_id": "SPEC-01"}):
        with pytest.raises(SddError) as bad:
            context.get_context(runtime, **{"task_id": "M01.1", **kwargs})
        assert bad.value.code == "invalid_input"


# ---------------------------------------------------------------- read_section


def test_spec05_ac10_read_section_range_returns_two_sections(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime("rag_style")
    result = context.read_section(runtime, "SPEC-02 §3–4")
    assert _ids(result["sections"]) == ["SPEC-02#3", "SPEC-02#4"]
    assert result["sections"][0]["title"] == "loans"
    assert result["sections"][0]["spec_id"] == "SPEC-02"
    assert result["synced_at"]


def test_read_section_forms(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime("rag_style")
    assert _ids(context.read_section(runtime, ["SPEC-00 §6"])["sections"]) == [
        "SPEC-00#6",
        "SPEC-00#6.1",
        "SPEC-00#6.2",
    ]
    assert _ids(context.read_section(runtime, ["SPEC-02#3", "SPEC-02 `jobs`"])["sections"]) == [
        "SPEC-02#3",
        "SPEC-02#4",
    ]
    whole = _ids(context.read_section(runtime, "SPEC-00")["sections"])
    assert whole == [
        "SPEC-00#1",
        "SPEC-00#2",
        "SPEC-00#6",
        "SPEC-00#6.1",
        "SPEC-00#6.2",
        "SPEC-00#8",
    ]
    suite = make_runtime("suite_style")
    assert _ids(context.read_section(suite, "SPEC-02 `file_shares`")["sections"]) == [
        "SPEC-02#file_shares"
    ]


def test_read_section_carries_amended_by(runtime: Runtime) -> None:
    [sec] = context.read_section(runtime, "SPEC-01 §1", agent="sonnet-1")["sections"]
    assert sec["amended_by"] == ["D001"]


@pytest.mark.parametrize("ref", ["SPEC-01 §9", "SPEC-09 §1", "SPEC-01 `nothing`", "hello", ""])
def test_read_section_unknown(runtime: Runtime, ref: str) -> None:
    with pytest.raises(SddError) as err:
        context.read_section(runtime, ref)
    assert err.value.code == ("invalid_input" if not ref else "unknown_section")
