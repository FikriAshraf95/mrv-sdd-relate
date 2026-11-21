"""Coordination tools (SPEC-05 §2 tools 1–4 and 7–9, §3, §5–6; SPEC-04 §5.1).

Every write is **one job** in the store's write queue: check → change the graph → write back
Markdown → re-sync it → append an Event, all or nothing (SPEC-05 §1 rule 3). Jobs that edit
Markdown also hold ``runtime.sync_lock``, like every sync, so the parse cache is never shared.
SSE events are published only after the job committed.

Agents (SPEC-05 §1 rule 2, DEC-003): any call naming an ``agent`` sets ``Agent.last_seen``; a
claim is stale once its holder has not been seen for ``SDD_CLAIM_TTL``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sdd.config import Settings, iso_utc
from sdd.errors import SddError
from sdd.graph.store import Row, Tx
from sdd.graph.upsert import add_event
from sdd.ids import InvalidIdError, label_of, normalise
from sdd.service.runtime import Runtime, publish_changed
from sdd.service.status import read_status
from sdd.sync import writeback

__all__ = [
    "agent_name",
    "claim_task",
    "complete_milestone",
    "complete_task",
    "log_deviation",
    "milestone_ident",
    "next_tasks",
    "release_task",
    "seen",
    "status",
    "task_ident",
    "touch",
]

_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,63}$")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
MAX_LIMIT = 100


# ---------------------------------------------------------------- input


def agent_name(raw: str | None, *, required: bool) -> str | None:
    """A free agent name (``opus-orch``, ``sonnet-2``); ``invalid_input`` if bad or missing."""
    if raw is None or raw.strip() == "":
        if required:
            raise SddError(
                "invalid_input",
                "agent is required: pass your agent name (the same one every session).",
            )
        return None
    name = raw.strip()
    if not _AGENT.match(name):
        raise SddError(
            "invalid_input",
            f"agent {name!r}: use letters, digits, '.', '_', '-' or '@' (at most 64).",
            details={"agent": name},
        )
    return name


def _ident(raw: str, label: str, what: str) -> str:
    try:
        ident = normalise(raw)
        ok = label_of(ident) == label
    except InvalidIdError:
        ok = False
    if not ok:
        raise SddError("invalid_input", f"{raw!r} is not a {what} ID.", details={"id": raw})
    return ident


def task_ident(raw: str) -> str:
    return _ident(raw, "Task", "task")


def milestone_ident(raw: str) -> str:
    return _ident(raw, "Milestone", "milestone")


def _text(value: str | None, name: str, *, required: bool = True) -> str | None:
    if value is None or not value.strip():
        if required:
            raise SddError("invalid_input", f"{name} must not be empty.")
        return None
    return value.strip()


def _paths(files: Sequence[str] | None) -> list[str]:
    out: list[str] = []
    for raw in files or ():
        path = raw.strip().replace("\\", "/").removeprefix("./")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise SddError(
                "invalid_input",
                f"files_touched entry {raw!r}: use a path relative to the project root.",
            )
        out.append(path)
    return sorted(set(out))


# ---------------------------------------------------------------- agents and liveness


def touch(tx: Tx, agent: str, now: str) -> None:
    """Create or refresh ``agent:<name>`` with ``last_seen = now``."""
    tx.run(
        "MERGE (a:Agent {id: $id}) SET a.name = $name, a.last_seen = $now, "
        "a.first_seen = coalesce(a.first_seen, $now)",
        {"id": f"agent:{agent}", "name": agent, "now": now},
    )


def seen(runtime: Runtime, agent: str | None) -> None:
    """A read tool named an agent: refresh its ``last_seen`` (skipped on a read-only store)."""
    if agent is None or runtime.store.read_only:
        return
    now = runtime.settings.now_iso()
    runtime.store.write(lambda tx: touch(tx, agent, now))


def _threshold(settings: Settings) -> str:
    """Claims whose holder was last seen before this moment are stale."""
    return iso_utc(settings.clock() - timedelta(seconds=settings.claim_ttl))


def _live(last_seen: str | None, threshold: str) -> bool:
    return last_seen is not None and str(last_seen) >= threshold


def _last_seen(tx: Tx, agent: str) -> str | None:
    rows = tx.run("MATCH (a:Agent {id: $id}) RETURN a.last_seen AS at", {"id": f"agent:{agent}"})
    return rows[0]["at"] if rows else None


def _age(now: datetime, at: str | None) -> int | None:
    if not at:
        return None
    return int((now - datetime.fromisoformat(str(at))).total_seconds())


# ---------------------------------------------------------------- graph helpers


def _task(tx: Tx, task_id: str) -> Row:
    rows = tx.run(
        "MATCH (t:Task {id: $id}) RETURN t.id AS id, t.title AS title, t.status AS status, "
        "t.milestone_id AS milestone_id, t.claimed_by AS claimed_by, t.claimed_at AS claimed_at",
        {"id": task_id},
    )
    if not rows:
        raise SddError(
            "task_not_found",
            f"No task {task_id}. List claimable tasks with next_tasks.",
            details={"task": task_id},
        )
    return rows[0]


def _blockers(tx: Tx, task_id: str, milestone_id: str) -> list[dict[str, Any]]:
    tasks = tx.run(
        "MATCH (t:Task {id: $id})-[:BLOCKED_BY]->(b:Task) WHERE b.status <> 'done' "
        "RETURN b.id AS id, b.status AS status ORDER BY b.id",
        {"id": task_id},
    )
    milestones = tx.run(
        "MATCH (m:Milestone {id: $id})-[:DEPENDS_ON]->(d:Milestone) WHERE d.status <> 'done' "
        "RETURN d.id AS id, d.status AS status ORDER BY d.id",
        {"id": milestone_id},
    )
    return [{"id": r["id"], "kind": "task", "status": r["status"]} for r in tasks] + [
        {"id": r["id"], "kind": "milestone", "status": r["status"]} for r in milestones
    ]


def _clear_claim(tx: Tx, task_id: str) -> None:
    tx.run(
        "MATCH (t:Task {id: $id}) SET t.claimed_by = null, t.claimed_at = null, "
        "t.status = CASE WHEN t.status = 'done' THEN 'done' ELSE 'todo' END",
        {"id": task_id},
    )
    tx.run("MATCH (:Agent)-[r:CLAIMED]->(:Task {id: $id}) DELETE r", {"id": task_id})


def _refresh_milestone(tx: Tx, milestone_id: str) -> None:
    """Re-derive a milestone's status from its tasks, unless its status line says DONE."""
    rows = tx.run("MATCH (m:Milestone {id: $id}) RETURN m.status AS s", {"id": milestone_id})
    if not rows or rows[0]["s"] == "done":
        return
    states = tx.run(
        "MATCH (t:Task) WHERE t.milestone_id = $id RETURN t.status AS s", {"id": milestone_id}
    )
    new = "in_progress" if any(r["s"] in ("done", "claimed") for r in states) else "todo"
    tx.run("MATCH (m:Milestone {id: $id}) SET m.status = $s", {"id": milestone_id, "s": new})


