"""Small reads the sprint replay needs (``sdd.demo`` may not import ``graph``; SPEC-01 §3)."""

from __future__ import annotations

from sdd.service.runtime import Runtime

__all__ = ["milestone_status", "section_refs"]


def milestone_status(runtime: Runtime) -> dict[str, tuple[str, int]]:
    """``{milestone id: (status, number of tasks not done)}``."""
    out: dict[str, tuple[str, int]] = {
        r["id"]: (r["status"], 0)
        for r in runtime.store.read("MATCH (m:Milestone) RETURN m.id AS id, m.status AS status")
    }
    for r in runtime.store.read(
        "MATCH (t:Task) WHERE t.status <> 'done' RETURN t.milestone_id AS m, count(t) AS n"
    ):
        if r["m"] in out:
            out[r["m"]] = (out[r["m"]][0], int(r["n"]))
    return out


def section_refs(runtime: Runtime, task_id: str) -> list[str]:
    """The sections a task's line links to, as references (``SPEC-05 §2``), in ID order."""
    rows = runtime.store.read(
        "MATCH (t:Task {id: $id})-[:GOVERNED_BY]->(s:Section) RETURN DISTINCT s.id AS id "
        "ORDER BY id",
        {"id": task_id},
    )
    return [_ref(str(r["id"])) for r in rows]


def _ref(section_id: str) -> str:
    """``SPEC-05#2.1`` → ``SPEC-05 §2.1``; a table ``SPEC-02#bookings`` → ``SPEC-02 `bookings```."""
    spec, _, anchor = section_id.partition("#")
    return f"{spec} §{anchor}" if anchor[:1].isdigit() else f"{spec} `{anchor}`"
