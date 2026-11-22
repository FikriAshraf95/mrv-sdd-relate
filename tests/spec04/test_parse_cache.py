"""SPEC-04 §2 step 3: only changed files are re-parsed (the parse cache of plan M02 §2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sdd.sync import indexer
from tests.conftest import MakeProject
from tests.graph_dump import settings_for, write_files


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap every parser in the ``_PARSERS`` table so each call records its path (counting only)."""
    calls: list[str] = []
    for kind, parser in dict(indexer._PARSERS).items():

        def counted(path: str, text: str, _parser=parser, **options: bool) -> object:  # type: ignore[no-untyped-def]
            calls.append(path)
            return _parser(path, text, **options)

        monkeypatch.setitem(indexer._PARSERS, kind, counted)
    return calls


def test_second_batch_reparses_only_the_changed_file(
    project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = project("tool_style")
    settings = settings_for(root)
    calls = _count_parses(monkeypatch)
    cache: indexer.ParseCache = {}

    first = indexer.analyse(settings, cache=cache)
    total = len(first.files)
    assert sorted(calls) == sorted(f.path for f in first.files)

    calls.clear()
    indexer.analyse(settings, cache=cache)
    assert calls == []  # nothing changed: nothing parsed

    spec = "docs/specs/SPEC-01-timer.md"
    text = (root / spec).read_text(encoding="utf-8")
    write_files(root, {spec: text.replace("120 seconds", "130 seconds")})
    again = indexer.analyse(settings, cache=cache)
    assert calls == [spec]
    assert len(again.files) == total
    assert len(cache) == total


def test_cache_drops_vanished_files_and_follows_the_given_file_set(project: MakeProject) -> None:
    root = project("tool_style")
    settings = settings_for(root)
    cache: indexer.ParseCache = {}
    files = indexer.discover(settings)
    indexer.analyse(settings, cache=cache, files=files)
    assert set(cache) == set(files)

    gone = "docs/milestones/M01-timer.md"
    (root / gone).unlink()
    indexer.analyse(settings, cache=cache, files={p: k for p, k in files.items() if p != gone})
    assert gone not in cache


def test_cached_results_are_not_mutated_by_duplicate_dropping(tmp_path: Path) -> None:
    root = tmp_path / "dups"
    root.mkdir()
    body = "# SPEC-01 — {}\n\n> **Status:** v1\n\n## 1. One\n\nText of {}.\n"
    write_files(
        root,
        {
            "docs/specs/SPEC-01-a.md": body.format("A", "a"),
            "docs/specs/SPEC-01-b.md": body.format("B", "b"),  # the same IDs: this file loses them
        },
    )
    settings = settings_for(root)
    cache: indexer.ParseCache = {}
    first = indexer.analyse(settings, cache=cache)
    assert {w.code for w in first.warnings} >= {"duplicate_id"}
    loser = next(f for f in first.files if f.path.endswith("-b.md"))
    assert loser.result.nodes == []  # dropped in this analysis...

    pristine = cache["docs/specs/SPEC-01-b.md"][2]
    assert [n.id for n in pristine.nodes] == ["SPEC-01", "SPEC-01#1"]  # ...but not in the cache

    second = indexer.analyse(settings, cache=cache)  # the cached result gives the same answer
    assert [w.code for w in second.warnings] == [w.code for w in first.warnings]
    assert next(f for f in second.files if f.path.endswith("-b.md")).result.nodes == []