def _publish_task(
    runtime: Runtime, task_id: str, status: str, claimed_by: str | None, milestone_id: str | None
) -> None:
    runtime.events.publish(
        "task",
        {"id": task_id, "status": status, "claimed_by": claimed_by, "milestone_id": milestone_id},
    )
    publish_changed(runtime.events, [task_id])


def _write(runtime: Runtime, agent: str, job: Any) -> Any:
    """Run a write job; on an expected failure still record that the agent was seen."""
    try:
        return runtime.store.write(job)
    except SddError:
        seen(runtime, agent)
        raise


# ---------------------------------------------------------------- 1. status


def status(runtime: Runtime, agent: str | None = None) -> dict[str, Any]:
    """Milestones with task counts, active claims with their age, warning count, ``synced_at``."""
    name = agent_name(agent, required=False)
    seen(runtime, name)
    warnings = runtime.last_report.warnings if runtime.last_report else []
    out = read_status(runtime.store, runtime.settings, warnings)
    threshold = _threshold(runtime.settings)
    last_seen = {
        r["name"]: r["at"]
        for r in runtime.store.read("MATCH (a:Agent) RETURN a.name AS name, a.last_seen AS at")
    }
    now = runtime.settings.clock()
    for claim in out["claims"]:
        claim["age_s"] = _age(now, claim["claimed_at"])
        claim["stale"] = not _live(last_seen.get(claim["agent"]), threshold)
    out["warning_count"] = sum(out["warnings"].values())
    out["synced_at"] = runtime.synced()
    return out


