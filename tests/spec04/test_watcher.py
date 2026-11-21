"""SPEC-04 §1 (the watcher) and §7 check 1 (a host edit reaches the graph within 3 s).

Poll mode only: the tests never rely on inotify. Polls are driven by hand (``poll_once``) where
that is deterministic, and by the real threads where timing is the point.
"""

from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path

from sdd import config
from sdd.service.runtime import Runtime
from sdd.sync.watcher import Batch, Watcher, glob_bases
from tests.conftest import MakeProject, MakeRuntime, daemon_settings, wait_for


def _write(root: Path, rel: str, text: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def _watcher(root: Path, on_batch: object = None, *, debounce: float = 0.1) -> Watcher:
    batches: list[Batch] = []
    cb = on_batch if callable(on_batch) else batches.append
    return Watcher(daemon_settings(root), cb, debounce=debounce)


# ---------------------------------------------------------------- polling


def test_poll_detects_create_modify_delete(project: MakeProject) -> None:
    root = project("tool_style")
    watcher = _watcher(root)
    watcher.poll_once(code=True)  # the initial snapshot
    assert watcher.poll_once(code=True) == set()

    _write(root, "src/kettle/new.py", "x = 1\n")
    assert watcher.poll_once(code=True) == {"src/kettle/new.py"}

    _write(root, "src/kettle/new.py", "x = 12345\n")  # a different size, whatever the mtime
    assert watcher.poll_once(code=True) == {"src/kettle/new.py"}

    (root / "src/kettle/new.py").unlink()
    assert watcher.poll_once(code=True) == {"src/kettle/new.py"}


def test_sdd_poll_sees_new_edited_and_deleted_documents(project: MakeProject) -> None:
    root = project("tool_style")
    watcher = _watcher(root)
    watcher.poll_once(code=True)
    assert "docs/specs/SPEC-01-timer.md" in watcher.sdd_files()

    _write(root, "docs/specs/SPEC-02-new.md", "# SPEC-02 — New\n\n## 1. One\n\nText.\n")
    assert watcher.poll_once(code=False) == {"docs/specs/SPEC-02-new.md"}
    assert watcher.sdd_files()["docs/specs/SPEC-02-new.md"] == "spec"

    spec = root / "docs/specs/SPEC-01-timer.md"
    spec.write_text(spec.read_text(encoding="utf-8") + "\nMore text here.\n", encoding="utf-8")
    assert watcher.poll_once(code=False) == {"docs/specs/SPEC-01-timer.md"}

    (root / "docs/specs/SPEC-02-new.md").unlink()
    assert watcher.poll_once(code=False) == {"docs/specs/SPEC-02-new.md"}
    assert "docs/specs/SPEC-02-new.md" not in watcher.sdd_files()
    # the code poll has nothing left to report: the SDD poll already updated the snapshot
    assert watcher.poll_once(code=True) == set()


def test_ignored_folders_are_never_reported(project: MakeProject) -> None:
    root = project("tool_style")
    watcher = _watcher(root)
    watcher.poll_once(code=True)
    _write(root, ".sdd/note.md", "x")
    _write(root, ".git/HEAD", "ref")
    _write(root, "node_modules/pkg/README.md", "# pkg")
    _write(root, "src/__pycache__/m.pyc", "x")
    _write(root, "docs/specs/.hidden.md", "x")
    assert watcher.poll_once(code=True) == set()
    assert watcher.poll_once(code=False) == set()


def test_nested_claude_md_is_found_by_the_code_poll_only(project: MakeProject) -> None:
    root = project("tool_style")
    watcher = _watcher(root)
    watcher.poll_once(code=True)
    _write(root, "src/kettle/CLAUDE.md", "# Kettle rules\n")
    assert watcher.poll_once(code=False) == set()
    assert "src/kettle/CLAUDE.md" not in watcher.sdd_files()
    assert watcher.poll_once(code=True) == {"src/kettle/CLAUDE.md"}
    assert watcher.sdd_files()["src/kettle/CLAUDE.md"] == "doc"


def test_glob_bases_follow_the_polling_rule(project: MakeProject) -> None:
    settings = config.load(project("tool_style"), None, env={})
    bases = glob_bases(settings)
    assert bases["docs/milestones"] is True  # `docs/milestones/**/M*.md`: walked recursively
    assert bases["docs/specs"] is False  # `docs/specs/SPEC-*.md`: one level
    assert bases[""] is False  # `**/CLAUDE.md`, HANDOFF.md, README.md: the root, one level


def test_debounce_merges_a_burst_into_one_batch(project: MakeProject) -> None:
    root = project("tool_style")
    batches: list[Batch] = []
    watcher = Watcher(daemon_settings(root), batches.append, debounce=0.6)
    watcher.start()
    try:
        for n in range(3):  # three edits, each in a later poll, all inside one debounce window
            _write(root, f"src/kettle/f{n}.py", f"x = {n}\n")
            threading.Event().wait(0.2)
        assert wait_for(lambda: len(batches) >= 1, timeout=5)
        threading.Event().wait(1.0)  # nothing else follows
    finally:
        watcher.stop()
    assert len(batches) == 1
    assert batches[0].paths == {f"src/kettle/f{n}.py" for n in range(3)}


def test_batches_never_overlap_and_a_failing_batch_does_not_stop_the_watcher(
    project: MakeProject,
) -> None:
    root = project("tool_style")
    seen: list[frozenset[str]] = []

    def on_batch(batch: Batch) -> None:
        seen.append(batch.paths)
        raise RuntimeError("boom")

    watcher = Watcher(daemon_settings(root), on_batch, debounce=0.1)
    watcher.start()
    try:
        _write(root, "src/kettle/a.py", "a = 1\n")
        assert wait_for(lambda: len(seen) == 1)
        _write(root, "src/kettle/b.py", "b = 1\n")
        assert wait_for(lambda: len(seen) == 2)
    finally:
        watcher.stop()
    assert seen == [frozenset({"src/kettle/a.py"}), frozenset({"src/kettle/b.py"})]


def test_auto_mode_polls_in_a_container_and_native_otherwise(project: MakeProject) -> None:
    root = project("tool_style")
    base = daemon_settings(root)
    from dataclasses import replace  # noqa: PLC0415

    assert Watcher(replace(base, watch="auto", in_container=True), lambda b: None).mode == "poll"
    assert Watcher(replace(base, watch="auto", in_container=False), lambda b: None).mode == "native"
    assert Watcher(replace(base, watch="native"), lambda b: None).mode == "native"


# ---------------------------------------------------------------- SPEC-04 §7 check 1


def _section(runtime: Runtime, section: str) -> dict[str, object]:
    rows = runtime.store.read(
        "MATCH (s:Section {id: $id}) RETURN s.text AS text, s.changed_at AS changed_at",
        {"id": section},
    )
    return rows[0]


def test_spec04_ac01_host_edit_updates_section_within_3s(runtime: Runtime) -> None:
    root = runtime.settings.project_root
    loop = asyncio.new_event_loop()
    sub = runtime.events.subscribe(loop)
    watcher = Watcher(runtime.settings, runtime.on_batch, debounce=0.1)
    watcher.start()
    try:
        before = {
            s: _section(runtime, s)["changed_at"] for s in ("SPEC-01#1", "SPEC-01#2", "SPEC-01#3")
        }
        assert set(before.values()) == {None}  # the startup sync was initial

        spec = root / "docs/specs/SPEC-01-timer.md"
        text = spec.read_text(encoding="utf-8")
        edited = text.replace("A brew has a tea", "A brew always has a tea")
        assert edited != text
        spec.write_bytes(edited.replace("\n", os.linesep).encode("utf-8"))  # like an editor save

        assert wait_for(lambda: "always" in str(_section(runtime, "SPEC-01#1")["text"]), timeout=3)
        assert _section(runtime, "SPEC-01#1")["changed_at"] is not None
        assert _section(runtime, "SPEC-01#2")["changed_at"] is None
        assert _section(runtime, "SPEC-01#3")["changed_at"] is None

        type_, data = loop.run_until_complete(asyncio.wait_for(sub.get(), 3))
        assert type_ == "graph_changed"
        assert "SPEC-01#1" in data["ids"]
        assert "Section" in data["kinds"]
    finally:
        watcher.stop()
        sub.close()
        loop.close()


def test_a_batch_with_no_sdd_path_does_not_sync(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime()
    synced = runtime.synced_at
    runtime.on_batch(Batch(frozenset({"src/kettle/brew.py"}), {}))
    assert runtime.synced_at == synced
