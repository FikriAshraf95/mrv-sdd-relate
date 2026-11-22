"""``sdd demo prepare``: a fresh working copy of the sample with its start state (SPEC-11 §4).

The copy is a ``git clone`` of ``<sample>.bundle`` (``samples/courtside.bundle``) into
``<data>/<target>``; then every milestone listed under ``[start] unticked`` in ``replay.toml``
gets its boxes unticked and its ``**Status:**`` emptied, through ``sync/writeback.py``. The start
state is not committed, and no store is opened here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sdd import config
from sdd.demo.script import SCRIPT_NAME, ReplayScript, load_script
from sdd.errors import SddError
from sdd.sync import writeback

__all__ = ["bundle_for", "prepare", "prepare_counted", "script_for"]

_MILESTONE_FILE = re.compile(r"^(M\d+[a-z]?)[-.]")


def bundle_for(sample: Path) -> Path:
    return sample.parent / f"{sample.name}.bundle"


def script_for(sample: Path) -> ReplayScript:
    return load_script(sample / SCRIPT_NAME)


def _milestone_files(clone: Path) -> dict[str, Path]:
    """Milestone ID → file, for milestone files outside ``done/`` (plan files excluded)."""
    settings = config.load(clone, config.MEMORY_STORE, env={})
    plans = {p.as_posix() for g in settings.paths["plans"] for p in clone.glob(g)}
    out: dict[str, Path] = {}
    for pattern in settings.paths["milestones"]:
        for path in sorted(clone.glob(pattern)):
            rel = path.relative_to(clone)
            match = _MILESTONE_FILE.match(path.name)
            if match is None or "done" in rel.parts or path.as_posix() in plans:
                continue
            out[match.group(1)] = path
    return out


def _apply_start(clone: Path, script: ReplayScript) -> dict[str, int]:
    files = _milestone_files(clone)
    unticked: dict[str, int] = {}
    for milestone in script.unticked:
        path = files.get(milestone)
        if path is None:
            raise SddError(
                "invalid_input",
                f"{SCRIPT_NAME}: start.unticked names {milestone}, which is not a milestone file "
                "outside done/ in the sample.",
                details={"key": "start.unticked"},
            )
        rel = path.relative_to(clone).as_posix()
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        text, count = writeback.untick_all(rel, text)
        text, _ = writeback.clear_status_line(text)
        writeback.atomic_write(path, text)
        unticked[milestone] = count
    return unticked


def prepare(sample: Path, data: Path, *, target: str = "run") -> Path:
    """Build ``<data>/<target>`` from the sample's bundle and return it."""
    return prepare_counted(sample, data, target=target)[0]


def prepare_counted(
    sample: Path, data: Path, *, target: str = "run"
) -> tuple[Path, dict[str, int]]:
    """As :func:`prepare`, also returning the boxes unticked per milestone."""
    sample = sample.resolve()
    bundle = bundle_for(sample)
    if not bundle.is_file():
        raise SddError("invalid_input", f"The sample bundle {bundle} does not exist.")
    script = script_for(sample)
    dest = data / target
    data.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    try:
        subprocess.run(
            ["git", "clone", "-q", str(bundle), str(dest)],
            env=config.git_env(),
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail: Any = getattr(exc, "stderr", None) or exc
        raise SddError("invalid_input", f"git clone of {bundle} failed: {detail}") from None
    return dest, _apply_start(dest, script)