# ---------------------------------------------------------------- 2. next_tasks


def next_tasks(
    runtime: Runtime, milestone: str | None = None, limit: int = 10, agent: str | None = None
) -> dict[str, Any]:
    """Claimable tasks in milestone order, then task order, with ``overlaps`` (SPEC-05 §3)."""
    name = agent_name(agent, required=False)
    if not 1 <= limit <= MAX_LIMIT:
        raise SddError("invalid_input", f"limit must be 1 to {MAX_LIMIT}.")
    only = milestone_ident(milestone) if milestone else None
    seen(runtime, name)
    store = runtime.store
    milestones = {
        r["id"]: r
        for r in store.read("MATCH (m:Milestone) RETURN m.id AS id, m.order AS ord, m.status AS s")
    }
    if only is not None and only not in milestones:
        raise SddError("milestone_not_found", f"No milestone {only}.", details={"id": only})
    deps: dict[str, list[str]] = {}
    for r in store.read(
        "MATCH (m:Milestone)-[:DEPENDS_ON]->(d:Milestone) RETURN m.id AS m, d.id AS d"
    ):
        deps.setdefault(r["m"], []).append(r["d"])
    tasks = store.read(
        "MATCH (t:Task) RETURN t.id AS id, t.title AS title, t.milestone_id AS milestone_id, "
        "t.group AS grp, t.order AS ord, t.status AS status, t.claimed_by AS claimed_by"
    )
    status_of = {t["id"]: t["status"] for t in tasks}
    blocked: dict[str, list[str]] = {}
    for r in store.read("MATCH (t:Task)-[:BLOCKED_BY]->(b:Task) RETURN t.id AS t, b.id AS b"):
        blocked.setdefault(r["t"], []).append(r["b"])
    governed: dict[str, set[str]] = {}
    for r in store.read("MATCH (t:Task)-[:GOVERNED_BY]->(s) RETURN t.id AS t, s.id AS s"):
        governed.setdefault(r["t"], set()).add(r["s"])
    files: dict[str, set[str]] = {}
    for rel in ("MENTIONS", "TOUCHES"):
        for r in store.read(f"MATCH (t:Task)-[:{rel}]->(f:File) RETURN t.id AS t, f.id AS f"):
            files.setdefault(r["t"], set()).add(r["f"])
    last_seen = {
        r["name"]: r["at"]
        for r in store.read("MATCH (a:Agent) RETURN a.name AS name, a.last_seen AS at")
    }
    threshold = _threshold(runtime.settings)

    def live_claim(t: Row) -> bool:
        holder = t["claimed_by"]
        return bool(holder) and t["status"] != "done" and _live(last_seen.get(holder), threshold)

    claimed_now = [t for t in tasks if live_claim(t)]
    out: list[dict[str, Any]] = []
    for t in tasks:
        if t["status"] == "done" or live_claim(t):
            continue
        if only is not None and t["milestone_id"] != only:
            continue
        if any(status_of.get(b) != "done" for b in blocked.get(t["id"], [])):
            continue
        mid = t["milestone_id"]
        if any(milestones.get(d, {}).get("s") != "done" for d in deps.get(mid, [])):
            continue
        mine_gov, mine_files = governed.get(t["id"], set()), files.get(t["id"], set())
        overlaps = []
        for c in claimed_now:
            shared = (mine_gov & governed.get(c["id"], set())) | (
                mine_files & files.get(c["id"], set())
            )
            if shared:
                overlaps.append(
                    {"id": c["id"], "claimed_by": c["claimed_by"], "shared": sorted(shared)}
                )
        out.append(
            {
                "id": t["id"],
                "title": t["title"],
                "milestone_id": mid,
                "group": t["grp"],
                "governed_by": sorted(mine_gov),
                "overlaps": overlaps,
                "_key": (str(milestones.get(mid, {}).get("ord") or ""), t["ord"] or 0),
            }
        )
    out.sort(key=lambda item: item.pop("_key"))
    return {"tasks": out[:limit], "total": len(out), "synced_at": runtime.synced()}


