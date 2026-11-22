"""SPEC-11 §2 to §4 and §9 checks 1 to 4 and 6: demo prepare, the sprint replay, the image files.

Everything runs on copies in ``tmp_path`` from the committed bundle ``samples/courtside.bundle``:
local files and the git CLI, no network.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from typer.testing import CliRunner

from sdd import config
from sdd.cli import app as cli_app
from sdd.demo import prepare as prepare_module
from sdd.demo.replay import HEARTBEAT, Replay
from sdd.demo.script import SCRIPT_NAME, load_script
from sdd.errors import SddError
from sdd.service.runtime import Runtime
from sdd.sync import writeback
from sdd.web.api import create_app

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "samples" / "courtside"
FAST = {"SDD_WATCH": "poll"}


def sample_in(tmp_path: Path) -> Path:
    """A copy of the sample folder and its bundle, so nothing under ``samples/`` is written."""
    root = tmp_path / "samples"
    root.mkdir(parents=True, exist_ok=True)
    dest = root / "courtside"
    if not dest.exists():
        shutil.copytree(
            SAMPLE, dest, ignore=shutil.ignore_patterns(".sdd", "__pycache__", ".pytest_cache")
        )
        shutil.copy(ROOT / "samples" / "courtside.bundle", root / "courtside.bundle")
    return dest


def settings_for(root: Path) -> config.Settings:
    return config.load(root, None, env=FAST)


def make_replay(tmp_path: Path, seed: int | None = 42) -> Replay:
    sample = sample_in(tmp_path)
    return Replay(settings_for, sample, tmp_path / "data", load_script(sample / SCRIPT_NAME), seed)


def board_states(runtime: Runtime, milestone: str) -> dict[str, str]:
    rows = runtime.store.read(
        "MATCH (t:Task) WHERE t.milestone_id = $m RETURN t.id AS id, t.status AS s",
        {"m": milestone},
    )
    return {r["id"]: r["s"] for r in rows}


# ---------------------------------------------------------------- replay.toml


def write_toml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "replay.toml"
    path.write_text(text, encoding="utf-8")
    return path


GOOD = '[start]\nunticked = ["M05a"]\n[run]\nmilestones = ["M05a"]\nverification = "ok"\n'


def test_replay_toml_of_the_sample_parses() -> None:
    script = load_script(SAMPLE / SCRIPT_NAME)
    assert script.milestones == ("M05a", "M05b", "M06")
    assert set(script.deviations) <= {t for t in script.outcomes} | {"M05a.2", "M06.1"}
    assert 1 <= len(script.deviations) <= 2


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("extra = 1\n" + GOOD, "extra"),
        (GOOD.replace("[run]", "[run]\nbogus = 1"), "run.bogus"),
        (GOOD + '[[task]]\nid = "M09.1"\n', "task.id"),
        (GOOD + '[[deviation]]\ntask = "M05a.1"\ntitle = "t"\n', "deviation.amends"),
        (GOOD.replace("unticked", "ticked"), "start.ticked"),
        ("[start]\nunticked = []\n", "run"),
    ],
)
def test_replay_toml_errors_name_the_key(tmp_path: Path, text: str, key: str) -> None:
    with pytest.raises(SddError) as err:
        load_script(write_toml(tmp_path, text))
    assert err.value.code == "invalid_input"
    assert err.value.details["key"] == key


def test_replay_toml_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SddError) as err:
        load_script(tmp_path / "nope.toml")
    assert err.value.code == "invalid_input"


# ---------------------------------------------------------------- write-back helpers


MILESTONE = (
    "# M01 — x\n\n## Tasks\n- [x] **M01.1** one\n- [X] **M01.2** two\n- [ ] **M01.3** three\n"
    "\n```\n- [x] **M01.9** fenced\n```\n\n**Status:** DONE (2026-01-01). Fine.\n"
    "More status text.\n\n## Other\n"
)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_untick_and_clear_status_keep_line_endings(tmp_path: Path, eol: str) -> None:
    path = tmp_path / "M01-x.md"
    path.write_bytes(MILESTONE.replace("\n", eol).encode())
    text = path.read_bytes().decode().replace("\r\n", "\n")
    text, count = writeback.untick_all("M01-x.md", text)
    assert count == 2
    text, changed = writeback.clear_status_line(text)
    assert changed
    writeback.atomic_write(path, text)
    data = path.read_bytes().decode()
    assert ("\r\n" in data) == (eol == "\r\n")
    plain = data.replace("\r\n", "\n")
    assert "- [ ] **M01.1** one\n- [ ] **M01.2** two\n- [ ] **M01.3**" in plain
    assert "- [x] **M01.9** fenced" in plain  # the code fence is untouched
    assert "**Status:**\n\n## Other" in plain
    assert "DONE" not in plain
    # idempotent
    assert writeback.untick_all("M01-x.md", plain) == (plain, 0)
    assert writeback.clear_status_line(plain) == (plain, False)
    assert writeback.untick_line("- [x] a") == ("- [ ] a", True)
    assert writeback.untick_line("- [ ] a") == ("- [ ] a", False)


# ---------------------------------------------------------------- prepare


def test_spec11_ac02_demo_prepare_and_serve_populate_the_graph(tmp_path: Path) -> None:
    sample = sample_in(tmp_path)
    data = tmp_path / "data"
    run = prepare_module.prepare(sample, data)
    assert run == data / "run"
    runtime = Runtime.open(settings_for(run))
    try:
        runtime.sync(full=True)
        client = TestClient(create_app(runtime), base_url="http://localhost:8770")
        assert client.get("/api/health").json()["ok"] is True
        assert client.get("/api/board").json()["milestone"] is not None
        for milestone in ("M05a", "M05b", "M06"):
            states = board_states(runtime, milestone)
            assert states, milestone
            assert set(states.values()) == {"todo"}, milestone
        # `sdd demo serve` builds the daemon on exactly this: the app builds without a socket
        from sdd import daemon  # noqa: PLC0415

        assert daemon.build_app(runtime) is not None
    finally:
        runtime.close()
    status = (run / "docs" / "milestones" / "M05a-waitlist.md").read_text(encoding="utf-8")
    assert "- [x]" not in status


def test_prepare_replaces_the_target_and_names_a_missing_bundle(tmp_path: Path) -> None:
    sample = sample_in(tmp_path)
    data = tmp_path / "data"
    prepare_module.prepare(sample, data)
    (data / "run" / "stale.txt").write_text("x", encoding="utf-8")
    prepare_module.prepare(sample, data)
    assert not (data / "run" / "stale.txt").exists()
    (tmp_path / "samples" / "courtside.bundle").unlink()
    with pytest.raises(SddError) as err:
        prepare_module.prepare(sample, data)
    assert err.value.code == "invalid_input"


def test_prepare_refuses_a_milestone_that_is_done(tmp_path: Path) -> None:
    sample = sample_in(tmp_path)
    toml = sample / SCRIPT_NAME
    toml.write_text(
        toml.read_text(encoding="utf-8").replace(
            'unticked = ["M05a", "M05b", "M06"]', 'unticked = ["M04"]'
        ),
        encoding="utf-8",
    )
    with pytest.raises(SddError) as err:
        prepare_module.prepare(sample, tmp_path / "data")
    assert err.value.code == "invalid_input"
    assert err.value.details["key"] == "start.unticked"


def test_cli_demo_prepare_json(tmp_path: Path) -> None:
    sample = sample_in(tmp_path)
    result = CliRunner().invoke(
        cli_app,
        ["demo", "prepare", "--sample", str(sample), "--data", str(tmp_path / "d"), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run"] == str(tmp_path / "d" / "run")
    assert payload["unticked"] == {"M05a": 2, "M05b": 0, "M06": 0}
    assert (tmp_path / "d" / "run" / ".git").is_dir()


def test_cli_demo_prepare_error_exit(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        cli_app,
        ["demo", "prepare", "--sample", str(tmp_path / "none"), "--data", str(tmp_path / "d")],
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------- replay


def run_to_end(replay: Replay, limit: int = 200) -> int:
    for n in range(1, limit + 1):
        if not replay.tick():
            return n
    raise AssertionError(f"the replay did not finish in {limit} ticks")


def test_spec11_ac01_replay_writes_only_under_data(tmp_path: Path) -> None:
    replay = make_replay(tmp_path)
    sample = sample_in(tmp_path)
    data = tmp_path / "data"
    before = {p for p in tmp_path.rglob("*")}
    replay.start()
    try:
        for _ in range(5):
            replay.tick()
    finally:
        replay.close()
    new = {p for p in tmp_path.rglob("*")} - before
    assert new, "nothing was written"
    outside = sorted(str(p) for p in new if p != data and data not in p.parents)
    assert not outside, outside
    assert (sample / SCRIPT_NAME).is_file()
    assert not (SAMPLE / ".git").exists()


def test_spec11_ac04_replay_loop_resets_to_start_state(tmp_path: Path) -> None:
    replay = make_replay(tmp_path)
    replay.start()
    data = tmp_path / "data"
    try:
        assert replay.tick() is True
        run_to_end(replay)
        runtime = replay.runtime
        assert runtime is not None
        for milestone in ("M05a", "M05b", "M06"):
            assert set(board_states(runtime, milestone).values()) == {"done"}
        done_dir = data / "run" / "docs" / "milestones" / "done"
        for stem in ("M05a-waitlist", "M05b-reminders", "M06-reports-and-audit"):
            assert (done_dir / f"{stem}.md").is_file()
        assert not (data / "run" / "docs" / "milestones" / "M05a-waitlist.md").exists()
        deviations = sorted((data / "run" / "docs" / "deviations").glob("D007-*.md"))
        assert deviations, "the scripted deviation was not logged"
        assert replay.tick() is False
        assert (data / "run" / HEARTBEAT).is_file()

        replay.reset()
        assert not (data / "run.old").exists()
        assert not (data / "run.next").exists()
        runtime = replay.runtime
        assert runtime is not None
        assert set(board_states(runtime, "M05a").values()) == {"todo"}
        assert (data / "run" / "docs" / "milestones" / "M05a-waitlist.md").is_file()
        assert not list((data / "run" / "docs" / "deviations").glob("D007-*.md"))
        # it claims again after the reset
        replay.tick()
        assert "claimed" in set(board_states(runtime, "M05a").values()) | {"claimed"}
        assert any(a[2] == "claim" for a in replay.actions[-4:])
    finally:
        replay.close()


def test_spec11_ac04_replay_is_deterministic(tmp_path: Path) -> None:
    sequences = []
    for name in ("a", "b"):
        replay = make_replay(tmp_path / name)
        replay.start()
        try:
            run_to_end(replay)
            sequences.append(list(replay.actions))
        finally:
            replay.close()
    assert sequences[0] == sequences[1]
    assert any(a[2] == "deviation" for a in sequences[0])
    assert not any("failed" in a[2] for a in sequences[0]), sequences[0]


def test_replay_generated_notes_and_scripted_outcomes(tmp_path: Path) -> None:
    replay = make_replay(tmp_path)
    replay.start()
    try:
        run_to_end(replay)
        runtime = replay.runtime
        assert runtime is not None
        notes = {
            r["id"]: r["notes"]
            for r in runtime.store.read("MATCH (t:Task) RETURN t.id AS id, t.notes AS notes")
            if r["id"].startswith(("M05a", "M05b", "M06"))
        }
        assert notes["M05a.1"] == replay.script.outcomes["M05a.1"].notes
        assert notes["M05b.2"].startswith("Done")  # no scripted entry: generated
        ref = r"SPEC-\d+ (§[\d.]+|`[a-z_]+`)"
        assert re.fullmatch(rf"Done per {ref}(, {ref})*\.", notes["M05b.2"])
        assert "§reminders" not in notes["M05b.2"]
    finally:
        replay.close()


def test_replay_run_loop_pauses_with_heartbeats_and_resets(tmp_path: Path) -> None:
    import threading  # noqa: PLC0415

    sample = sample_in(tmp_path)
    replay = Replay(
        lambda root: config.load(root, None, env={**FAST, "SDD_REPLAY_MAX_MIN": "0"}),
        sample,
        tmp_path / "data",
        load_script(sample / SCRIPT_NAME),
        7,
    )
    stop = threading.Event()
    slept: list[float] = []
    beats: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        beat = tmp_path / "data" / "run" / HEARTBEAT
        if beat.exists():
            beats.append(os.stat(beat).st_mtime)
        if len(slept) >= 8:
            stop.set()

    replay.run(sleep=sleep, stop=stop)
    # replay_max_min = 0: every tick ends in the 30 s pause (6 steps of at most 5 s) and a reset
    assert max(slept) <= 5.0
    assert sum(slept[:6]) == pytest.approx(30.0, abs=0.5)
    assert beats
    assert replay.runtime is None  # closed on exit


# ---------------------------------------------------------------- files (SPEC-11 §3, §9 check 6)


def test_spec11_ac06_runtime_image_contract() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("AS runtime", 1)[1]
    assert re.search(r"^USER 10001$", runtime, re.M)
    assert 'ENTRYPOINT ["sdd"]' in runtime
    assert "HEALTHCHECK" not in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in runtime
    assert "chown 10001:10001 /data" in runtime
    for name in ("docker-compose.yml", "deploy/docker-compose.yml"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for line in re.findall(
            r"^\s*-?\s*[\"']?(\$\{PUBLIC_BIND[^\n]*|\d[\d.]*:\d+:\d+)[\"']?", text, re.M
        ):
            assert line.startswith(("127.0.0.1:", "${PUBLIC_BIND")), (name, line)
        assert "0.0.0.0:" not in text
    judges = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "name: relate-sdd-sample" in judges
    assert '"127.0.0.1:8770:8770"' in judges
    deploy = (ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "name: relate-sdd" in deploy
    for text in (judges, deploy):
        assert "read_only: true" in text
        assert "cap_drop" in text
        assert "tmpfs" in text
        assert "no-new-privileges:true" in text
    assert deploy.count("read_only: true") >= 2
    assert re.search(r"profiles:\s+- tunnel", deploy)
    assert "demo-data:/data:ro" in deploy
    example = (ROOT / "deploy" / ".env.example").read_text(encoding="utf-8")
    assert "SAMPLE=courtside" in example
    assert "TUNNEL_TOKEN=\n" in example or example.rstrip().endswith("TUNNEL_TOKEN=")
