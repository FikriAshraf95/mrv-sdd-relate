"""SPEC-04 §6 (git sync) and §7 check 9; M04a: a tool-owned ``TOUCHES`` survives a reset that
removes the commit-owned one. Scripted repositories in ``tmp_path`` (the git CLI only)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sdd.graph.store import Store
from sdd.service import coordination as coord
from sdd.service import indexing
from sdd.service.runtime import Runtime
from sdd.sync import git
from tests.conftest import (
    Commit,
    MakeProject,
    _git,
    daemon_settings,
    git_commit_all,
    wait_for,
)
from tests.graph_dump import Sync, settings_for, write_files
from tests.history import TOOL_STYLE_HISTORY

WALKER = Commit(
    "feat: walker [M01.2]",
    {"src/kettle/brew.py": "GREEN_TEA_SECONDS = 120\n", "src/kettle/timer.py": "x = 1\n"},
)


def _commits(store: Store) -> dict[str, dict[str, Any]]:
    rows = store.read("MATCH (c:Commit) RETURN c.message AS m, properties(c) AS p")
    return {r["m"]: r["p"] for r in rows}


def _rels(store: Store, type_: str) -> set[tuple[str, str, str]]:
    rows = store.read(
        f"MATCH (a)-[r:{type_}]->(b) RETURN a.id AS a, b.id AS b, r.src AS s ORDER BY a, b"
    )
    return {(r["a"], r["b"], r["s"]) for r in rows}


def _reset_hard(repo: Path, rev: str) -> None:
    _git(repo, "reset", "-q", "--hard", rev)


def test_spec04_ac09_commit_completes_touches_and_reset_removes(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=(*TOOL_STYLE_HISTORY, WALKER))
    sync = Sync(root, store)
    report = sync.full()
    assert report.git is not None
    assert report.git.added == 6
    commits = _commits(store)
    walker_sha = commits["feat: walker [M01.2]"]["sha"]
    src = f"git:{walker_sha}"
    assert ("commit:" + walker_sha, "M01.2", src) in _rels(store, "COMPLETES")
    touches = {(a, b) for a, b, s in _rels(store, "TOUCHES") if s == src}
    assert touches == {
        ("M01.2", "file:src/kettle/brew.py"),
        ("M01.2", "file:src/kettle/timer.py"),
    }
    changed = {
        (b, s): r["c"]
        for a, b, s in _rels(store, "CHANGED")
        if a == f"commit:{walker_sha}"
        for r in store.read(
            "MATCH (:Commit {sha: $sha})-[r:CHANGED]->(:File {id: $f}) RETURN r.change AS c",
            {"sha": walker_sha, "f": b},
        )
    }
    assert changed == {
        ("file:src/kettle/brew.py", src): "M",
        ("file:src/kettle/timer.py", src): "A",
    }

    _reset_hard(root, "HEAD~1")
    after = sync.head()
    assert after.git is not None
    assert after.git.removed == 1
    assert "feat: walker [M01.2]" not in _commits(store)
    assert not [r for r in _rels(store, "TOUCHES") if r[2] == src]
    assert not [r for r in _rels(store, "CHANGED") if r[2] == src]
    assert not [r for r in _rels(store, "COMPLETES") if r[2] == src]
    assert f"commit:{walker_sha}" in after.changed_ids
    assert len(_commits(store)) == 5


def test_m04a_tool_touches_survive_reset(project: MakeProject) -> None:
    root = project("tool_style", commits=(*TOOL_STYLE_HISTORY, WALKER))
    runtime = Runtime.open(daemon_settings(root))
    try:
        runtime.sync(full=True)
        coord.claim_task(runtime, "M01.1", "sonnet-1")
        coord.complete_task(runtime, "M01.1", "sonnet-1")  # M01.2 waits for it
        coord.claim_task(runtime, "M01.2", "sonnet-1")
        coord.complete_task(runtime, "M01.2", "sonnet-1", files_touched=["src/kettle/brew.py"])
        store = runtime.store
        before = _rels(store, "TOUCHES")
        assert ("M01.2", "file:src/kettle/brew.py", "tool") in before
        assert any(r[0] == "M01.2" and r[2].startswith("git:") for r in before)
        _reset_hard(root, "HEAD~1")
        report = runtime.sync(full=False, git=True)
        assert report["git"]["removed"] == 1
        after = _rels(store, "TOUCHES")
        assert ("M01.2", "file:src/kettle/brew.py", "tool") in after
        assert not [r for r in after if r[0] == "M01.2" and r[2].startswith("git:")]
    finally:
        runtime.close()


def test_commit_nodes_hold_name_only_utc_time_and_every_path(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    Sync(root, store).full()
    row = store.read("MATCH (c:Commit {message: 'feat: loader [M02.1]'}) RETURN properties(c) AS p")
    p = row[0]["p"]
    assert p["author"] == "Test Author"  # no email: the graph can be public
    assert "@" not in str(p)
    assert p["at"].endswith("Z")
    assert p["at"].startswith("2026-11-01T")
    assert p["short"] == p["sha"][:7]
    assert len(p["sha"]) == 40
    assert p["paths"] == ["src/ingest/loader.py"]
    assert p["id"] == f"commit:{p['sha']}"


def test_part_of_a_milestone_only_when_there_is_no_task_id(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    Sync(root, store).full()
    by_message = {m: p["sha"] for m, p in _commits(store).items()}
    tidy = f"commit:{by_message['chore: tidy (M02)']}"
    part_of = _rels(store, "PART_OF")
    assert (tidy, "M02", f"git:{by_message['chore: tidy (M02)']}") in part_of
    assert not [r for r in _rels(store, "COMPLETES") if r[0] == tidy]
    brew = f"commit:{by_message['feat: brew model [M01.1]']}"
    assert [r for r in _rels(store, "COMPLETES") if r[0] == brew]
    assert not [r for r in part_of if r[0] == brew]
    readme = f"commit:{by_message['docs: readme']}"
    assert not [r for r in part_of if r[0] == readme]
    assert not [r for r in _rels(store, "COMPLETES") if r[0] == readme]


def test_parents_form_the_history(project: MakeProject, store: Store) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    Sync(root, store).full()
    parents = _rels(store, "PARENT")
    assert len(parents) == 4  # five commits, the first has no parent
    assert all(s == f"git:{a.removeprefix('commit:')}" for a, _, s in parents)


def test_a_missing_task_or_milestone_gets_no_link_and_no_unresolved(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=(Commit("feat: x [M09.9]", {"x.txt": "x\n"}),))
    Sync(root, store).full()
    assert not _rels(store, "COMPLETES")
    assert not store.read("MATCH (n) WHERE n.unresolved IS NOT NULL AND n:Commit RETURN n")


def test_first_sync_keeps_only_the_newest_commits(project: MakeProject, store: Store) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    sync = Sync(root, store, git_max_commits=2)
    report = sync.full()
    assert report.git is not None
    assert report.git.added == 2
    assert set(_commits(store)) == {"chore: tidy (M02)", "docs: readme"}


def test_the_next_sync_reads_only_new_commits(project: MakeProject, store: Store) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    sync = Sync(root, store)
    sync.full()
    again = sync.head()
    assert again.git is not None
    assert (again.git.added, again.git.removed) == (0, 0)
    # a commit that creates a file: the File node exists before the CHANGED link is made
    git_commit_all(root, Commit("feat: timer [M01.3]", {"src/kettle/timer.py": "x = 1\n"}), 20)
    report = sync.head()
    assert report.git is not None
    assert report.git.added == 1
    assert report.code is not None
    assert report.code.added == 1
    sha = _git(root, "rev-parse", "HEAD")
    assert ("commit:" + sha, "file:src/kettle/timer.py", f"git:{sha}") in _rels(store, "CHANGED")
    assert ("M01.3", "file:src/kettle/timer.py", f"git:{sha}") in _rels(store, "TOUCHES")
    meta = store.read("MATCH (m:Meta {id: 'meta'}) RETURN m.last_git_sha AS s")
    assert meta == [{"s": sha}]


def test_a_new_test_file_in_a_commit_gets_its_tests_links(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    sync = Sync(root, store)
    sync.full()
    new_test = Commit(
        "test: more", {"tests/test_more.py": "def test_spec01_ac3_pause():\n    pass\n"}
    )
    git_commit_all(root, new_test, 20)
    sync.head()
    rows = store.read("MATCH (f:File {path: 'tests/test_more.py'})-[:TESTS]->(c) RETURN c.id AS c")
    assert rows == [{"c": "SPEC-01#ac3"}]


def test_a_rewrite_with_new_commits_replaces_the_stale_ones(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=(*TOOL_STYLE_HISTORY, WALKER))
    sync = Sync(root, store)
    sync.full()
    old = _commits(store)["feat: walker [M01.2]"]["sha"]
    _reset_hard(root, "HEAD~1")
    git_commit_all(
        root, Commit("feat: other walker [M01.3]", {"src/kettle/other.py": "y = 2\n"}), 30
    )
    report = sync.head()
    assert report.git is not None
    assert (report.git.added, report.git.removed) == (1, 1)
    messages = set(_commits(store))
    assert "feat: walker [M01.2]" not in messages
    assert "feat: other walker [M01.3]" in messages
    assert not [r for r in _rels(store, "TOUCHES") if r[2] == f"git:{old}"]
    assert [r for r in _rels(store, "COMPLETES") if r[1] == "M01.3"]


def test_a_project_without_git_syncs_with_git_none(project: MakeProject, store: Store) -> None:
    report = Sync(project("tool_style"), store).full()
    assert report.git is None
    assert report.code is not None
    assert report.code.added > 0
    assert not store.read("MATCH (c:Commit) RETURN c")


def test_a_repository_without_commits_is_skipped(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    assert Sync(root, store).full().git is None


def test_a_project_inside_a_larger_repository_is_skipped(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    inner = root / "sub"
    write_files(root, {"sub/docs/specs/SPEC-01-x.md": "# SPEC-01 — X\n\n## 1. A\n\nText.\n"})
    assert Sync(inner, store).full().git is None  # paths would not match the project's


def test_log_parses_renames_copies_and_deletes(project: MakeProject) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    _git(root, "mv", "src/util/misc.py", "src/util/other.py")
    git_commit_all(root, Commit("refactor: rename misc [M02.2]"), 20)
    git_commit_all(root, Commit("chore: drop", {"src/kettle/__init__.py": None}), 21)
    commits = git.log_commits(root, "HEAD", 10)
    rename, drop = commits[-2], commits[-1]
    assert rename.changes == [("R", "src/util/other.py")]
    assert rename.paths == ["src/util/misc.py", "src/util/other.py"]
    assert drop.changes == [("D", "src/kettle/__init__.py")]
    assert rename.at.endswith("Z")


def test_task_ids_in_a_subject() -> None:
    assert git.task_ids("feat: x [M02.3] and [m4a.1]") == (["M02.3"], [])  # lower case is no ID
    assert git.task_ids("feat: x [M04a.4] [M02.3]") == (["M04a.4", "M02.3"], [])
    assert git.task_ids("chore: tidy (M20f)") == ([], ["M20f"])
    assert git.task_ids("docs: close M03b") == ([], ["M03b"])
    assert git.task_ids("feat: both [M01.1] (M02)") == (["M01.1"], [])
    assert git.task_ids("docs: nothing here") == ([], [])


def test_head_poller_calls_back_on_a_new_commit(project: MakeProject) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    seen: list[str] = []
    poller = git.HeadPoller(root, seen.append, interval=0.05)
    poller.start()
    try:
        assert not wait_for(lambda: bool(seen), timeout=0.3)  # nothing moved yet
        sha = git_commit_all(root, Commit("feat: more [M01.3]", {"a.txt": "a\n"}), 20)
        assert wait_for(lambda: seen == [sha])
    finally:
        poller.stop()
    assert seen == [sha]  # reported once


def test_the_sync_result_carries_code_and_git(project: MakeProject) -> None:
    root = project("tool_style", commits=TOOL_STYLE_HISTORY)
    result = indexing.sync(settings_for(root))
    assert result["code"]["added"] > 0
    assert result["git"]["added"] == 5
    assert result["git"]["head"] == _git(root, "rev-parse", "HEAD")
    bare = indexing.sync(settings_for(project("tool_style")))
    assert bare["git"] is None
    assert bare["code"]["added"] > 0
