"""``what_changed`` (SPEC-05 §7; DEC-003 option (ii)).

``since`` is an ISO time, an event ID, or ``"last_session"``: everything after this agent's
previous ``what_changed`` call (``Agent.last_changes_at``). A first call returns the last 24 h
with ``first_session: true``. The answer is built from the append-only Events.

Times have one-second resolution, so a bound is inclusive: an event in the same second as the
previous call is reported again rather than missed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sdd.config import iso_utc
from sdd.errors import SddError
from sdd.graph.store import Row, Tx
from sdd.ids import InvalidIdError, label_of, normalise
from sdd.service.coordination import agent_name, touch
from sdd.service.runtime import Runtime

__all__ = ["what_changed"]

FIRST_SESSION = timedelta(hours=24)
LAST_SESSION = "last_session"

# Event kind → result group (SPEC-05 §7)
_GROUPS = {
    "section_changed": "sections_changed",
    "spec_added": "specs_added",
    "spec_removed": "specs_removed",
    "deviation_logged": "deviations",
    "task_completed": "tasks_completed",
    "task_claimed": "tasks_claimed",
    "milestone_done": "milestones_done",
}


def _parse_since(runtime: Runtime, since: str) -> tuple[str, str | None]:
    """``(inclusive start time, event ID to start after or None)`` for an ISO time or event."""
    text = since.strip()
    if text.lower().startswith("event:"):
        try:
            ident = normalise(text)
            ok = label_of(ident) == "Event"
        except InvalidIdError:
            ok = False
        if ok:
            rows = runtime.store.read("MATCH (e:Event {id: $id}) RETURN e.at AS at", {"id": ident})
            if rows:
                return str(rows[0]["at"]), ident
        raise SddError("node_not_found", f"No event {text}.", details={"id": text})
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise SddError(
            "invalid_input",
            f"since={since!r}: use an ISO time (2026-11-25T03:12:00Z), an event ID or "
            "'last_session'.",
        ) from None
    if moment.tzinfo is None:
        raise SddError("invalid_input", f"since={since!r} needs a time zone (end it with Z).")
    return iso_utc(moment), None


def what_changed(runtime: Runtime, since: str, agent: str | None = None) -> dict[str, Any]:
    """Grouped changes since ``since``; with ``agent`` also stores ``Agent.last_changes_at``."""
    if not isinstance(since, str) or not since.strip():
        raise SddError(
            "invalid_input", "since is required: an ISO time, an event ID or 'last_session'."
        )
    last_session = since.strip() == LAST_SESSION
    name = agent_name(agent, required=last_session)
    settings = runtime.settings
    now = settings.clock()
    first_session = False
    after: str | None = None
    if last_session:
        rows = runtime.store.read(
            "MATCH (a:Agent {id: $id}) RETURN a.last_changes_at AS at", {"id": f"agent:{name}"}
        )
        previous = rows[0]["at"] if rows else None
        if previous is None:
            first_session = True
            start = iso_utc(now - FIRST_SESSION)
        else:
            start = str(previous)
    else:
        start, after = _parse_since(runtime, since)

    events = runtime.store.read(
        "MATCH (e:Event) WHERE e.at >= $start RETURN properties(e) AS e ORDER BY e.at, e.id",
        {"start": start},
    )
    if after is not None:
        events = [r for r in events if str(r["e"]["id"]) > after]
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in _GROUPS.values()}
    section_ids = [r["e"]["target_id"] for r in events if r["e"]["kind"] == "section_changed"]
    sections = _sections(runtime, section_ids)
    for row in events:
        e: Row = row["e"]
        group = _GROUPS.get(str(e["kind"]))
        if group is None:
            continue
        item: dict[str, Any] = {"id": e["target_id"], "actor": e["actor"], "at": e["at"]}
        if group == "sections_changed":
            info = sections.get(str(e["target_id"]), {})
            item["title"] = info.get("title")
            item["changed_at"] = info.get("changed_at") or e["at"]
        elif group == "deviations":
            item["title"] = e.get("summary")
            item["task"] = (e.get("data") or {}).get("task")
        elif group == "tasks_completed":
            data = e.get("data") or {}
            item["notes"] = data.get("notes")
            item["files_touched"] = data.get("files_touched") or []
        groups[group].append(item)
    groups["sections_changed"] = _latest_per_id(groups["sections_changed"])

    stamp = iso_utc(now)
    if name is not None and not runtime.store.read_only:

        def job(tx: Tx) -> None:
            touch(tx, name, stamp)
            tx.run(
                "MATCH (a:Agent {id: $id}) SET a.last_changes_at = $now",
                {"id": f"agent:{name}", "now": stamp},
            )

        runtime.store.write(job)
    out: dict[str, Any] = {
        "since": start,
        "until": stamp,
        "first_session": first_session,
        **groups,
        "synced_at": runtime.synced(),
    }
    return out


def _sections(runtime: Runtime, ids: list[str]) -> dict[str, Row]:
    if not ids:
        return {}
    rows = runtime.store.read(
        "MATCH (s:Section) WHERE s.id IN $ids RETURN s.id AS id, s.title AS title, "
        "s.changed_at AS changed_at",
        {"ids": sorted(set(ids))},
    )
    return {str(r["id"]): r for r in rows}


def _latest_per_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in items:  # already in time order
        latest[str(item["id"])] = item
    return sorted(latest.values(), key=lambda i: (str(i["at"]), str(i["id"])))
