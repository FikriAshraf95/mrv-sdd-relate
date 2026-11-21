"""The ``sdd`` command (SPEC-08). Commands validate input, call ``service/`` or the daemon API,
and map the result; no logic lives here.

Global options (SPEC-08 §1 rule 2) work before the command (``sdd --json info``) and, through
the ``ProjectOpt`` / ``StoreOpt`` / ``JsonOpt`` aliases and :func:`resolve`, after it
(``sdd doctor --project X --store :memory:``). The command-level value wins.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from sdd import __version__, config
from sdd.errors import SddError
from sdd.service import info as info_service

# SPEC-08 §1 rule 3
EXIT_CODES: dict[str, int] = {
    "invalid_input": 2,
    "ambiguous_target": 2,
    "task_not_found": 3,
    "milestone_not_found": 3,
    "node_not_found": 3,
    "file_not_found": 3,
    "unknown_section": 3,
    "already_claimed": 4,
    "task_done": 4,
    "task_blocked": 4,
    "not_claimed_by_you": 4,
    "milestone_incomplete": 4,
    "source_changed": 4,
    "daemon_running": 4,
    "write_conflict": 5,
}

ProjectOpt = Annotated[
    Path | None,
    typer.Option(
        "--project",
        help="Project root (default: walk up to the first folder with .sdd/ or docs/specs/).",
        file_okay=False,
    ),
]
StoreOpt = Annotated[
    str | None,
    typer.Option(
        "--store",
        help="Store directory (default <project>/.sdd/graph); ':memory:' writes nothing.",
    ),
]
JsonOpt = Annotated[bool, typer.Option("--json", help="Print the result or error as JSON.")]


@dataclass
class Globals:
    project: Path | None = None
    store: str | None = None
    json: bool = False


app = typer.Typer(
    name="sdd",
    help="SDD Graph: a spec-driven repo as one Relate graph, for agents (MCP) and people.",
    add_completion=False,
    pretty_exceptions_enable=False,
)


def relate_version() -> str:
    # Read from package metadata: importing relate is reserved for graph/store.py.
    try:
        return version("relate-db")
    except PackageNotFoundError:
        return "not installed"


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
    show_version: Annotated[
        bool, typer.Option("--version", help="Print the sdd and relate-db versions.")
    ] = False,
) -> None:
    ctx.obj = Globals(project=project, store=store, json=as_json)
    if show_version:
        versions = {"sdd": __version__, "relate_db": relate_version()}
        if as_json:
            emit(versions)
        else:
            typer.echo(f"sdd {versions['sdd']}\nrelate-db {versions['relate_db']}")
        raise typer.Exit(0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def resolve(
    ctx: typer.Context,
    project: Path | None = None,
    store: str | None = None,
    as_json: bool = False,
) -> tuple[config.Settings, bool]:
    """Merge command-level global options over the ones given before the command."""
    g: Globals = ctx.obj if isinstance(ctx.obj, Globals) else Globals()
    use_json = as_json or g.json
    try:
        settings = config.load(project or g.project, store or g.store)
    except SddError as err:
        fail(err, use_json)
    return settings, use_json


def emit(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def fail(err: SddError, as_json: bool) -> NoReturn:
    """Print an error (JSON on stdout with --json, else the message on stderr) and exit."""
    if as_json:
        emit(err.to_dict())
    else:
        print(f"error ({err.code}): {err.message}", file=sys.stderr)
    raise typer.Exit(EXIT_CODES.get(err.code, 1))


@app.command()
def info(
    ctx: typer.Context,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Project root, store path, daemon, node and relationship counts, schema version."""
    settings, use_json = resolve(ctx, project, store, as_json)
    try:
        result = info_service.info(settings)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
        return
    state = "" if result["store_exists"] else " (not created yet)"
    stored = result["store_schema_version"]
    lines = [
        ("project", result["project"]),
        ("store", f"{result['store']}{state}"),
        ("daemon", "none"),
        ("schema version", f"{result['schema_version']} (store: {stored or 'not set'})"),
        ("nodes", str(result["total_nodes"])),
        *((f"  {label}", str(n)) for label, n in result["nodes"].items()),
        ("relationships", str(result["total_relationships"])),
        *((f"  {kind}", str(n)) for kind, n in result["relationships"].items()),
    ]
    width = max(len(key) for key, _ in lines) + 2
    for key, value in lines:
        typer.echo(f"{key:<{width}}{value}")
