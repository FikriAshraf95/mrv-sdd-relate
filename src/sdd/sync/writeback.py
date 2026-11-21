"""The only module that writes Markdown (CLAUDE.md "Never break"; SPEC-04 §5).

M01b ships the atomic write helper and the legacy task-ID rewrite behind ``sdd ids --write``.
M02 extends it with the claim, tick and deviation write-backs.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from sdd.parse import parse_milestone

__all__ = ["add_task_ids", "atomic_write"]

_MARKER = re.compile(r"^(\s*[-*] \[[ xX]\] )")
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
