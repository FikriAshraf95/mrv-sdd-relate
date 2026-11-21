"""Settings from the environment and ``.sdd/config.toml``.

This is the only module that reads ``os.environ`` (SPEC-01 §2). Stdlib and ``errors`` only
(SPEC-01 §3). Time is read through ``Settings.clock`` so tests can inject a fixed clock
(SPEC-10 §1).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sdd.errors import SddError

MEMORY_STORE = ":memory:"
CONFIG_FILE = Path(".sdd") / "config.toml"

# SPEC-03 §1: document globs, overridable in .sdd/config.toml.
DEFAULT_PATHS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "specs": ("docs/specs/SPEC-*.md",),
        "milestones": ("docs/milestones/**/M*.md",),
        "plans": ("docs/milestones/**/M*-plan.md",),
        "deviations": ("docs/deviations/D*.md",),
        "deviation_index": ("docs/DEVIATIONS.md",),
        "docs": (
            "**/CLAUDE.md",
            "docs/IDEA.md",
            "docs/design-system.md",
            "HANDOFF.md",
            "README.md",
        ),
        "schema_specs": ("docs/specs/SPEC-*schema*.md",),
        "tests": ("tests/**", "**/*Tests/**", "**/*.test.ts", "**/test_*.py", "**/*_test.go"),
    }
)
_BOOL_KEYS = frozenset({"writeback"})
# SPEC-05 §4: spec references every context packet carries in full (default: SPEC-00 §6).
_LIST_KEYS = frozenset({"always_include"})
DEFAULT_ALWAYS_INCLUDE = ("SPEC-00 §6",)

WATCH_MODES = ("auto", "poll", "native")
PUBLIC_QUERY_MODES = ("guarded", "presets")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(moment: datetime) -> str:
    """UTC ISO 8601 with ``Z`` (SPEC-00 §6.2)."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    store_path: str  # a directory path, or ":memory:"
    paths: Mapping[str, tuple[str, ...]] = DEFAULT_PATHS
    writeback: bool = True
    always_include: tuple[str, ...] = DEFAULT_ALWAYS_INCLUDE
    in_container: bool = False
    # SPEC-04 §1, §4, §6
    watch: str = "auto"
    poll_interval: float = 1.0
    poll_code_interval: float = 10.0  # minimum; the poll backs off to 10x its duration (M02.8)
    max_files: int = 20_000
    git_max_commits: int = 2000
    # SPEC-05 §3, DEC-003 (seconds)
    claim_ttl: float = 2 * 3600.0
    # SPEC-09 §2, §4
    token: str | None = field(default=None, repr=False)
    allow_remote: bool = False
    allowed_hosts: tuple[str, ...] = ()
    trusted_proxy_net: str | None = None
    public_query: str = "guarded"
    query_timeout: float = 5.0  # SPEC-09 §3 step 3 (seconds; tests shorten it)
    # SPEC-11 §4
    replay_tick: float = 4.0
    replay_max_min: float = 20.0
    replay_seed: int | None = None
    clock: Callable[[], datetime] = field(default=utc_now, repr=False, compare=False)

    @property
    def in_memory(self) -> bool:
        return self.store_path == MEMORY_STORE

    @property
    def sdd_dir(self) -> Path:
        return self.project_root / ".sdd"

    def now_iso(self) -> str:
        return iso_utc(self.clock())


def find_project_root(start: Path) -> Path | None:
    """Walk up from ``start`` to the first folder containing ``.sdd/`` or ``docs/specs/``."""
    here = start.resolve()
    for folder in (here, *here.parents):
        if (folder / ".sdd").is_dir() or (folder / "docs" / "specs").is_dir():
            return folder
    return None


