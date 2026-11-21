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
from sdd.service import indexing
from sdd.service import info as info_service
from sdd.service import status as status_service
from sdd.service import task_ids as ids_service

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


# ---------------------------------------------------------------- sync, status, doctor, ids (M01b)

YesOpt = Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")]


def _confirm(question: str, *, yes: bool, use_json: bool, flag_hint: str) -> bool:
    """Ask unless ``--yes``. ``--json`` never prompts: without ``--yes`` it is a usage error."""
    if yes:
        return True
    if use_json:
        fail(SddError("invalid_input", f"{flag_hint} needs --yes together with --json."), True)
    return typer.confirm(question)


def _warning_line(w: dict[str, Any]) -> str:
    return f"{w['path']}:{w['line']} {w['severity']} {w['code']} {w['message']}"


@app.command()
def sync(
    ctx: typer.Context,
    reset: Annotated[
        bool, typer.Option("--reset", help="Empty the store first; graph-only state is lost.")
    ] = False,
    yes: YesOpt = False,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """One full sync of the SDD Markdown into the store (no daemon)."""
    settings, use_json = resolve(ctx, project, store, as_json)
    if reset and not settings.in_memory:
        question = f"Empty the store {settings.store_path}? Claims, agents and events are lost."
        if not _confirm(question, yes=yes, use_json=use_json, flag_hint="--reset"):
            typer.echo("Cancelled.")
            raise typer.Exit(1)
    try:
        result = indexing.sync(settings, reset=reset)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
        return
    kind = "initial sync" if result["initial"] else "sync"
    typer.echo(
        f"{kind}: {result['scanned']} files scanned, {len(result['changed'])} changed, "
        f"{len(result['removed'])} removed, {result['relinked']} re-linked"
    )
    typer.echo(
        f"nodes {result['created']} created, {result['updated']} updated, "
        f"{result['deleted']} deleted; events {result['events']}; "
        f"store holds {result['nodes']} nodes and {result['relationships']} relationships"
    )
    for w in result["warnings"]:
        typer.echo(_warning_line(w))
    sev = result["warnings_by_severity"]
    typer.echo(
        f"warnings: {sev['error']} error, {sev['warning']} warning, {sev['info']} info; "
        f"unresolved links: {result['unresolved_total']}"
    )


@app.command()
def doctor(
    ctx: typer.Context,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Every parser warning and unresolved link. Reads Markdown only; exit 1 on any error."""
    settings, use_json = resolve(ctx, project, store, as_json)
    try:
        result = indexing.doctor(settings)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
    else:
        current = None
        for w in result["warnings"]:
            if w["path"] != current:
                current = w["path"]
                typer.echo(current)
            typer.echo(f"  {w['line']} {w['severity']} {w['code']} {w['message']}")
        for node, strings in result["unresolved"].items():
            typer.echo(f"unresolved {node}: {', '.join(strings)}")
        counts = result["counts"]
        sev = result["warnings_by_severity"]
        typer.echo(
            f"{counts['specs']} specs, {counts['sections']} sections, "
            f"{counts['milestones']} milestones, {counts['tasks']} tasks, "
            f"{counts['deviations']} deviations, {counts['legacy_task_lines']} legacy task lines, "
            f"{counts['unresolved_links']} unresolved links"
        )
        typer.echo(f"warnings: {sev['error']} error, {sev['warning']} warning, {sev['info']} info")
    if not result["ok"]:
        raise typer.Exit(1)


@app.command()
def status(
    ctx: typer.Context,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Milestones with their tasks, claims, warnings and unresolved links."""
    settings, use_json = resolve(ctx, project, store, as_json)
    try:
        result = status_service.status(settings)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
        return
    for m in result["milestones"]:
        typer.echo(f"{m['id']} {m['title']} [{m['status']}] {m['done']}/{m['total']}")
        for t in m["tasks"]:
            box = "x" if t["checked"] else " "
            who = f" (claimed by {t['claimed_by']})" if t["claimed_by"] else ""
            typer.echo(f"  [{box}] {t['id']} {t['title']}{who}")
    if result["claims"]:
        typer.echo("claims: " + ", ".join(f"{c['task']} by {c['agent']}" for c in result["claims"]))
    for node, strings in result["unresolved"].items():
        typer.echo(f"unresolved {node}: {', '.join(strings)}")
    for row in result["unticked_completed"]:
        typer.echo(f"unticked but completed by commit: {row['task']} ({row['commit']})")
    sev = result["warnings"]
    typer.echo(f"warnings: {sev['error']} error, {sev['warning']} warning, {sev['info']} info")
    if not result["writeback"]:
        typer.echo("write-back is off (config.toml): completions stay in the graph only")


@app.command()
def ids(
    ctx: typer.Context,
    write: Annotated[
        bool, typer.Option("--write", help="Apply the rewrite (default: only show the diff).")
    ] = False,
    milestone: Annotated[
        str | None, typer.Option("--milestone", help="Only this milestone, e.g. M17.")
    ] = None,
    yes: YesOpt = False,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Add stable task IDs to legacy checkbox lines (shows a diff; asks before writing)."""
    settings, use_json = resolve(ctx, project, store, as_json)
    written: list[dict[str, Any]] = []
    try:
        plans = ids_service.plan_ids(settings, milestone)
        if write and plans:
            if _confirm(
                f"Rewrite {len(plans)} milestone file(s)?",
                yes=yes,
                use_json=use_json,
                flag_hint="--write",
            ):
                written = ids_service.write_ids(settings, plans)
            else:
                typer.echo("Cancelled.")
                raise typer.Exit(1)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(
            {
                "plans": [
                    {"path": p.path, "milestone": p.milestone, "count": p.count, "diff": p.diff}
                    for p in plans
                ],
                "written": written,
            }
        )
        return
    if not plans:
        typer.echo("No legacy task lines.")
        return
    for p in plans:
        typer.echo(p.diff.rstrip("\n"))
    if written:
        typer.echo(f"wrote {sum(w['added'] for w in written)} task IDs in {len(written)} file(s)")
