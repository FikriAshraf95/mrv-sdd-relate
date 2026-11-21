"""SPEC-04 §5 (write-back): ticking one task box inside a write job, and loop prevention (§5.4)."""

from __future__ import annotations

import pytest

from sdd.errors import SddError
from sdd.service import tasks
from sdd.service.runtime import Runtime
from sdd.sync import indexer, writeback
from tests.conftest import MakeRuntime

MILESTONE = "docs/milestones/M01-timer.md"


def _task(runtime: Runtime, task_id: str) -> dict[str, object]:
    rows = runtime.store.read(
        "MATCH (t:Task {id: $id}) RETURN t.checked AS checked, t.status AS status, "
        "t.done_at AS done_at, t.completed_by AS completed_by, t.claimed_by AS claimed_by",
        {"id": task_id},
    )
    return rows[0]


def _event_count(runtime: Runtime) -> int:
    return int(runtime.store.read("MATCH (e:Event) RETURN count(e) AS n")[0]["n"])


# ---------------------------------------------------------------- check 6


def test_spec04_ac06_tick_one_line_crlf_no_resync(runtime: Runtime) -> None:
    path = runtime.settings.project_root / MILESTONE
    original = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    path.write_bytes(original.replace("\n", "\r\n").encode("utf-8"))
    runtime.sync(full=True)  # the graph now knows the CRLF file
    before = path.read_bytes()

    result = tasks.tick_task(runtime, "M01.1", agent="sonnet-1")
    assert result == {
        "task": "M01.1",
        "path": MILESTONE,
        "changed_file": True,
        "status": "done",
    }

    after = path.read_bytes()
    old_lines, new_lines = before.split(b"\r\n"), after.split(b"\r\n")
    assert len(old_lines) == len(new_lines)  # all endings are still CRLF, final newline kept
    assert b"\n" not in after.replace(b"\r\n", b"")
    diff = [(o, n) for o, n in zip(old_lines, new_lines, strict=True) if o != n]
    assert len(diff) == 1
    assert diff[0][0].startswith(b"- [ ] **M01.1**")
    assert diff[0][1] == diff[0][0].replace(b"[ ]", b"[x]", 1)
    assert after.endswith(b"\r\n") == before.endswith(b"\r\n")

    # the watcher's next batch finds the stored hash equal: nothing to do, no Event
    report = runtime.sync(full=False, files=indexer.discover(runtime.settings))
    assert report["changed"] == []
    assert _event_count(runtime) == 0
    task = _task(runtime, "M01.1")
    assert task["checked"] is True
    assert task["status"] == "done"
    assert task["completed_by"] == "sonnet-1"
    assert task["done_at"] is not None


def test_tick_clears_a_claim_and_publishes_one_graph_changed(runtime: Runtime) -> None:
    from tests.graph_dump import claim  # noqa: PLC0415

    claim(runtime.store, "M01.2", "sonnet-1")
    assert _task(runtime, "M01.2")["status"] == "claimed"
    tasks.tick_task(runtime, "M01.2", agent="sonnet-1")
    task = _task(runtime, "M01.2")
    assert task["claimed_by"] is None
    assert task["status"] == "done"
    assert runtime.store.read("MATCH (:Agent)-[r:CLAIMED]->(:Task) RETURN count(r) AS n") == [
        {"n": 0}
    ]
    milestone = runtime.store.read("MATCH (m:Milestone {id: 'M01'}) RETURN m.status AS s")
    assert milestone == [{"s": "in_progress"}]
    assert _event_count(runtime) == 0  # no human task_completed from the re-parse


def test_tick_twice_is_idempotent(runtime: Runtime) -> None:
    path = runtime.settings.project_root / MILESTONE
    first = tasks.tick_task(runtime, "M01.1")
    after_first = path.read_bytes()
    second = tasks.tick_task(runtime, "M01.1")
    assert first["changed_file"] is True
    assert second["changed_file"] is False
    assert path.read_bytes() == after_first
    assert _task(runtime, "M01.1")["status"] == "done"


