"""SPEC-11 §6 and §9 check 5 (the files part), M08: ``sdd site`` builds the static demo.

Builds from the committed sample store into ``tmp_path``: local files and the git CLI, no network.
The WASM files are stubs (the real package is fetched by the Pages workflow). What the browser
does with the site is checked by hand (SPEC-11 §9 check 5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sdd import config
from sdd.cli import app as cli_app
from sdd.errors import SddError
from sdd.service import impact
from sdd.service.runtime import Runtime
from sdd.site import META_TAG, build_site

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "samples" / "courtside"


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("site") / "site"
    build_site(SAMPLE, out)
    return out


def data(site: Path, *parts: str) -> object:
    return json.loads((site.joinpath("data", *parts)).read_text(encoding="utf-8"))


def stub_wasm(root: Path, *, skip: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("relate.js", "relate_bg.wasm", "trap.js"):
        if name != skip:
            (root / name).write_bytes(b"stub " + name.encode())
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_spec11_ac05_static_site_impact_centrepiece(site: Path) -> None:
    index = data(site, "index.json")
    assert isinstance(index, dict)
    target = "table:bookings"
    served = data(site, "impact", index["impact"][target])
    runtime = Runtime.open_public(config.load(SAMPLE, str(SAMPLE / ".sdd" / "graph"), env={}))
    try:
        expected = json.loads(json.dumps(impact.impact(runtime, target, 3)))
    finally:
        runtime.close()
    assert served == expected
    assert f"impact:{target}" in index["preset"]
    page = (site / "index.html").read_text(encoding="utf-8")
    assert META_TAG in page
    assert page.count("sdd-backend") == 1
    for kind, files in index.items():
        for name in files.values():
            assert (site / "data" / kind / name).is_file()
    manifest = data(site, "manifest.json")
    assert isinstance(manifest, dict)
    assert manifest["wasm"] is False
    assert manifest["centrepiece"] == target
    assert (site / ".nojekyll").is_file()
    assert (site / "static.js").is_file()
    assert (site / "relate-worker.js").is_file()
    graph_files = ("graph3d.js", "graph2d.js", "graph-layout.worker.js", "vendor/MANIFEST.json")
    for name in (*graph_files, "vendor/three/three.module.js"):
        assert (site / name).is_file(), name
    assert not (site / "wasm").exists()


def test_site_answers_cover_the_dashboard(site: Path) -> None:
    index = data(site, "index.json")
    assert isinstance(index, dict)
    assert {"default", "M05a"} <= set(index["board"])
    assert "schema" in index["preset"]
    assert "milestone:M05a" in index["preset"]
    assert any(k.startswith("lineage:") for k in index["preset"])
    assert any(k.startswith("explain:") for k in index["preset"])
    assert len(index["query"]) == 6
    health = data(site, "health.json")
    assert isinstance(health, dict)
    assert health["mode"] == "static"
    assert health["public_query"] == "presets"
    manifest = data(site, "manifest.json")
    assert isinstance(manifest, dict)
    graph = data(site, "graph.json")
    assert isinstance(graph, dict)
    assert len(graph["nodes"]) == manifest["counts"]["nodes"]
    cypher = (site / "data" / "graph.cypher").read_text(encoding="utf-8")
    assert cypher.startswith("// sdd export --cypher")


def test_site_build_is_deterministic(site: Path, tmp_path: Path) -> None:
    again = tmp_path / "again"
    build_site(SAMPLE, again)
    assert tree(again / "data") == tree(site / "data")


def test_site_copies_the_wasm_files(tmp_path: Path) -> None:
    result = build_site(SAMPLE, tmp_path / "out", wasm_dir=stub_wasm(tmp_path / "pkg"))
    assert result["backend_files"] == {"wasm": True}
    assert (tmp_path / "out" / "wasm" / "relate_bg.wasm").read_bytes() == b"stub relate_bg.wasm"
    manifest = data(tmp_path / "out", "manifest.json")
    assert isinstance(manifest, dict)
    assert manifest["wasm"] is True


def test_site_wasm_dir_missing_a_file_is_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(SddError) as err:
        build_site(SAMPLE, tmp_path / "out", wasm_dir=stub_wasm(tmp_path / "pkg", skip="trap.js"))
    assert err.value.code == "invalid_input"
    assert not (tmp_path / "out").exists()


def test_site_replay_recording(site: Path) -> None:
    replay = data(site, "replay.json")
    assert isinstance(replay, dict)
    assert replay["seed"] == 1
    for milestone, board in replay["start"].items():
        assert board["milestone"]["id"] == milestone
        assert board["columns"]["claimed"] == []
        assert board["columns"]["done"] == []
        assert board["columns"]["todo"]
    events = replay["events"]
    assert events
    assert events[-1]["type"] == "milestone"
    assert events[-1]["data"]["status"] == "done"
    assert {e["type"] for e in events} == {"task", "deviation", "milestone"}
    assert all("failed" not in json.dumps(e) for e in events)
    claims = [e for e in events if e["type"] == "task" and e["data"]["status"] == "claimed"]
    dones = [e for e in events if e["type"] == "task" and e["data"]["status"] == "done"]
    assert (
        len(claims)
        == len(dones)
        == sum(len(b["columns"]["todo"]) for b in replay["start"].values())
    )


def test_site_replay_same_seed_same_file(site: Path, tmp_path: Path) -> None:
    build_site(SAMPLE, tmp_path / "again", seed=1)
    assert (tmp_path / "again" / "data" / "replay.json").read_bytes() == (
        site / "data" / "replay.json"
    ).read_bytes()


def test_site_refuses_dangerous_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    for bad in (ROOT, ROOT / "src", Path(".")):
        with pytest.raises(SddError) as err:
            build_site(SAMPLE, bad)
        assert err.value.code == "invalid_input"
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SddError) as err:
        build_site(SAMPLE, other)
    assert err.value.code == "invalid_input"
    assert (other / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_site_rebuilds_over_a_previous_site(site: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    build_site(SAMPLE, out)
    (out / "stale.txt").write_text("x", encoding="utf-8")
    build_site(SAMPLE, out)
    assert not (out / "stale.txt").exists()


def test_sdd_site_command_json(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_app, ["--json", "site", "--sample", str(SAMPLE), "--out", str(tmp_path / "s")]
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["nodes"] > 0
    assert body["answers"] > 0
    assert body["backend_files"] == {"wasm": False}


def test_examples_are_stored_once() -> None:
    """The Query tab's examples live in examples.json only (query.js fetches it)."""
    static = ROOT / "src" / "sdd" / "web" / "static"
    examples = json.loads((static / "examples.json").read_text(encoding="utf-8"))
    assert len(examples) == 6
    assert "MATCH (t:Task)" not in (static / "query.js").read_text(encoding="utf-8")