def load(
    project: Path | str | None = None,
    store: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> Settings:
    """Build :class:`Settings` from CLI options, the environment and ``.sdd/config.toml``."""
    environ = os.environ if env is None else env

    if project is None:
        start = cwd or Path.cwd()
        root = find_project_root(start)
        if root is None:
            raise SddError(
                "invalid_input",
                f"No project found from {start}: no folder up the tree contains .sdd/ or "
                "docs/specs/. Pass --project PATH.",
            )
    else:
        root = Path(project).resolve()
        if not root.is_dir():
            raise SddError("invalid_input", f"Project folder {root} does not exist.")

    if store is None:
        store_path = str(root / ".sdd" / "graph")
    elif store == MEMORY_STORE:
        store_path = MEMORY_STORE
    else:
        store_path = str(Path(store).resolve())

    file_cfg = _read_config_file(root / CONFIG_FILE)
    paths = dict(DEFAULT_PATHS)
    for key, value in file_cfg.items():
        if key in DEFAULT_PATHS:
            paths[key] = value

    return Settings(
        project_root=root,
        store_path=store_path,
        paths=MappingProxyType(paths),
        writeback=bool(file_cfg.get("writeback", True)),
        always_include=tuple(file_cfg.get("always_include", DEFAULT_ALWAYS_INCLUDE)),
        in_container=Path("/.dockerenv").exists(),
        watch=_choice(environ, "SDD_WATCH", "auto", WATCH_MODES),
        poll_interval=_number(environ, "SDD_POLL_INTERVAL", 1.0),
        poll_code_interval=_number(environ, "SDD_POLL_CODE_INTERVAL", 10.0),
        max_files=int(_number(environ, "SDD_MAX_FILES", 20_000)),
        git_max_commits=int(_number(environ, "SDD_GIT_MAX_COMMITS", 2000)),
        claim_ttl=_number(environ, "SDD_CLAIM_TTL", 2 * 3600.0),
        token=environ.get("SDD_TOKEN") or None,
        allow_remote=_flag(environ, "SDD_ALLOW_REMOTE"),
        allowed_hosts=tuple(
            h.strip() for h in environ.get("SDD_ALLOWED_HOSTS", "").split(",") if h.strip()
        ),
        trusted_proxy_net=environ.get("SDD_TRUSTED_PROXY_NET") or None,
        public_query=_choice(environ, "SDD_PUBLIC_QUERY", "guarded", PUBLIC_QUERY_MODES),
        replay_tick=_number(environ, "SDD_REPLAY_TICK", 4.0),
        replay_max_min=_number(environ, "SDD_REPLAY_MAX_MIN", 20.0),
        replay_seed=(
            int(_number(environ, "SDD_REPLAY_SEED", 0)) if environ.get("SDD_REPLAY_SEED") else None
        ),
        clock=clock or utc_now,
    )


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise SddError("invalid_input", f"{path} is not valid TOML: {exc}. Fix the file.") from exc

    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key in DEFAULT_PATHS:
            globs = [value] if isinstance(value, str) else value
            if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
                raise SddError(
                    "invalid_input", f"{path}: '{key}' must be a glob string or a list of globs."
                )
            out[key] = tuple(globs)
        elif key in _BOOL_KEYS:
            if not isinstance(value, bool):
                raise SddError("invalid_input", f"{path}: '{key}' must be true or false.")
            out[key] = value
        elif key in _LIST_KEYS:
            items = [value] if isinstance(value, str) else value
            if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
                raise SddError("invalid_input", f"{path}: '{key}' must be a list of strings.")
            out[key] = tuple(items)
        else:
            known = ", ".join(sorted([*DEFAULT_PATHS, *_BOOL_KEYS, *_LIST_KEYS]))
            raise SddError(
                "invalid_input",
                f"{path}: unknown key '{key}'. Known keys: {known}.",
                details={"key": key},
            )
    return out


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SddError("invalid_input", f"{name}={raw!r} is not a number.") from None
    if value < 0:
        raise SddError("invalid_input", f"{name}={raw!r} must not be negative.")
    return value


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _choice(env: Mapping[str, str], name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = env.get(name, "").strip().lower() or default
    if value not in allowed:
        raise SddError("invalid_input", f"{name}={value!r}: use one of {', '.join(allowed)}.")
    return value