def test_tick_follows_a_line_that_moved_by_hand(runtime: Runtime) -> None:
    path = runtime.settings.project_root / MILESTONE
    text = path.read_text(encoding="utf-8")
    path.write_text("A new first line, added by hand.\n\n" + text, encoding="utf-8")  # shifts lines
    tasks.tick_task(runtime, "M01.1")
    new = path.read_text(encoding="utf-8")
    assert "- [x] **M01.1**" in new
    assert "- [ ] **M01.2**" in new  # no other line was touched


def test_removed_line_is_source_changed_and_the_graph_is_unchanged(runtime: Runtime) -> None:
    path = runtime.settings.project_root / MILESTONE
    text = path.read_text(encoding="utf-8")
    kept = "".join(line for line in text.splitlines(keepends=True) if "**M01.1**" not in line)
    path.write_text(kept, encoding="utf-8")
    with pytest.raises(SddError) as err:
        tasks.tick_task(runtime, "M01.1")
    assert err.value.code == "source_changed"
    assert err.value.details == {"task": "M01.1", "path": MILESTONE}
    task = _task(runtime, "M01.1")
    assert (task["checked"], task["status"], task["done_at"]) == (False, "todo", None)
    assert path.read_text(encoding="utf-8") == kept


def test_unknown_and_malformed_ids(runtime: Runtime) -> None:
    with pytest.raises(SddError) as missing:
        tasks.tick_task(runtime, "M01.99")
    assert missing.value.code == "task_not_found"
    with pytest.raises(SddError) as bad:
        tasks.tick_task(runtime, "not an id")
    assert bad.value.code == "invalid_input"


def test_writeback_false_leaves_the_file_alone_and_the_task_done(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime(toml="writeback = false\n")
    path = runtime.settings.project_root / MILESTONE
    before = path.read_bytes()
    result = tasks.tick_task(runtime, "M01.1", agent="sonnet-1")
    assert result["changed_file"] is False
    assert path.read_bytes() == before
    task = _task(runtime, "M01.1")
    assert (task["status"], task["completed_by"]) == ("done", "sonnet-1")
    # a later sync of the unticked line does not revert it (SPEC-04 §2.1)
    runtime.sync(full=True)
    assert _task(runtime, "M01.1")["status"] == "done"
    # the line is still re-located: a removed line is source_changed even without write-back
    kept = "".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines(keepends=True)
        if "**M01.2**" not in line
    )
    path.write_text(kept, encoding="utf-8")
    with pytest.raises(SddError) as err:
        tasks.tick_task(runtime, "M01.2")
    assert err.value.code == "source_changed"


# ---------------------------------------------------------------- tick_line (pure)

TEXT = """# M01 — Timer

## Tasks
- [ ] **M01.1** First
- [X] **M01.2** Second, ticked with a capital
* [ ] **M01.3** Star bullet

```
- [ ] **M01.9** only inside a code fence
```
"""


def test_tick_line_changes_only_the_box_of_that_line() -> None:
    new, changed = writeback.tick_line(MILESTONE, TEXT, "M01.1")
    assert changed
    assert new == TEXT.replace("- [ ] **M01.1**", "- [x] **M01.1**")
    star, changed = writeback.tick_line(MILESTONE, TEXT, "M01.3")
    assert changed
    assert star == TEXT.replace("* [ ] **M01.3**", "* [x] **M01.3**")


def test_tick_line_counts_a_capital_x_as_done() -> None:
    assert writeback.tick_line(MILESTONE, TEXT, "M01.2") == (TEXT, False)


def test_tick_line_ignores_a_code_fence_lookalike() -> None:
    with pytest.raises(SddError) as err:
        writeback.tick_line(MILESTONE, TEXT, "M01.9")
    assert err.value.code == "source_changed"
    new, _ = writeback.tick_line(MILESTONE, TEXT, "M01.1")
    assert "- [ ] **M01.9**" in new  # the fenced line is untouched
