"""The ``sdd`` command (SPEC-08). Commands validate input, call ``service/`` or the daemon API,
and map the result; no logic lives here.

Global options (SPEC-08 §1 rule 2) work before the command (``sdd --json info``) and, through
the ``ProjectOpt`` / ``StoreOpt`` / ``JsonOpt`` aliases and :func:`resolve`, after it
(``sdd doctor --project X --store :memory:``). The command-level value wins.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from sdd import __version__, config
from sdd.errors import SddError
from sdd.service import commands, indexing
from sdd.service import info as info_service
from sdd.service import init as init_service
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
        ("daemon", _daemon_line(result["daemon"])),
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


# ---------------------------------------------------------------- daemon (M02)


def _daemon_line(daemon: dict[str, Any] | None) -> str:
    return "none" if daemon is None else f"running on :{daemon['port']} (pid {daemon['pid']})"


@app.command()
def daemon(
    ctx: typer.Context,
    host: Annotated[
        str, typer.Option("--host", help="Address to bind (beyond loopback: SPEC-09 §2 rule 1).")
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to listen on.")] = 8770,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Run the daemon: owns the store, watches the Markdown, serves /api and /mcp."""
    # imported here, not at the top: uvicorn, starlette and watchdog are slow to load
    from sdd import daemon as daemon_module  # noqa: PLC0415

    settings, use_json = resolve(ctx, project, store, as_json)
    try:
        daemon_module.run(settings, host=host, port=port)
    except SddError as err:
        fail(err, use_json)


# ---------------------------------------------------------------- coordination (M03a)

AgentOpt = Annotated[str, typer.Option("--agent", help="Your agent name, the same every session.")]
OptAgentOpt = Annotated[
    str | None, typer.Option("--agent", help="Your agent name (marks you as alive).")
]
TaskArg = Annotated[str, typer.Argument(help="Task ID, e.g. M02.3.")]