# ---------------------------------------------------------------- 3. claim_task


def claim_task(runtime: Runtime, task_id: str, agent: str | None) -> dict[str, Any]:
    """Check and set in one job: of two simultaneous claims exactly one wins. Re-claiming your
    own task succeeds. A stale claim is released first (``task_released``, actor ``sync``)."""
    ident = task_ident(task_id)
    name = agent_name(agent, required=True)
    assert name is not None
    settings = runtime.settings

    def job(tx: Tx) -> dict[str, Any]:
        now = settings.now_iso()
        touch(tx, name, now)
        t = _task(tx, ident)
        if t["status"] == "done":
            raise SddError(
                "task_done",
                f"{ident} is already done. Pick another from next_tasks.",
                details={"task": ident},
            )
        holder = t["claimed_by"]
        if holder == name:
            return {
                "claimed_at": t["claimed_at"],
                "already_held": True,
                "released": None,
                "milestone_id": t["milestone_id"],
            }
        released = None
        if holder:
            if _live(_last_seen(tx, holder), _threshold(settings)):
                raise SddError(
                    "already_claimed",
                    f"{ident} is claimed by {holder} since {t['claimed_at']}. "
                    "Pick another from next_tasks.",
                    details={"claimed_by": holder, "claimed_at": t["claimed_at"]},
                )
            blockers = _blockers(tx, ident, t["milestone_id"])
            if blockers:
                raise _blocked(ident, blockers)
            _clear_claim(tx, ident)
            add_event(
                tx,
                kind="task_released",
                actor="sync",
                target_id=ident,
                summary=f"{ident} released: {holder} not seen for {settings.claim_ttl:.0f} s",
                data={"claimed_by": holder, "reason": "stale"},
                now=now,
            )
            released = holder
        else:
            blockers = _blockers(tx, ident, t["milestone_id"])
            if blockers:
                raise _blocked(ident, blockers)
        tx.run(
            "MATCH (t:Task {id: $id}) SET t.claimed_by = $agent, t.claimed_at = $now, "
            "t.status = 'claimed'",
            {"id": ident, "agent": name, "now": now},
        )
        tx.run(
            "MATCH (a:Agent {id: $a}) MATCH (t:Task {id: $t}) "
            "CREATE (a)-[:CLAIMED {at: $now, src: 'tool'}]->(t)",
            {"a": f"agent:{name}", "t": ident, "now": now},
        )
        _refresh_milestone(tx, t["milestone_id"])
        add_event(
            tx,
            kind="task_claimed",
            actor=name,
            target_id=ident,
            summary=f"{ident} claimed by {name}",
            data={},
            now=now,
        )
        return {
            "claimed_at": now,
            "already_held": False,
            "released": released,
            "milestone_id": t["milestone_id"],
        }

    result = _write(runtime, name, job)
    if not result["already_held"]:
        _publish_task(runtime, ident, "claimed", name, result["milestone_id"])
    return {
        "task": ident,
        "agent": name,
        "status": "claimed",
        "claimed_at": result["claimed_at"],
        "already_held": result["already_held"],
        "released_stale_claim_of": result["released"],
        "synced_at": runtime.synced(),
    }


def _blocked(task_id: str, blockers: list[dict[str, Any]]) -> SddError:
    names = ", ".join(b["id"] for b in blockers)
    return SddError(
        "task_blocked",
        f"{task_id} waits for {names}. Pick another from next_tasks.",
        details={"blockers": blockers},
    )


# ---------------------------------------------------------------- 4. release_task


