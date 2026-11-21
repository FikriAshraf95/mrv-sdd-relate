"""The only module that writes Markdown (CLAUDE.md "Never break"; SPEC-04 §5).

M01b ships the atomic write helper and the legacy task-ID rewrite behind ``sdd ids --write``.
M02 adds the first edit, ticking one task box inside a write job (:func:`tick_task`; plan M02
§3). M03a wraps it in ``complete_task`` and adds the claim, deviation and milestone write-backs.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph import upsert
from sdd.graph.store import Tx
from sdd.graph.upsert import FileIn, NodeIn
from sdd.parse import parse_milestone
from sdd.sync.indexer import file_hash

__all__ = ["TickResult", "add_task_ids", "atomic_write", "tick_line", "tick_task"]

_MARKER = re.compile(r"^(\s*[-*] \[[ xX]\] )")
_UNCHECKED = re.compile(r"^(\s*[-*] )\[ \]( )")
_STABLE_NUMBER = re.compile(r"\.(\d+)$")


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` (``\\n`` line endings) to ``path`` through a temp file and ``os.replace``.

    Keeps the file's current line ending (CRLF if it contains ``\\r\\n``) and its final-newline
    state. UTF-8, no BOM added.
    """
    crlf = False
    final_newline = text.endswith("\n")
    if path.exists():
        original = path.read_bytes()
        crlf = b"\r\n" in original
        final_newline = original.endswith(b"\n")
    body = text.rstrip("\n") + ("\n" if final_newline else "")
    data = body.replace("\n", "\r\n" if crlf else "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if path.exists():
            tmp.chmod(path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def add_task_ids(path: str, text: str) -> tuple[str, int]:
    """Give every legacy checkbox line of a milestone file a stable ID (SPEC-03 §4.2).

    Numbers continue after the highest stable number in the file, in document order. Only the
    task lines the parser found are touched (so code blocks never are) and only by inserting
    ``**M17.n** `` after the checkbox. ``text`` uses ``\\n`` line endings. Idempotent.
    """
    result = parse_milestone(path, text)
    tasks = [n for n in result.nodes if n.label == "Task"]
    stable = [n for n in tasks if n.props.get("stable_id")]
    highest = max(
        (int(m.group(1)) for n in stable if (m := _STABLE_NUMBER.search(n.id))), default=0
    )
    legacy = sorted(
        (n for n in tasks if not n.props.get("stable_id")), key=lambda n: n.props["source_line"]
    )
    if not legacy:
        return text, 0
    milestone_id = next((n.id for n in result.nodes if n.label == "Milestone"), None)
    if milestone_id is None:
        return text, 0
    lines = text.split("\n")
    changed = 0
    for node in legacy:
        index = int(node.props["source_line"]) - 1
        match = _MARKER.match(lines[index]) if 0 <= index < len(lines) else None
        if match is None:
            continue
        highest += 1
        lines[index] = f"{match.group(1)}**{milestone_id}.{highest}** {lines[index][match.end() :]}"
        changed += 1
    return "\n".join(lines), changed


@dataclass(frozen=True, slots=True)
class TickResult:
    task_id: str
    path: str
    changed_file: bool
    milestone_id: str | None
    status: str


def tick_line(path: str, text: str, task_id: str) -> tuple[str, bool]:
    """Tick the box of ``task_id`` in ``text`` (``\n`` endings): ``(new_text, changed)``.

    The line is re-located by ID in this text, never from a cached line number (SPEC-04 §5.2),
    through the parser, so a lookalike in a code fence is never touched. Raises ``source_changed``
    if the task or its checkbox line is gone. A box already ``[x]`` or ``[X]`` returns
    ``(text, False)``. Only the ``[ ]`` of that one line changes.
    """
    gone = SddError(
        "source_changed",
        f"{task_id} is no longer in {path} (edited since it was read). Re-read the milestone.",
        details={"task": task_id, "path": path},
    )
    node = next(
        (n for n in parse_milestone(path, text).nodes if n.label == "Task" and n.id == task_id),
        None,
    )
    if node is None:
        raise gone
    lines = text.split("\n")
    index = int(node.props["source_line"]) - 1
    if not 0 <= index < len(lines) or not _MARKER.match(lines[index]):
        raise gone
    if f"**{task_id}**" not in lines[index]:
        raise gone
    if not _UNCHECKED.match(lines[index]):
        return text, False
    lines[index] = _UNCHECKED.sub(r"\1[x]\2", lines[index], count=1)
    return "\n".join(lines), True


def tick_task(
    tx: Tx, settings: Settings, task_id: str, *, now: str, agent: str | None = None
) -> TickResult:
    """Tick one task box and mirror it in the graph, inside the caller's write job.

    Order of SPEC-04 §5.2: check → graph (uncommitted) → Markdown (atomic rename) → re-parse
    (loop prevention, §5.4); the store commits when the job returns. Idempotent: a retry finds
    ``[x]`` and writes no file. With ``writeback = false`` only the graph changes (§2.1): the
    task is ``done`` through ``completed_by`` and the line is still re-located, so a removed
    line is ``source_changed``. Raises ``task_not_found``, ``invalid_input`` (path outside the
    project, SPEC-09 §2 rule 5) or ``source_changed``, all before any change.
    """
    rows = tx.run(
        "MATCH (t:Task {id: $id}) RETURN t.source_path AS path, t.milestone_id AS milestone",
        {"id": task_id},
    )
    if not rows:
        raise SddError("task_not_found", f"No task {task_id}.", details={"task": task_id})
    path = str(rows[0]["path"])
    milestone_id = rows[0]["milestone"]
    root = settings.project_root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise SddError("invalid_input", f"{path} is outside the project root; refusing to edit.")

    before = target.read_bytes()
    new_text, changed = tick_line(path, before.decode("utf-8").replace("\r\n", "\n"), task_id)

    # graph, uncommitted. With write-back the next re-parse sees checked = true on both sides,
    # so it counts no hand tick and writes no human Event; without it `completed_by` carries "done".
    props: dict[str, object] = {"now": now, "agent": agent or "tool", "id": task_id}
    tx.run(
        "MATCH (t:Task {id: $id}) SET t.status = 'done', t.done_at = coalesce(t.done_at, $now), "
        "t.claimed_by = null, t.claimed_at = null",
        props,
    )
    if settings.writeback:
        tx.run("MATCH (t:Task {id: $id}) SET t.checked = true", props)
    if agent is not None or not settings.writeback:
        tx.run("MATCH (t:Task {id: $id}) SET t.completed_by = $agent", props)
    tx.run("MATCH (:Agent)-[r:CLAIMED]->(:Task {id: $id}) DELETE r", props)

    if settings.writeback:
        if changed:
            atomic_write(target, new_text)
        _reparse(tx, settings, path, file_hash(before), now)
    return TickResult(task_id, path, changed and settings.writeback, milestone_id, "done")


def _reparse(tx: Tx, settings: Settings, path: str, hash_before: str, now: str) -> None:
    """Re-parse the file just written and store its hash, so the watcher skips it (§5.4).

    The stored hash moves only if the graph was in sync with the file before the tick; otherwise
    a human edit is still unsynced, and the next batch must see it.
    """
    data = (settings.project_root.resolve() / path).read_bytes()
    result = parse_milestone(path, data.decode("utf-8", errors="replace"))
    nodes = [NodeIn(n.label, n.id, dict(n.props)) for n in result.nodes]
    stored = tx.run("MATCH (f:File {id: $id}) RETURN f.content_hash AS h", {"id": f"file:{path}"})
    in_sync = bool(stored) and stored[0]["h"] == hash_before
    upsert.upsert_file_nodes(
        tx,
        FileIn(path, file_hash(data)),
        nodes,
        keep_ids={n.id for n in nodes},
        now=now,
        initial=False,
        writeback=settings.writeback,
    )
    if in_sync:
        tx.run(
            "MATCH (f:File {id: $id}) SET f.content_hash = $hash",
            {"id": f"file:{path}", "hash": file_hash(data)},
        )