def _run(use_json: bool, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one coordination command; print JSON with --json, exit with the error's code."""
    try:
        result = call()
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
    return result


@app.command("next")
def next_(
    ctx: typer.Context,
    milestone: Annotated[
        str | None, typer.Option("--milestone", help="Only this milestone, e.g. M02.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="At most this many tasks.")] = 10,
    agent: OptAgentOpt = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Claimable tasks in order, with the claimed tasks they overlap."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(use_json, lambda: commands.next_tasks(settings, milestone, limit, agent))
    if use_json:
        return
    if not result["tasks"]:
        typer.echo("No claimable tasks.")
    for t in result["tasks"]:
        overlap = ", ".join(f"{o['id']} ({o['claimed_by']})" for o in t["overlaps"])
        typer.echo(f"{t['id']} {t['title']}" + (f"  [overlaps {overlap}]" if overlap else ""))


@app.command()
def claim(
    ctx: typer.Context,
    task: TaskArg,
    agent: AgentOpt,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Claim a task atomically (exit 4 if another agent holds it)."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(use_json, lambda: commands.claim(settings, task, agent))
    if not use_json:
        stale = result.get("released_stale_claim_of")
        extra = f" (took over the stale claim of {stale})" if stale else ""
        typer.echo(f"{result['task']} claimed by {result['agent']}{extra}")


@app.command()
def release(
    ctx: typer.Context,
    task: TaskArg,
    agent: AgentOpt,
    reason: Annotated[str | None, typer.Option("--reason", help="Why it is given back.")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Free a claim another agent holds.")
    ] = False,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Give a claim back; --force frees another agent's claim."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(use_json, lambda: commands.release(settings, task, agent, reason, force))
    if use_json:
        return
    if result["released"]:
        typer.echo(f"{result['task']} released (was claimed by {result['claimed_by']})")
    else:
        typer.echo(f"{result['task']} was not claimed")


@app.command()
def done(
    ctx: typer.Context,
    task: TaskArg,
    agent: AgentOpt,
    notes: Annotated[str | None, typer.Option("--notes", help="What was done.")] = None,
    files: Annotated[
        list[str] | None, typer.Option("--files", help="A file touched (repeatable).")
    ] = None,
    commit: Annotated[str | None, typer.Option("--commit", help="Git SHA of the work.")] = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Complete a task you hold: tick its box and record the outcome."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(
        use_json,
        lambda: commands.done(
            settings, task, agent, notes=notes, files_touched=files, commit=commit
        ),
    )
    if use_json:
        return
    typer.echo(f"{result['task']} done ({result['path']})")
    for t in result["unblocked"]:
        typer.echo(f"  unblocked {t['id']} {t['title']}")


@app.command()
def deviation(
    ctx: typer.Context,
    task: Annotated[str, typer.Argument(help="Task ID the deviation is raised in.")],
    agent: AgentOpt,
    title: Annotated[str, typer.Option("--title", help="One line.")],
    amends: Annotated[
        list[str], typer.Option("--amends", help="A spec reference, e.g. SPEC-04 §5.1.")
    ],
    spec_says: Annotated[str, typer.Option("--spec-says", help="What the spec says.")],
    does: Annotated[str, typer.Option("--does", help="What the implementation does.")],
    why: Annotated[str, typer.Option("--why", help="Why it differs.")],
    consequences: Annotated[
        str | None, typer.Option("--consequences", help="What follows from it.")
    ] = None,
    affects: Annotated[
        list[str] | None, typer.Option("--affects", help="A file path or table (repeatable).")
    ] = None,
    resolved: Annotated[
        bool, typer.Option("--resolved", help="Status: resolved, spec updated.")
    ] = False,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Log a deviation: the file, the index row and the spec notes in one change."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(
        use_json,
        lambda: commands.deviation(
            settings,
            task,
            agent,
            title=title,
            spec_says=spec_says,
            implementation_does=does,
            why=why,
            consequences=consequences,
            amends=amends,
            affects=affects,
            status="resolved" if resolved else "open",
        ),
    )
    if not use_json:
        typer.echo(f"{result['id']} logged: {result['path']}")


@app.command("milestone-done")
def milestone_done(
    ctx: typer.Context,
    milestone: Annotated[str, typer.Argument(help="Milestone ID, e.g. M02.")],
    agent: AgentOpt,
    verification: Annotated[
        str, typer.Option("--verification", help="How acceptance was verified.")
    ],
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Write the DONE status line and move the milestone to done/."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(
        use_json, lambda: commands.milestone_done(settings, milestone, agent, verification)
    )
    if use_json:
        return
    typer.echo(result["status_line"])
    if result["moved_from"]:
        typer.echo(f"moved {result['moved_from']} -> {result['path']}")


CHANGE_GROUPS = (
    "sections_changed",
    "specs_added",
    "specs_removed",
    "deviations",
    "tasks_claimed",
    "tasks_completed",
    "milestones_done",
)


@app.command()
def changes(
    ctx: typer.Context,
    since: Annotated[
        str, typer.Option("--since", help="An ISO time, an event ID or last_session.")
    ],
    agent: OptAgentOpt = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """What changed since a time, an event, or your last call."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(use_json, lambda: commands.changes_since(settings, since, agent))
    if use_json:
        return
    first = " (first session)" if result["first_session"] else ""
    typer.echo(f"since {result['since']}{first}")
    for group in CHANGE_GROUPS:
        for item in result[group]:
            title = f" {item['title']}" if item.get("title") else ""
            typer.echo(f"{item['at']} {group} {item['id']}{title} ({item['actor']})")


@app.command("context")
def context_(
    ctx: typer.Context,
    task: TaskArg,
    detail: Annotated[
        str, typer.Option("--detail", help="task (default) or milestone (every section read).")
    ] = "task",
    max_chars: Annotated[
        int, typer.Option("--max-chars", help="Drop parts above this size.")
    ] = 24000,
    agent: OptAgentOpt = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Print a task's context packet."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(
        use_json, lambda: commands.context_packet(settings, task, detail, max_chars, agent)
    )
    if use_json:
        return
    t, m = result["task"], result["milestone"]
    typer.echo(f"{t['id']} {t['title']} [{t['status']}]  ({m['id']} {m['title']})")
    for s in result["sections"]:
        typer.echo(f"\n## {s['id']} {s['title']}  ({s['why']})\n{s['text']}")
    for d in result["deviations"]:
        typer.echo(f"\n{d['id']} [{d['status']}] {d['title']}: {d.get('implementation_does', '')}")
    if result["outline"]:
        typer.echo("\noutline: " + ", ".join(f"{o['id']} {o['title']}" for o in result["outline"]))
    size = result["size"]
    cut = f", truncated {', '.join(size['truncated'])}" if size["truncated"] else ""
    typer.echo(f"\n{size['chars']} chars (~{size['tokens_est']} tokens{cut})")


@app.command()
def section(
    ctx: typer.Context,
    refs: Annotated[list[str], typer.Argument(help="Spec references, e.g. 'SPEC-03 §4.2'.")],
    agent: OptAgentOpt = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Print spec sections by reference, with their subsections."""
    settings, use_json = resolve(ctx, project, store, as_json)
    result = _run(use_json, lambda: commands.section(settings, refs, agent))
    if use_json:
        return
    for s in result["sections"]:
        typer.echo(f"## {s['id']} {s['title']}\n{s['text']}\n")


@app.command()
def query(
    ctx: typer.Context,
    cypher: Annotated[str, typer.Argument(help="One read-only Cypher statement.")],
    params: Annotated[
        str | None, typer.Option("--params", help="Parameters as a JSON object.")
    ] = None,
    agent: OptAgentOpt = None,
    project: ProjectOpt = None,
    store: StoreOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Run read-only Cypher through the query guard (100 rows, 5 s)."""
    settings, use_json = resolve(ctx, project, store, as_json)
    try:
        values = json.loads(params) if params else None
    except ValueError:
        fail(SddError("invalid_input", "--params is not valid JSON."), use_json)
    result = _run(use_json, lambda: commands.query(settings, cypher, values, agent))
    if use_json:
        return
    typer.echo("\t".join(result["columns"]))
    for row in result["rows"]:
        typer.echo("\t".join(json.dumps(v, ensure_ascii=False) for v in row))
    if result["truncated"]:
        typer.echo(f"(truncated at {len(result['rows'])} rows)")


@app.command()
def init(
    ctx: typer.Context,
    force: Annotated[
        bool, typer.Option("--force", help="Replace files and the sdd .mcp.json entry.")
    ] = False,
    project: ProjectOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Set the project up: .sdd/config.toml, .sdd/.gitignore, .mcp.json, the sdd skill."""
    g: Globals = ctx.obj if isinstance(ctx.obj, Globals) else Globals()
    use_json = as_json or g.json
    folder = project or g.project
    if folder is None:
        folder = config.find_project_root(Path.cwd()) or Path.cwd()
    try:
        settings = config.load(folder)
        result = init_service.init_project(settings, force=force)
    except SddError as err:
        fail(err, use_json)
    if use_json:
        emit(result)
        return
    for f in result["files"]:
        typer.echo(f"{f['action']:>8}  {f['path']}")
    for key, globs in result["paths"].items():
        typer.echo(f"detected  {key} = {', '.join(globs)}")
    typer.echo("\nAdd this to CLAUDE.md:\n")
    typer.echo(result["snippet"])
