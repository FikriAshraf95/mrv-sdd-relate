"""SPEC-01 §7 check 5: concurrent write jobs through the one write queue."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from sdd.service import coordination as coord
from sdd.service.runtime import Runtime
from tests.spec05.helpers import claims_on, events, write_file

TASKS = 50


def _milestone() -> str:
    lines = [f"- [ ] **M05.{n}** Step {n}" for n in range(1, TASKS + 1)]
    return (
        "# M05 — Many steps\n\n> **Depends on:** nothing\n\n## Goal\nMany small steps.\n\n"
        "## Tasks\n### Steps\n" + "\n".join(lines) + "\n\n## Acceptance criteria\n1. All done.\n"
    )


def test_spec01_ac05_fifty_concurrent_claims(runtime: Runtime) -> None:
    write_file(runtime, "docs/milestones/M05-many-steps.md", _milestone())
    barrier = threading.Barrier(TASKS)

    def claim(n: int) -> str:
        barrier.wait()
        return str(coord.claim_task(runtime, f"M05.{n}", f"agent-{n}")["task"])

    with ThreadPoolExecutor(TASKS) as pool:
        claimed = list(pool.map(claim, range(1, TASKS + 1)))  # any SddError would raise here
    assert claimed == [f"M05.{n}" for n in range(1, TASKS + 1)]
    assert all(claims_on(runtime, f"M05.{n}") == 1 for n in range(1, TASKS + 1))
    # one event per job, each job committed on its own: the event times never go backwards
    at = [e["at"] for e in events(runtime, "task_claimed")]
    assert len(at) == TASKS
    assert at == sorted(at)