def release_task(
    runtime: Runtime,
    task_id: str,
    agent: str | None,
    reason: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Give a claim back. ``force`` frees a claim someone else holds (the event's actor is the
    holder, ``data.forced_by`` the caller); without it the caller must hold the claim."""
    ident = task_ident(task_id)
    name = agent_name(agent, required=True)
    assert name is not None
    note = _text(reason, "reason", required=False)

    def job(tx: Tx) -> dict[str, Any]:
        now = runtime.settings.now_iso()
        touch(tx, name, now)
        t = _task(tx, ident)
        holder = t["claimed_by"] if t["status"] != "done" else None
        if holder is None:
            if force:
                return {"released": False, "holder": None, "milestone_id": t["milestone_id"]}
            raise SddError(
                "not_claimed_by_you",
                f"{ident} is not claimed by anyone; nothing to release.",
                details={"claimed_by": None, "status": t["status"]},
            )
        if holder != name and not force:
            raise SddError(
                "not_claimed_by_you",
                f"{ident} is claimed by {holder}, not {name}. Pass force=true only if {holder} "
                "has stopped.",
                details={"claimed_by": holder},
            )
        _clear_claim(tx, ident)
        _refresh_milestone(tx, t["milestone_id"])
        data: dict[str, Any] = {"reason": note}
        if holder != name:
            data["forced_by"] = name
        add_event(
            tx,
            kind="task_released",
            actor=holder,
            target_id=ident,
            summary=f"{ident} released" + (f" by {name} (forced)" if holder != name else ""),
            data=data,
            now=now,
        )
        return {"released": True, "holder": holder, "milestone_id": t["milestone_id"]}

    result = _write(runtime, name, job)
    if result["released"]:
        _publish_task(runtime, ident, "todo", None, result["milestone_id"])
    return {
        "task": ident,
        "released": result["released"],
        "claimed_by": result["holder"],
        "forced": bool(result["released"] and result["holder"] != name),
        "synced_at": runtime.synced(),
    }


# ---------------------------------------------------------------- 8. complete_task


def complete_task(
    runtime: Runtime,
    task_id: str,
    agent: str | None,
    *,
    notes: str | None = None,
    files_touched: Sequence[str] | None = None,
    commit: str | None = None,
) -> dict[str, Any]:
    """Tick the box (SPEC-04 §5.1), record the outcome in the Event, return the newly unblocked
    tasks. The caller must hold the claim (``not_claimed_by_you``)."""
    ident = task_ident(task_id)
    name = agent_name(agent, required=True)
    assert name is not None
    text = _text(notes, "notes", required=False)
    files = _paths(files_touched)
    sha = commit.strip().lower() if commit and commit.strip() else None
    if sha is not None and not _SHA.match(sha):
        raise SddError("invalid_input", f"commit {commit!r} is not a git SHA (7–40 hex digits).")
    settings = runtime.settings

    def job(tx: Tx) -> dict[str, Any]:
        now = settings.now_iso()
        touch(tx, name, now)
        t = _task(tx, ident)
        if t["claimed_by"] != name:
            holder = t["claimed_by"]
            hint = f"claimed by {holder}" if holder else f"not claimed ({t['status']})"
            raise SddError(
                "not_claimed_by_you",
                f"{ident} is {hint}. Claim it with claim_task before completing it.",
                details={"claimed_by": holder, "status": t["status"]},
            )
        waiting = [
            r["id"]
            for r in tx.run(
                "MATCH (w:Task)-[:BLOCKED_BY]->(t:Task {id: $id}) RETURN w.id AS id", {"id": ident}
            )
        ]
        tick = writeback.tick_task(tx, settings, ident, now=now, agent=name)
        if text is not None:
            tx.run("MATCH (t:Task {id: $id}) SET t.notes = $notes", {"id": ident, "notes": text})
        _refresh_milestone(tx, t["milestone_id"])
        _link_outcome(tx, ident, files, sha)
        unblocked = []
        for wid in waiting:
            w = _task(tx, wid)
            if w["status"] == "todo" and not _blockers(tx, wid, w["milestone_id"]):
                unblocked.append(
                    {"id": wid, "title": w["title"], "milestone_id": w["milestone_id"]}
                )
        add_event(
            tx,
            kind="task_completed",
            actor=name,
            target_id=ident,
            summary=f"{ident} completed by {name}",
            data={"notes": text, "files_touched": files, "commit": sha},
            now=now,
        )
        return {"tick": tick, "unblocked": unblocked, "milestone_id": t["milestone_id"]}

    with runtime.sync_lock:
        result = _write(runtime, name, job)
    tick: writeback.TickResult = result["tick"]
    _publish_task(runtime, ident, "done", None, result["milestone_id"])
    publish_changed(runtime.events, [f"file:{tick.path}"])
    return {
        "task": ident,
        "status": "done",
        "path": tick.path,
        "changed_file": tick.changed_file,
        "unblocked": result["unblocked"],
        "synced_at": runtime.synced(),
    }


def _link_outcome(tx: Tx, task_id: str, files: list[str], sha: str | None) -> None:
    """``TOUCHES`` to known File nodes and ``COMPLETES`` from a known commit (``src = tool``)."""
    if files:
        have = {
            r["id"]
            for r in tx.run(
                "MATCH (t:Task {id: $id})-[r:TOUCHES]->(f:File) WHERE r.src = 'tool' "
                "RETURN f.id AS id",
                {"id": task_id},
            )
        }
        wanted = [f"file:{p}" for p in files if f"file:{p}" not in have]
        if wanted:
            tx.run(
                "MATCH (t:Task {id: $id}) MATCH (f:File) WHERE f.id IN $files "
                "CREATE (t)-[:TOUCHES {src: 'tool'}]->(f)",
                {"id": task_id, "files": wanted},
            )
    if sha:
        commits = tx.run(
            "MATCH (c:Commit) WHERE c.id STARTS WITH $prefix RETURN c.id AS id",
            {"prefix": f"commit:{sha}"},
        )
        if len(commits) == 1:
            exists = tx.run(
                "MATCH (c:Commit {id: $c})-[r:COMPLETES]->(t:Task {id: $t}) WHERE r.src = 'tool' "
                "RETURN count(r) AS n",
                {"c": commits[0]["id"], "t": task_id},
            )
            if not exists or not exists[0]["n"]:
                tx.run(
                    "MATCH (c:Commit {id: $c}) MATCH (t:Task {id: $t}) "
                    "CREATE (c)-[:COMPLETES {src: 'tool'}]->(t)",
                    {"c": commits[0]["id"], "t": task_id},
                )


# ---------------------------------------------------------------- 7. log_deviation


def log_deviation(
    runtime: Runtime,
    task_id: str,
    agent: str | None,
    *,
    title: str,
    spec_says: str,
    implementation_does: str,
    why: str,
    consequences: str | None = None,
    amends: Sequence[str] = (),
    affects: Sequence[str] | None = None,
    status: str = "open",
) -> dict[str, Any]:
    """Log a deviation the way the manual ritual does (SPEC-05 §5, SPEC-04 §5.1): the file, the
    index row at the top, a note in each amended section, all in one job."""
    ident = task_ident(task_id)
    name = agent_name(agent, required=True)
    assert name is not None
    clean_title = _text(title, "title")
    assert clean_title is not None
    if "\n" in clean_title:
        raise SddError("invalid_input", "title must be one line.")
    if status not in ("open", "resolved"):
        raise SddError("invalid_input", "status must be 'open' or 'resolved'.")
    refs = (amends,) if isinstance(amends, str) else tuple(amends)
    settings = runtime.settings
    if not settings.writeback:
        raise SddError(
            "writeback_disabled",
            "Write-back is off in .sdd/config.toml: a deviation only in the graph would "
            "contradict the Markdown. Log it by hand.",
        )
    memo: dict[str, Any] = {}

    def job(tx: Tx) -> dict[str, Any]:
        now = settings.now_iso()
        touch(tx, name, now)
        t = _task(tx, ident)
        dev = writeback.DeviationIn(
            task_id=ident,
            milestone_id=str(t["milestone_id"]),
            title=clean_title,
            spec_says=_text(spec_says, "spec_says") or "",
            implementation_does=_text(implementation_does, "implementation_does") or "",
            why=_text(why, "why") or "",
            consequences=_text(consequences, "consequences", required=False),
            amends=refs,
            affects=tuple(affects or ()),
            status=status,
        )
        result = writeback.log_deviation(tx, settings, dev, now=now, memo=memo, cache=runtime.cache)
        add_event(
            tx,
            kind="deviation_logged",
            actor=name,
            target_id=result.id,
            summary=clean_title,
            data={"task": ident, "path": result.path, "amends": [x.id for x in result.targets]},
            now=now,
        )
        return {"result": result}

    with runtime.sync_lock:
        out = _write(runtime, name, job)
    result: writeback.DeviationResult = out["result"]
    runtime.events.publish("deviation", {"id": result.id, "title": clean_title})
    publish_changed(runtime.events, [result.id, *result.report.changed_ids])
    return {
        "id": result.id,
        "path": result.path,
        "amends": [x.id for x in result.targets],
        "files": result.files,
        "synced_at": runtime.synced(),
    }


# ---------------------------------------------------------------- 9. complete_milestone


def complete_milestone(
    runtime: Runtime, milestone_id: str, agent: str | None, verification: str
) -> dict[str, Any]:
    """Write the DONE status line with the deviations ``RAISED_IN`` the milestone, move the file
    to ``done/`` and rewrite the links to it (SPEC-05 §6). Every task must be done."""
    ident = milestone_ident(milestone_id)
    name = agent_name(agent, required=True)
    assert name is not None
    how = _text(verification, "verification")
    assert how is not None
    if not how.endswith((".", "!", "?")):
        how += "."
    settings = runtime.settings
    if not settings.writeback:
        raise SddError(
            "writeback_disabled",
            "Write-back is off in .sdd/config.toml: a DONE status only in the graph would "
            "contradict the Markdown. Write the status line by hand.",
        )

    def job(tx: Tx) -> dict[str, Any]:
        now = settings.now_iso()
        touch(tx, name, now)
        if not tx.run("MATCH (m:Milestone {id: $id}) RETURN m.id AS id", {"id": ident}):
            raise SddError("milestone_not_found", f"No milestone {ident}.", details={"id": ident})
        open_tasks = [
            r["id"]
            for r in tx.run(
                "MATCH (t:Task) WHERE t.milestone_id = $id AND t.status <> 'done' "
                "RETURN t.id AS id, t.order AS ord ORDER BY ord",
                {"id": ident},
            )
        ]
        if open_tasks:
            raise SddError(
                "milestone_incomplete",
                f"{ident} still has open tasks: {', '.join(open_tasks)}. Finish them first.",
                details={"open": open_tasks},
            )
        devs = [
            r["id"]
            for r in tx.run(
                "MATCH (d:Deviation)-[:RAISED_IN]->(m:Milestone {id: $id}) "
                "RETURN DISTINCT d.id AS id ORDER BY id",
                {"id": ident},
            )
        ]
        line = f"**Status:** DONE ({now[:10]}). {how} Deviations: {', '.join(devs) or 'none'}."
        result = writeback.complete_milestone(tx, settings, ident, line, cache=runtime.cache)
        add_event(
            tx,
            kind="milestone_done",
            actor=name,
            target_id=ident,
            summary=f"{ident} done",
            data={"verification": how, "deviations": devs, "path": result.path},
            now=now,
        )
        return {"result": result, "deviations": devs, "status_line": line}

    with runtime.sync_lock:
        out = _write(runtime, name, job)
    result: writeback.MilestoneDoneResult = out["result"]
    runtime.events.publish("milestone", {"id": ident, "status": "done"})
    publish_changed(runtime.events, [ident, *result.report.changed_ids])
    return {
        "milestone": ident,
        "status": "done",
        "status_line": out["status_line"],
        "deviations": out["deviations"],
        "path": result.path,
        "moved_from": result.moved_from,
        "files": result.files,
        "synced_at": runtime.synced(),
    }
