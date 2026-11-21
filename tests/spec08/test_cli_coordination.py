"""SPEC-08 §2 coordination commands: through the daemon API, or locally without a daemon."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from sdd.cli import app
from sdd.service.runtime import Runtime
from tests.conftest import FakeDaemon, MakeProject
from tests.spec05.helpers import INDEX, read

runner = CliRunner()


def _json(args: list[str]) -> tuple[int, dict[str, object]]:
    result = runner.invoke(app, [*args, "--json"])
    return result.exit_code, json.loads(result.stdout)


def test_spec08_ac02_claim_on_a_claimed_task_exits_4(
    runtime: Runtime, fake_daemon: FakeDaemon
) -> None:
    root = str(runtime.settings.project_root)
    code, first = _json(["claim", "M01.1", "--agent", "sonnet-1", "--project", root])
    assert code == 0
    assert first["agent"] == "sonnet-1"
    code, second = _json(["claim", "M01.1", "--agent", "sonnet-2", "--project", root])
    assert code == 4
    assert second["error"]["code"] == "already_claimed"  # type: ignore[index]
    assert "POST /api/tasks/M01.1/claim" in fake_daemon.seen


def test_walkthrough_through_the_daemon(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)
    start = "2000-01-01T00:00:00Z"
    assert runner.invoke(app, ["claim", "M01.1", "--agent", "a", "--project", root]).exit_code == 0
    dev = runner.invoke(
        app,
        [
            "deviation", "M01.1", "--agent", "a", "--title", "Brews keep a log",
            "--amends", "SPEC-01 §1", "--spec-says", "No log.", "--does", "A log.",
            "--why", "Auditing.", "--project", root,
        ],
    )  # fmt: skip
    assert dev.exit_code == 0, dev.output
    assert "D003 logged" in dev.stdout
    assert "| [D003]" in read(runtime, INDEX)
    done = runner.invoke(
        app,
        ["done", "M01.1", "--agent", "a", "--notes", "ok", "--files", "a.py", "--project", root],
    )
    assert done.exit_code == 0, done.output
    assert "unblocked M01.2" in done.stdout
    nxt = runner.invoke(app, ["next", "--project", root])
    assert nxt.stdout.startswith("M01.2 ")
    for tid in ("M01.2", "M01.3"):
        runner.invoke(app, ["claim", tid, "--agent", "a", "--project", root])
        runner.invoke(app, ["done", tid, "--agent", "a", "--project", root])
    ms = runner.invoke(
        app, ["milestone-done", "M01", "--agent", "o", "--verification", "ok", "--project", root]
    )
    assert ms.exit_code == 0, ms.output
    assert "DONE (" in ms.stdout
    code, changed = _json(["changes", "--since", start, "--project", root])
    assert code == 0
    assert [d["id"] for d in changed["deviations"]] == ["D003"]  # type: ignore[attr-defined]
    assert [m["id"] for m in changed["milestones_done"]] == ["M01"]  # type: ignore[attr-defined]
    seen = set(fake_daemon.seen)
    assert {"POST /api/deviations", "POST /api/milestones/M01/complete", "GET /api/changes"} <= seen


def test_release_force_and_errors(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)
    runner.invoke(app, ["claim", "M01.1", "--agent", "a", "--project", root])
    code, refused = _json(["release", "M01.1", "--agent", "b", "--project", root])
    assert code == 4
    assert refused["error"]["code"] == "not_claimed_by_you"  # type: ignore[index]
    forced = runner.invoke(app, ["release", "M01.1", "--agent", "b", "--force", "--project", root])
    assert forced.exit_code == 0
    assert "was claimed by a" in forced.stdout
    code, missing = _json(["claim", "M09.1", "--agent", "a", "--project", root])
    assert code == 3
    assert missing["error"]["code"] == "task_not_found"  # type: ignore[index]


def test_claim_without_a_daemon_runs_locally(project: MakeProject) -> None:
    root = str(project("tool_style"))
    code, first = _json(["claim", "M01.1", "--agent", "a", "--project", root])
    assert code == 0, first
    code, second = _json(["claim", "M01.1", "--agent", "b", "--project", root])
    assert code == 4
    assert second["error"]["code"] == "already_claimed"  # type: ignore[index]
    code, nxt = _json(["next", "--project", root])
    assert code == 0
    assert nxt["tasks"] == []  # read-only open of the store the claim wrote


def test_memory_store_refuses_writes(project: MakeProject) -> None:
    root = str(project("tool_style"))
    code, out = _json(["claim", "M01.1", "--agent", "a", "--project", root, "--store", ":memory:"])
    assert code == 2
    assert out["error"]["code"] == "invalid_input"  # type: ignore[index]
    code, nxt = _json(["next", "--project", root, "--store", ":memory:"])
    assert code == 0
    assert [t["id"] for t in nxt["tasks"]] == ["M01.1"]  # type: ignore[attr-defined]
