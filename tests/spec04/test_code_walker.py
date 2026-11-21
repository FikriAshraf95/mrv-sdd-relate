"""SPEC-04 §4 (the code walker, TESTS) and §7 check 8; SPEC-02 §8 check 5 (no contents in File
nodes); the M04a.6 scoping rule. Real stores; ``tool_style`` copied into ``tmp_path``."""

from __future__ import annotations

import re
from typing import Any

from sdd.graph.store import Store
from sdd.sync import indexer
from tests.conftest import MakeProject
from tests.graph_dump import Sync, dump, settings_for, write_files


def _files(store: Store) -> dict[str, dict[str, Any]]:
    rows = store.read("MATCH (f:File) RETURN f.path AS path, properties(f) AS p")
    return {r["path"]: r["p"] for r in rows}


def _tests(store: Store) -> set[tuple[str, str]]:
    rows = store.read("MATCH (f:File)-[:TESTS]->(c) RETURN f.path AS f, c.id AS c")
    return {(r["f"], r["c"]) for r in rows}


def test_spec04_ac08_gitignored_and_node_modules_produce_no_file_nodes(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style")
    write_files(
        root,
        {
            "scratch/a.txt": "x\n",
            "x.log": "x\n",
            "node_modules/p/index.js": "x\n",
            ".venv/lib/x.py": "x\n",
            "build/out.py": "x\n",
        },
    )
    Sync(root, store).full()
    files = _files(store)
    for ignored in ("scratch/a.txt", "x.log", "node_modules/p/index.js", ".venv/lib/x.py"):
        assert ignored not in files
    assert "build/out.py" not in files
    loader = files["src/ingest/loader.py"]
    assert loader["language"] == "python"
    assert loader["lines"] == 2
    assert len(loader["content_hash"]) == 64
    assert files["tests/test_brew.py"]["is_test"] is True
    assert files["src/ingest/loader.py"]["is_test"] is False
    assert files["README.txt"]["language"] == "text"
    assert "language" not in files[".gitignore"]  # no extension map entry: the property is absent


def test_dot_folders_are_walked_unless_ignored(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    write_files(root, {".claude/skills/x.md": "# x\n", ".mypy_cache/m.json": "{}\n"})
    write_files(root, {".gitignore": "*.log\nscratch/\n.mypy_cache/\n"})
    Sync(root, store).full()
    files = _files(store)
    assert ".claude/skills/x.md" in files
    assert ".gitignore" in files
    assert ".mypy_cache/m.json" not in files


def test_nested_gitignore_and_sddignore(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    write_files(
        root,
        {
            ".sddignore": "docs/internal/\n",
            "docs/internal/x.txt": "x\n",
            "src/kettle/.gitignore": "*.tmp\n!keep.tmp\n",
            "src/kettle/a.tmp": "x\n",
            "src/kettle/keep.tmp": "x\n",
            "src/ingest/b.tmp": "x\n",
            # a deeper file cannot un-ignore what the root ignored
            "src/ingest/.gitignore": "!x.log\n",
            "src/ingest/x.log": "x\n",
        },
    )
    Sync(root, store).full()
    files = _files(store)
    assert "docs/internal/x.txt" not in files  # .sddignore at the root
    assert "src/kettle/a.tmp" not in files  # nested .gitignore
    assert "src/kettle/keep.tmp" in files  # negation inside one file
    assert "src/ingest/b.tmp" in files  # the nested file does not apply to its sibling folder
    assert "src/ingest/x.log" not in files  # the root `*.log` wins over a deeper negation


def test_gitignore_edit_is_picked_up_by_the_next_sync(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    assert "src/ingest/loader.py" in _files(store)
    write_files(root, {".gitignore": "*.log\nscratch/\nsrc/ingest/\n"})
    report = sync.batch(".gitignore")
    assert report.code is not None
    assert "src/ingest/loader.py" in _files(store)  # a batch re-reads only its paths...
    sync.batch("src/ingest/loader.py", "src/ingest/chunker.py", "src/ingest/__init__.py")
    files = _files(store)  # ...and a path that became ignored is deleted
    assert "src/ingest/loader.py" not in files
    assert ".gitignore" in files


def test_folders_and_contains_without_a_root_folder(project: MakeProject, store: Store) -> None:
    Sync(project("tool_style"), store).full()
    folders = {r["p"] for r in store.read("MATCH (d:Folder) RETURN d.path AS p")}
    assert {"src", "src/ingest", "src/kettle", "docs", "docs/specs"} <= folders
    assert "" not in folders
    pairs = {
        (r["a"], r["b"])
        for r in store.read("MATCH (a:Folder)-[r:CONTAINS]->(b) RETURN a.id AS a, b.id AS b")
    }
    assert ("dir:src", "dir:src/ingest") in pairs
    assert ("dir:src/ingest", "file:src/ingest/loader.py") in pairs
    assert not store.read("MATCH (:Folder)-[:CONTAINS]->(x) WHERE x.path = 'src' RETURN x")
    srcs = {r["s"] for r in store.read("MATCH ()-[r:CONTAINS]->() RETURN r.src AS s")}
    assert srcs == {"walker"}
    # a top-level file has no parent
    assert not store.read("MATCH (:Folder)-[:CONTAINS]->(f:File {id: 'file:README.txt'}) RETURN f")


def test_last_file_going_prunes_its_folders(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    write_files(root, {"src/util/misc.py": None})
    report = sync.batch("src/util/misc.py")
    assert report.code is not None
    assert report.code.removed == 1
    assert "dir:src/util" in report.changed_ids
    assert not store.read("MATCH (d:Folder {path: 'src/util'}) RETURN d")
    assert store.read("MATCH (d:Folder {path: 'src'}) RETURN d")  # still has children
    write_files(root, {"src/deep/er/x.py": "x = 1\n"})
    sync.batch("src/deep/er/x.py")
    assert store.read("MATCH (d:Folder {path: 'src/deep/er'}) RETURN d")
    write_files(root, {"src/deep/er/x.py": None})
    sync.batch("src/deep/er/x.py")
    assert not store.read("MATCH (d:Folder) WHERE d.path STARTS WITH 'src/deep' RETURN d")


def test_resync_of_an_unchanged_repo_writes_nothing(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    before = dump(store, drop_labels={"Meta"})  # Meta.last_full_sync moves by design
    report = sync.full()
    assert report.code is not None
    assert (report.code.added, report.code.updated, report.code.removed) == (0, 0, 0)
    assert report.code.folders == 0
    assert (report.created, report.updated, report.deleted, report.events) == (0, 0, 0, 0)
    assert dump(store, drop_labels={"Meta"}) == before  # last_synced included: nothing was touched
    # a cold cache (a new process) against the stored layer writes nothing either
    fresh = Sync(root, store, clock=sync.clock)
    again = fresh.full()
    assert again.code is not None
    assert (again.code.added, again.code.updated, again.code.removed) == (0, 0, 0)
    assert dump(store, drop_labels={"Meta"}) == before


def test_code_files_are_not_the_markdown_syncs_to_delete(
    project: MakeProject, store: Store
) -> None:
    """M04a.6: with code File nodes present, a Markdown full sync deletes none and re-links 0."""
    root = project("tool_style")
    Sync(root, store).full()
    code_files = {p for p in _files(store) if p.endswith(".py")}
    assert code_files
    report = indexer.sync(store, settings_for(root), full=True)
    assert report.removed == []
    assert report.relinked == 0
    assert code_files <= set(_files(store))
    # and `sdd sync`'s indexer-only path (sync_tx for write-back) is scoped the same way
    again = indexer.sync(store, settings_for(root), full=False)
    assert again.removed == []
    assert again.relinked == 0


def test_a_changed_sdd_document_is_still_resynced_after_the_walker_saw_it(
    project: MakeProject, store: Store
) -> None:
    """The walker never sets content_hash on an SDD document: the indexer's marker stays honest."""
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    spec = "docs/specs/SPEC-01-timer.md"
    text = (root / spec).read_text(encoding="utf-8")
    write_files(root, {spec: text.replace("A brew has a tea", "A brew has one tea")})
    report = sync.batch(spec)
    assert report.changed == [spec]
    row = store.read("MATCH (s:Section {id: 'SPEC-01#1'}) RETURN s.text AS t")
    assert "one tea" in row[0]["t"]


def test_spec02_ac05_no_file_node_holds_contents(project: MakeProject, store: Store) -> None:
    Sync(project("tool_style"), store).full()
    allowed = {
        "id",
        "path",
        "name",
        "language",
        "size",
        "lines",
        "content_hash",
        "is_test",
        "last_synced",
    }
    for path, props in _files(store).items():
        assert set(props) <= allowed, path
        assert "source_path" not in props
        for key, value in props.items():
            if key == "content_hash":
                assert re.fullmatch(r"[0-9a-f]{64}", value), path
            elif isinstance(value, str):
                assert len(value) <= 200, (path, key)


def test_soft_cap_keeps_the_first_files_by_path(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store, max_files=3)
    report = sync.full()
    assert report.code is not None
    assert report.code.capped > 0
    # the cap counts every walked file and keeps the first by path; the indexer still reads every
    # SDD document (discover does not cap), so the specs are parsed whatever the cap says
    assert set(sync.state.code) == {".gitignore", "CLAUDE.md", "README.txt"}
    files = _files(store)
    assert "src/ingest/loader.py" not in files
    assert store.read("MATCH (s:Spec {id: 'SPEC-02'}) RETURN s.id")


def test_a_batch_over_the_cap_evicts_the_last_paths(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    sync.max_files = len(sync.state.code)
    write_files(root, {"zzz/last.py": "x = 1\n", "aaa/first.py": "x = 1\n"})
    report = sync.batch("zzz/last.py", "aaa/first.py")
    assert report.code is not None
    assert report.code.capped == 2
    files = _files(store)
    assert "aaa/first.py" in files
    assert "zzz/last.py" not in files
    assert len(sync.state.code) == sync.max_files


def test_a_code_only_batch_updates_a_file_node(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    write_files(root, {"src/ingest/loader.py": "def load():\n    pass\n\n# more\n"})
    report = sync.batch("src/ingest/loader.py")
    assert report.indexed is False  # no SDD document in the batch
    assert report.code is not None
    assert report.code.updated == 1
    assert "file:src/ingest/loader.py" in report.changed_ids
    assert _files(store)["src/ingest/loader.py"]["lines"] == 4
    noop = sync.batch("src/ingest/loader.py")  # nothing differs now
    assert noop.code is not None
    assert (noop.code.updated, noop.code.added) == (0, 0)


# ---------------------------------------------------------------- TESTS


def test_tests_links_read_the_numbers_as_integers(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    Sync(root, store).full()
    links = _tests(store)
    assert ("tests/test_brew.py", "SPEC-01#ac1") in links  # spec01_ac1
    assert ("tests/test_brew.py", "SPEC-01#ac2") in links  # spec1_ac02
    assert ("tests/test_ingest.py", "SPEC-02#ac1") in links
    assert len(links) == 3


def test_tests_to_an_unknown_check_create_nothing(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    write_files(
        root, {"tests/test_more.py": "def test_spec09_ac01_x():\n    pass\n\n# spec01_ac77\n"}
    )
    sync.batch("tests/test_more.py")
    assert not {t for t in _tests(store) if t[0] == "tests/test_more.py"}


def test_a_check_added_later_gets_its_tests(project: MakeProject, store: Store) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    spec = "docs/specs/SPEC-01-timer.md"
    write_files(root, {"tests/test_late.py": "def test_spec01_ac04_late():\n    pass\n"})
    sync.batch("tests/test_late.py")
    assert ("tests/test_late.py", "SPEC-01#ac4") not in _tests(store)  # no such check yet
    text = (root / spec).read_text(encoding="utf-8")
    write_files(root, {spec: text + "4. A late check.\n"})
    report = sync.batch(spec)  # only the spec changed, yet every test file is rescanned
    assert report.code is not None
    assert report.code.tests_links >= 1
    assert ("tests/test_late.py", "SPEC-01#ac4") in _tests(store)


def test_tests_links_follow_the_file_and_are_rewritten_only_on_a_difference(
    project: MakeProject, store: Store
) -> None:
    root = project("tool_style")
    sync = Sync(root, store)
    sync.full()
    again = sync.full()
    assert again.code is not None
    assert again.code.tests_links == 0
    write_files(root, {"tests/test_ingest.py": "def test_x():\n    pass\n"})
    sync.batch("tests/test_ingest.py")
    assert ("tests/test_ingest.py", "SPEC-02#ac1") not in _tests(store)
    write_files(root, {"tests/test_ingest.py": None})
    sync.batch("tests/test_ingest.py")
    assert not {t for t in _tests(store) if t[0] == "tests/test_ingest.py"}
