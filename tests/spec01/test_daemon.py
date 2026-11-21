"""SPEC-01 §7 checks 1-3 (daemon ownership and CLI routing), and daemon detection (plan M02 §7).

Checks 2 and 3 name ``sdd impact``, which arrives in M04b; they are tested with ``sdd status``
here and M04b extends them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sdd import daemon
from sdd.cli import app
from sdd.errors import SddError
from sdd.service import remote
from sdd.service.runtime import Runtime
from tests.conftest import FakeDaemon, MakeProject, MakeRuntime, daemon_settings
from tests.spec01.test_store import hold_store

runner = CliRunner()


def _invoke(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


# ---------------------------------------------------------------- check 1


def test_spec01_ac01_second_daemon_refuses(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    with pytest.raises(SddError) as err:
        daemon.prepare(runtime.settings)
    assert err.value.code == "daemon_running"
    assert err.value.details["port"] == 8770

    # the first daemon is untouched: it still answers, and its store still writes
    assert fake_daemon.client.get("/api/health").json()["instance"] == runtime.instance
    report = runtime.sync(full=True)
    assert report["scanned"] > 0


def test_second_daemon_is_refused_by_the_writer_lock_without_a_daemon_file(
    project: MakeProject,
) -> None:
    settings = daemon_settings(project("tool_style"))
    holder = hold_store(Path(settings.store_path), 10)  # another process holds the store
    try:
        assert remote.detect(settings) is None  # no daemon.json at all
        with pytest.raises(SddError) as err:
            daemon.prepare(settings)
        assert err.value.code == "daemon_running"
    finally:
        holder.terminate()
        holder.wait()


def test_daemon_needs_a_store_on_disk(project: MakeProject) -> None:
    from sdd import config  # noqa: PLC0415

    settings = config.load(project("tool_style"), ":memory:", env={})
    with pytest.raises(SddError) as err:
        daemon.prepare(settings)
    assert err.value.code == "invalid_input"


# ---------------------------------------------------------------- check 2


def test_spec01_ac02_sync_refuses_status_routes(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)

    code, out = _invoke("--json", "sync", "--project", root)
    assert code == 4
    assert json.loads(out)["error"]["code"] == "daemon_running"

    fake_daemon.seen.clear()
    code, out = _invoke("--json", "status", "--project", root)
    assert code == 0, out
    assert "GET /api/status" in fake_daemon.seen
    assert [m["id"] for m in json.loads(out)["milestones"]] == ["M01", "M02"]

    code, out = _invoke("status", "--project", root)  # the text output is unchanged
    assert code == 0
    assert "M01 Timer" in out


def test_ids_write_refuses_while_a_daemon_runs(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = runtime.settings.project_root
    path = root / "docs/milestones/M01-timer.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("### Tests\n", "### Tests\n- [ ] A legacy line without an ID\n"))
    before = path.read_bytes()
    code, out = _invoke("--json", "ids", "--write", "--yes", "--project", str(root))
    assert code == 4
    assert json.loads(out)["error"]["code"] == "daemon_running"
    assert path.read_bytes() == before


def test_info_reports_the_daemon(runtime: Runtime, fake_daemon: FakeDaemon) -> None:
    root = str(runtime.settings.project_root)
    code, out = _invoke("--json", "info", "--project", root)
    assert code == 0, out
    daemon_info = json.loads(out)["daemon"]
    assert daemon_info["port"] == 8770
    assert daemon_info["pid"] > 0
    code, out = _invoke("info", "--project", root)
    assert "running on :8770" in out


def test_an_explicit_other_store_does_not_route_or_refuse(
    runtime: Runtime, fake_daemon: FakeDaemon
) -> None:
    root = str(runtime.settings.project_root)
    fake_daemon.seen.clear()
    code, out = _invoke("--json", "sync", "--project", root, "--store", ":memory:")
    assert code == 0, out
    assert fake_daemon.seen == []


def test_a_token_protected_daemon_needs_the_token_in_the_cli(
    make_runtime: MakeRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = make_runtime(SDD_TOKEN="tok")
    root = str(runtime.settings.project_root)
    daemon.write_daemon_file(runtime, "127.0.0.1", 8770)

    def transport(
        method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, Any]:
        if headers.get("Authorization") != "Bearer tok":
            return 401, {"error": {"code": "unauthorized", "message": "x"}}
        return 200, {"instance": runtime.instance, "milestones": []}

    monkeypatch.setattr(remote, "TRANSPORT", transport)
    code, out = _invoke("--json", "status", "--project", root)  # no SDD_TOKEN in this env
    assert code == 1
    assert json.loads(out)["error"]["code"] == "unauthorized"
    monkeypatch.setenv("SDD_TOKEN", "tok")
    code, out = _invoke("--json", "status", "--project", root)
    assert code == 0, out


# ---------------------------------------------------------------- check 3


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {
        p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_spec01_ac03_status_without_daemon_read_only(project: MakeProject) -> None:
    root = project("tool_style")
    code, out = _invoke("sync", "--project", str(root))
    assert code == 0, out
    store_dir = root / ".sdd"
    before = _tree(store_dir)
    assert before  # the sync created the store

    code, out = _invoke("--json", "status", "--project", str(root))
    assert code == 0, out
    assert json.loads(out)["milestones"][0]["id"] == "M01"
    assert _tree(store_dir) == before  # no file created, none touched: a read-only snapshot


# ---------------------------------------------------------------- detection and cleanup


def _daemon_json(settings: Any, **fields: Any) -> None:
    path = remote.daemon_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"pid": 1, "host": "127.0.0.1", "port": 8770, "instance": "abc", "started_at": "t"}
    path.write_text(json.dumps({**data, **fields}), encoding="utf-8")


def test_stale_daemon_json_is_ignored_and_kept(
    project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = daemon_settings(project("tool_style"))
    _daemon_json(settings)

    def refused(*args: object) -> tuple[int, Any]:
        raise ConnectionRefusedError

    monkeypatch.setattr(remote, "TRANSPORT", refused)
    assert remote.detect(settings) is None
    remote.ensure_no_daemon(settings)  # does not raise
    assert remote.daemon_file(settings).exists()  # never deleted by detection


def test_another_instance_answering_is_not_our_daemon(
    project: MakeProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = daemon_settings(project("tool_style"))
    _daemon_json(settings, instance="mine")
    monkeypatch.setattr(remote, "TRANSPORT", lambda *a: (200, {"ok": True, "instance": "other"}))
    assert remote.detect(settings) is None
    monkeypatch.setattr(remote, "TRANSPORT", lambda *a: (500, None))
    assert remote.detect(settings) is None
    monkeypatch.setattr(remote, "TRANSPORT", lambda *a: (200, {"instance": "mine"}))
    info = remote.detect(settings)
    assert info is not None
    assert (info.port, info.pid, info.auth_ok) == (8770, 1, True)
    monkeypatch.setattr(remote, "TRANSPORT", lambda *a: (401, {"error": {"code": "unauthorized"}}))
    unauthorized = remote.detect(settings)
    assert unauthorized is not None
    assert unauthorized.auth_ok is False


def test_an_unreadable_daemon_json_means_no_daemon(project: MakeProject) -> None:
    settings = daemon_settings(project("tool_style"))
    assert remote.detect(settings) is None
    remote.daemon_file(settings).parent.mkdir(parents=True, exist_ok=True)
    remote.daemon_file(settings).write_text("{not json", encoding="utf-8")
    assert remote.detect(settings) is None


def test_daemon_json_is_written_atomically_and_removed_only_if_ours(runtime: Runtime) -> None:
    settings = runtime.settings
    daemon.write_daemon_file(runtime, "127.0.0.1", 8770)
    data = json.loads(remote.daemon_file(settings).read_text(encoding="utf-8"))
    assert data["instance"] == runtime.instance
    assert data["port"] == 8770
    assert data["token_sha256"] is None
    assert data["project"] == settings.project_root.name
    assert not list(settings.sdd_dir.glob("daemon.json.tmp"))

    assert daemon.remove_daemon_file(settings, "someone-else") is False
    assert remote.daemon_file(settings).exists()
    assert daemon.remove_daemon_file(settings, runtime.instance) is True
    assert not remote.daemon_file(settings).exists()
    assert daemon.remove_daemon_file(settings, runtime.instance) is False


def test_token_is_stored_only_as_a_hash(make_runtime: MakeRuntime) -> None:
    runtime = make_runtime(SDD_TOKEN="tok")
    daemon.write_daemon_file(runtime, "0.0.0.0", 8770)
    raw = remote.daemon_file(runtime.settings).read_text(encoding="utf-8")
    assert 'tok"' not in raw
    assert len(json.loads(raw)["token_sha256"]) == 64
