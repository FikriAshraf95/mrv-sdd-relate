"""The only module that writes Markdown (CLAUDE.md "Never break"; SPEC-04 §5).

M01b ships the atomic write helper and the legacy task-ID rewrite behind ``sdd ids --write``.
M02 adds the first edit, ticking one task box inside a write job (:func:`tick_task`; plan M02
§3). M03a adds the deviation write-back (:func:`log_deviation`) and the milestone status line,
move and link rewrite (:func:`complete_milestone`); both re-sync inside their job
(``indexer.sync_tx``), so the file and the graph change together (§5.2, §5.4).
"""

from __future__ import annotations

import os
import posixpath
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from sdd.config import Settings
from sdd.errors import SddError
from sdd.graph import upsert
from sdd.graph.store import Tx
from sdd.graph.upsert import FileIn, NodeIn
from sdd.parse import Ref, parse_deviation_index, parse_milestone, parse_spec
from sdd.parse.links import spec_refs
from sdd.parse.md import id_slug
from sdd.sync import indexer
from sdd.sync.indexer import file_hash

__all__ = [
    "AmendTarget",
    "DeviationIn",
    "DeviationResult",
    "MilestoneDoneResult",
    "TickResult",
    "add_spec_note",
    "add_task_ids",
    "atomic_write",
    "complete_milestone",
    "insert_index_row",
    "log_deviation",
    "render_deviation",
    "replace_status_block",
    "rewrite_links",
    "set_status_line",
    "tick_line",
    "tick_task",
    "write_status_block",
]

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


# ---------------------------------------------------------------- shared (M03a)


def _abs(settings: Settings, rel: str) -> Path:
    """The absolute path of a project-relative path; ``invalid_input`` outside the project."""
    root = settings.project_root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise SddError("invalid_input", f"{rel} is outside the project root; refusing to edit.")
    return target


def _read(settings: Settings, rel: str) -> str:
    return _abs(settings, rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def _fences(lines: list[str]) -> list[bool]:
    """``True`` for each line inside (or opening/closing) a fenced code block."""
    out: list[bool] = []
    fence: str | None = None
    for line in lines:
        stripped = line.lstrip()
        if fence is None and stripped[:3] in ("```", "~~~"):
            fence = stripped[:3]
            out.append(True)
        elif fence is not None:
            out.append(True)
            if stripped.startswith(fence):
                fence = None
        else:
            out.append(False)
    return out


def _glob_dir(settings: Settings, key: str, default: str) -> str:
    globs = settings.paths.get(key) or ()
    folder = posixpath.dirname(globs[0]) if globs else ""
    return folder if folder and "*" not in folder else default


def _glob_file(settings: Settings, key: str, default: str) -> str:
    globs = settings.paths.get(key) or ()
    return globs[0] if globs and "*" not in globs[0] else default


def _rel_link(target: str, from_file: str) -> str:
    return posixpath.relpath(target, posixpath.dirname(from_file) or ".")


# ---------------------------------------------------------------- log_deviation (SPEC-04 §5.1)

_KEBAB = re.compile(r"[^a-z0-9]+")
_D_FILE = re.compile(r"^D(\d+)")
_FIELD_LINE = re.compile(r"^\s*[-*]\s+\*\*(?P<key>[^*\n]+?):\*\*")
_H2 = re.compile(r"^##\s+(?P<name>.+?)\s*$")
_HEADING = re.compile(r"^#{1,6}\s")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}")
_PLACEHOLDER = "*(none yet)*"
_INDEX_HEADER = "| # | Title | Milestone | Spec | Status |\n|---|---|---|---|---|"
_FIELD_NAMES = {
    "date / milestone": "Date / milestone",
    "spec": "Spec",
    "affects": "Affects",
    "status": "Status",
}
_SECTION_NAMES = {
    "spec says": "Spec says",
    "implementation does": "Implementation does",
    "why": "Why",
    "consequences": "Consequences",
}

BUILTIN_TEMPLATE = """# D<nnn> — <title>

- **Date / milestone:** …
- **Spec:** …
- **Affects:** …
- **Status:** Open

## Spec says
…

## Implementation does
…

## Why
…

## Consequences
…
"""


def kebab(title: str) -> str:
    """The file-name slug of a deviation title: at most 60 characters, cut at a word boundary."""
    slug = _KEBAB.sub("-", title.lower()).strip("-")
    if len(slug) > 60:
        cut = slug[:61]
        slug = cut[: cut.rfind("-")] if "-" in cut else slug[:60]
    return slug or "deviation"


@dataclass(frozen=True, slots=True)
class AmendTarget:
    id: str  # Section or Spec ID
    spec_id: str
    spec_path: str
    anchor: str | None  # ``#5-log_deviation`` for a section, None for a whole spec
    label: str  # link text: ``SPEC-05 §5``, ``SPEC-02 `documents` ``, ``SPEC-05``


@dataclass(frozen=True, slots=True)
class DeviationIn:
    task_id: str
    milestone_id: str
    title: str
    spec_says: str
    implementation_does: str
    why: str
    consequences: str | None
    amends: tuple[str, ...]
    affects: tuple[str, ...]
    status: str  # open | resolved


@dataclass(frozen=True, slots=True)
class DeviationResult:
    id: str
    path: str
    files: list[str]
    targets: list[AmendTarget]
    report: indexer.SyncReport


def resolve_amends(tx: Tx, refs: tuple[str, ...]) -> list[AmendTarget]:
    """Each reference (SPEC-03 §2.2 grammar, or a canonical ID) → the sections or spec it names.

    At least one is needed; one that does not resolve raises ``unknown_section`` (SPEC-05 §5).
    """
    if not refs:
        raise SddError("invalid_input", "amends needs at least one spec reference.")
    out: dict[str, AmendTarget] = {}
    for raw in refs:
        parsed = spec_refs(raw.strip())
        if not parsed:
            raise SddError(
                "unknown_section",
                f"{raw!r} is not a spec reference. Use the form 'SPEC-05 §5'.",
                details={"ref": raw},
            )
        for ref in parsed:
            target = _resolve_amend(tx, ref)
            if target is None:
                raise SddError(
                    "unknown_section",
                    f"{raw!r} names no section in the graph. Check it with read_section.",
                    details={"ref": raw},
                )
            out.setdefault(target.id, target)
    return list(out.values())


def _resolve_amend(tx: Tx, ref: Ref) -> AmendTarget | None:
    spec_id = ref.target.split("#", 1)[0]
    spec = tx.run("MATCH (p:Spec {id: $id}) RETURN p.source_path AS path", {"id": spec_id})
    if not spec:
        return None
    spec_path = str(spec[0]["path"])
    if ref.kind == "spec":
        return AmendTarget(spec_id, spec_id, spec_path, None, spec_id)
    rows = tx.run(
        "MATCH (s:Section) WHERE s.spec_id = $spec "
        "RETURN s.id AS id, s.number AS number, s.title AS title, s.anchor AS anchor",
        {"spec": spec_id},
    )
    if ref.kind == "section":
        hit = next((r for r in rows if r["id"] == ref.target), None)
    else:
        want = id_slug(ref.slug or "")
        hit = next((r for r in rows if id_slug(str(r["title"])) == want), None)
    if hit is None:
        return None
    label = f"{spec_id} §{hit['number']}" if hit["number"] else f"{spec_id} `{hit['title']}`"
    return AmendTarget(str(hit["id"]), spec_id, spec_path, str(hit["anchor"]), label)


def check_affects(tx: Tx, affects: tuple[str, ...]) -> list[str]:
    """Each entry must name a File node's path or a Table node's name, else ``invalid_input``
    (SPEC-05 §5). Returns the entries, stripped."""
    out: list[str] = []
    for raw in affects:
        entry = raw.strip().strip("`")
        if not entry:
            continue
        hit = tx.run(
            "MATCH (n) WHERE n.id IN $ids RETURN n.id AS id",
            {"ids": [f"file:{entry}", f"table:{entry}"]},
        )
        if not hit:
            raise SddError(
                "invalid_input",
                f"affects entry {entry!r} names no File node or Table node.",
                details={"affects": entry},
            )
        out.append(entry)
    return out


def deviation_template(index_text: str | None) -> str:
    """The fenced template under ``## Template`` in ``DEVIATIONS.md``, else the built-in one."""
    if not index_text:
        return BUILTIN_TEMPLATE
    lines = index_text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "## Template"), None)
    if start is None:
        return BUILTIN_TEMPLATE
    fences = [i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("```")]
    if len(fences) < 2:
        return BUILTIN_TEMPLATE
    body = lines[fences[0] + 1 : fences[1]]
    if not any(ln.startswith("# D") for ln in body):
        return BUILTIN_TEMPLATE
    return "\n".join(body) + "\n"


def render_deviation(
    template: str,
    *,
    dev_id: str,
    title: str,
    fields: dict[str, str | None],
    sections: dict[str, str],
) -> str:
    """Fill ``template``: the H1, the bullet fields (a ``None`` value drops the line; a field the
    template lacks goes after the last field), and the H2 sections' bodies."""
    out: list[str] = []
    done_fields: set[str] = set()
    done_sections: set[str] = set()
    last_field = -1
    skipping = False
    h1_done = False
    for line in template.rstrip("\n").split("\n"):
        if skipping:
            if not _HEADING.match(line):
                continue
            skipping = False
        if not h1_done and line.startswith("# "):
            out.append(f"# {dev_id} — {title}")
            h1_done = True
            continue
        fm = _FIELD_LINE.match(line)
        if fm and fm["key"].strip().lower() in fields:
            key = fm["key"].strip()
            done_fields.add(key.lower())
            value = fields[key.lower()]
            if value is not None:
                out.append(f"- **{key}:** {value}")
                last_field = len(out) - 1
            continue
        hm = _H2.match(line)
        if hm and hm["name"].lower() in sections:
            done_sections.add(hm["name"].lower())
            out += [line, sections[hm["name"].lower()].strip(), ""]
            skipping = True
            continue
        out.append(line)
    extra = [
        f"- **{_FIELD_NAMES.get(k, k.title())}:** {v}"
        for k, v in fields.items()
        if k not in done_fields and v is not None
    ]
    if extra:
        at = last_field + 1 if last_field >= 0 else len(out)
        out[at:at] = extra
    for key, body in sections.items():
        if key not in done_sections:
            out += ["", f"## {_SECTION_NAMES.get(key, key.title())}", body.strip(), ""]
    return "\n".join(out).rstrip("\n") + "\n"


def next_deviation_number(settings: Settings, index_text: str | None) -> int:
    """Highest D-number in the deviation files **and** the index, plus one (SPEC-04 §5.1)."""
    folder = _abs(settings, _glob_dir(settings, "deviations", "docs/deviations"))
    numbers = [0]
    if folder.is_dir():
        numbers += [int(m.group(1)) for p in folder.iterdir() if (m := _D_FILE.match(p.name))]
    if index_text:
        rows = parse_deviation_index("index.md", index_text).index_rows
        numbers += [int(r.id[1:]) for r in rows]
    return max(numbers) + 1


def insert_index_row(text: str, row: str, dev_id: str) -> tuple[str, bool]:
    """Put ``row`` at the top of the index table (the table whose first header cell is ``#``),
    replacing a ``*(none yet)*`` placeholder. No table: one is appended. Idempotent by ID."""
    lines = text.split("\n")
    fenced = _fences(lines)
    row_re = re.compile(rf"^\s*\|\s*\[?{re.escape(dev_id)}\b")
    if any(row_re.match(ln) for ln, f in zip(lines, fenced, strict=True) if not f):
        return text, False
    tables = [
        i
        for i in range(len(lines) - 1)
        if not fenced[i] and lines[i].lstrip().startswith("|") and _TABLE_SEP.match(lines[i + 1])
    ]
    header = next(
        (i for i in tables if lines[i].strip().strip("|").split("|")[0].strip() == "#"),
        tables[0] if tables else None,
    )
    if header is None:
        return f"{text.rstrip(chr(10))}\n\n{_INDEX_HEADER}\n{row}\n", True
    at = header + 2
    if at < len(lines) and _PLACEHOLDER in lines[at]:
        lines[at] = row
    else:
        lines.insert(at, row)
    return "\n".join(lines), True


def add_spec_note(
    spec_path: str, text: str, target: AmendTarget, note: str, dev_id: str
) -> tuple[str, bool]:
    """Append ``note`` as the last line of the section's own body (before its first child
    heading), after a blank line; for a whole spec, as a ``>`` line ending the header blockquote.
    The section is re-located by ID in ``text``; gone → ``source_changed``. Idempotent by ID."""
    lines = text.split("\n")
    marker = f"[{dev_id}]"
    if target.anchor is None:
        h1 = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), None)
        if h1 is None:
            raise _gone(target, spec_path)
        j = h1 + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and lines[j].startswith(">"):
            k = j
            while k + 1 < len(lines) and lines[k + 1].startswith(">"):
                k += 1
            if any(marker in ln for ln in lines[j : k + 1]):
                return text, False
            lines[k + 1 : k + 1] = [">", note]
        else:
            lines[h1 + 1 : h1 + 1] = ["", note]
        return "\n".join(lines), True
    nodes = parse_spec(spec_path, text).nodes
    node = next((n for n in nodes if n.label == "Section" and n.id == target.id), None)
    if node is None:
        raise _gone(target, spec_path)
    start, end = int(node.props["line_start"]), int(node.props["line_end"])
    if any(marker in ln for ln in lines[start - 1 : end]):
        return text, False
    insert = ["", note]
    if end < len(lines) and lines[end].strip():
        insert.append("")
    lines[end:end] = insert
    return "\n".join(lines), True


def _gone(target: AmendTarget, path: str) -> SddError:
    return SddError(
        "source_changed",
        f"{target.label} is no longer in {path} (edited since it was read). Re-read the spec.",
        details={"section": target.id, "path": path},
    )


def log_deviation(
    tx: Tx,
    settings: Settings,
    dev: DeviationIn,
    *,
    now: str,
    memo: dict[str, Any],
    cache: indexer.ParseCache | None = None,
) -> DeviationResult:
    """Steps (1)–(4) of SPEC-04 §5.1 inside the caller's write job, then the in-job re-sync.

    ``memo`` lives as long as the job function: a retried job reuses the number and path it chose
    the first time, so it finds its own file, row and notes and writes nothing twice. Everything
    is located before the first write, so ``source_changed`` leaves every file as it was.
    """
    targets = resolve_amends(tx, dev.amends)
    affects = check_affects(tx, dev.affects)
    index_rel = _glob_file(settings, "deviation_index", "docs/DEVIATIONS.md")
    index_text = _read(settings, index_rel) if _abs(settings, index_rel).is_file() else None
    number: int = memo.setdefault("number", next_deviation_number(settings, index_text))
    dev_id = f"D{number:03d}"
    dev_dir = _glob_dir(settings, "deviations", "docs/deviations")
    dev_rel: str = memo.setdefault("path", f"{dev_dir}/{dev_id}-{kebab(dev.title)}.md")
    status_text = "Resolved → spec updated" if dev.status == "resolved" else "Open"

    edits: dict[str, str] = {}
    if not _abs(settings, dev_rel).exists():
        spec_links = " · ".join(
            f"[{t.label}]({_rel_link(t.spec_path, dev_rel)}{t.anchor or ''})" for t in targets
        )
        edits[dev_rel] = render_deviation(
            deviation_template(index_text),
            dev_id=dev_id,
            title=dev.title,
            fields={
                "date / milestone": f"{now[:10]} · {dev.milestone_id} · {dev.task_id}",
                "spec": spec_links,
                "affects": ", ".join(f"`{a}`" for a in affects) if affects else None,
                "status": status_text,
            },
            sections={
                "spec says": dev.spec_says,
                "implementation does": dev.implementation_does,
                "why": dev.why,
                "consequences": dev.consequences or "None.",
            },
        )

    index_links = " · ".join(
        f"[{t.label}]({_rel_link(t.spec_path, index_rel)}{t.anchor or ''})" for t in targets
    )
    title_cell = dev.title.replace("|", "\\|")
    row = (
        f"| [{dev_id}]({_rel_link(dev_rel, index_rel)}) | {title_cell} | {dev.milestone_id} "
        f"| {index_links} | {status_text} |"
    )
    base = index_text if index_text is not None else "# Deviations\n\n## Index (newest first)\n"
    new_index, changed = insert_index_row(base, row, dev_id)
    if changed:
        edits[index_rel] = new_index

    by_spec: dict[str, list[AmendTarget]] = {}
    for t in targets:
        by_spec.setdefault(t.spec_path, []).append(t)
    for spec_path, items in by_spec.items():
        text = _read(settings, spec_path)
        any_change = False
        for t in items:
            note = f"> **DEVIATION:** see [{dev_id}]({_rel_link(dev_rel, spec_path)}) — {dev.title}"
            text, ch = add_spec_note(spec_path, text, t, note, dev_id)
            any_change = any_change or ch
        if any_change:
            edits[spec_path] = text

    for rel, text in edits.items():
        target = _abs(settings, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, text)
    report = indexer.sync_tx(tx, settings, cache=cache)
    return DeviationResult(dev_id, dev_rel, sorted(edits), targets, report)


# ---------------------------------------------------------------- complete_milestone (§5.1)

_STATUS = re.compile(r"^\*\*Status(?::\*\*|\*\*:|:)")
_DONE = re.compile(r"\bDONE\b")
_LINK = re.compile(r"(\]\()([^)\s]+)(\))")
_EXTERNAL = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//|#)")


@dataclass(frozen=True, slots=True)
class MilestoneDoneResult:
    path: str
    moved_from: str | None
    files: list[str]
    report: indexer.SyncReport


def set_status_line(text: str, line: str) -> tuple[str, bool]:
    """Replace the ``**Status:**`` paragraph with ``line`` (appended if there is none). A status
    already ``DONE`` is left alone, so a retried job never writes it twice."""
    lines = text.split("\n")
    fenced = _fences(lines)
    idx = next(
        (i for i, ln in enumerate(lines) if not fenced[i] and _STATUS.match(ln.strip())), None
    )
    if idx is None:
        return f"{text.rstrip(chr(10))}\n\n{line}\n", True
    end = idx + 1
    while end < len(lines) and lines[end].strip() and not _HEADING.match(lines[end]):
        end += 1
    if _DONE.search(" ".join(lines[idx:end])):
        return text, False
    lines[idx:end] = [line]
    return "\n".join(lines), True


def rewrite_links(
    text: str, old_path: str, new_path: str, moves: dict[str, str]
) -> tuple[str, bool]:
    """Rewrite the path part of relative inline links (text and anchor unchanged): links to a
    moved file follow it, and a moved file's own links are re-based on its new folder."""
    lines = text.split("\n")
    fenced = _fences(lines)
    old_dir = posixpath.dirname(old_path)
    changed = False

    def sub(m: re.Match[str]) -> str:
        nonlocal changed
        href = m.group(2)
        target, sep, anchor = href.partition("#")
        if _EXTERNAL.match(href) or not target:
            return m.group(0)
        resolved = posixpath.normpath(posixpath.join(old_dir, unquote(target)))
        dest = moves.get(resolved, resolved)
        if dest == resolved and old_path == new_path:
            return m.group(0)
        rel = _rel_link(dest, new_path)
        if posixpath.normpath(unquote(target)) == rel:
            return m.group(0)
        changed = True
        return f"{m.group(1)}{rel}{sep}{anchor}{m.group(3)}"

    out = [ln if fenced[i] else _LINK.sub(sub, ln) for i, ln in enumerate(lines)]
    return "\n".join(out), changed


def complete_milestone(
    tx: Tx,
    settings: Settings,
    milestone_id: str,
    status_line: str,
    *,
    cache: indexer.ParseCache | None = None,
) -> MilestoneDoneResult:
    """Write the DONE status line, move the file (and its plan file) to ``done/`` when that
    folder exists, rewrite every relative link to the moved files, then re-sync in the job.

    Idempotent: a retry finds the status ``DONE`` and the files already moved.
    """
    rows = tx.run(
        "MATCH (m:Milestone {id: $id}) RETURN m.source_path AS path", {"id": milestone_id}
    )
    if not rows:
        raise SddError(
            "milestone_not_found", f"No milestone {milestone_id}.", details={"id": milestone_id}
        )
    path = str(rows[0]["path"])
    folder, name = posixpath.split(path)
    in_done = posixpath.basename(folder) == "done"
    done_dir = folder if in_done else posixpath.join(folder, "done")
    move = not in_done and _abs(settings, done_dir).is_dir()
    new_path = posixpath.join(done_dir, name) if move else path
    current = path
    if not _abs(settings, path).is_file():
        if not (move and _abs(settings, new_path).is_file()):
            raise SddError(
                "source_changed",
                f"{path} is gone (moved or deleted since it was read). Re-sync and retry.",
                details={"milestone": milestone_id, "path": path},
            )
        current = new_path  # a retry: moved already

    moves: dict[str, str] = {}
    plan_old = posixpath.join(folder, f"{milestone_id}-plan.md")
    if move:
        moves[path] = new_path
        if _abs(settings, plan_old).is_file():
            moves[plan_old] = posixpath.join(done_dir, posixpath.basename(plan_old))

    # (current path, destination, new text, text changed)
    steps: list[tuple[str, str, str, bool]] = []
    text, status_changed = set_status_line(_read(settings, current), status_line)
    text, links_changed = rewrite_links(text, current, new_path, moves)
    steps.append((current, new_path, text, status_changed or links_changed))
    if plan_old in moves:
        plan_text, ch = rewrite_links(_read(settings, plan_old), plan_old, moves[plan_old], moves)
        steps.append((plan_old, moves[plan_old], plan_text, ch))
    if moves:
        skip = {current, plan_old, *moves.values()}
        for rel in indexer.discover(settings):
            if rel not in skip:
                other, ch = rewrite_links(_read(settings, rel), rel, rel, moves)
                if ch:
                    steps.append((rel, rel, other, True))

    written: list[str] = []
    for source, dest, new_text, text_changed in steps:
        if text_changed:
            atomic_write(_abs(settings, source), new_text)
        if dest != source:
            os.replace(_abs(settings, source), _abs(settings, dest))
        if text_changed or dest != source:
            written.append(dest)
    report = indexer.sync_tx(tx, settings, cache=cache)
    return MilestoneDoneResult(new_path, path if move else None, sorted(written), report)


# ---------------------------------------------------------------- CLAUDE.md status block (M06a)

STATUS_OPEN = "<!-- sdd:status -->"
STATUS_CLOSE = "<!-- /sdd:status -->"


def replace_status_block(text: str, block: str) -> tuple[str, bool]:
    """Replace the lines between the two status markers with ``block`` (SPEC-08 §3).

    Pure, on ``\n`` text (callers normalise like :func:`_read`; :func:`atomic_write` restores
    CRLF). The marker lines and everything outside them stay as they are. Returns
    ``(new text, changed)``; ``invalid_input`` showing the two marker lines when either is
    missing.
    """
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip() == STATUS_OPEN), None)
    end = None
    if start is not None:
        end = next(
            (i for i in range(start + 1, len(lines)) if lines[i].strip() == STATUS_CLOSE), None
        )
    if start is None or end is None:
        raise SddError(
            "invalid_input",
            "CLAUDE.md needs the status markers, each on a line of its own:\n"
            f"{STATUS_OPEN}\n{STATUS_CLOSE}",
        )
    new_lines = [*lines[: start + 1], *block.strip("\n").split("\n"), *lines[end:]]
    new_text = "\n".join(new_lines)
    return new_text, new_text != text


def write_status_block(settings: Settings, block: str, rel: str = "CLAUDE.md") -> bool:
    """Write ``block`` between the markers of the project's CLAUDE.md; ``True`` if it changed.

    Re-reads the file right before writing: if it changed since the first read, nothing is
    written and the error is ``source_changed``.
    """
    path = _abs(settings, rel)
    if not path.is_file():
        raise SddError(
            "invalid_input",
            f"No {rel} in the project. Create it with the markers, each on a line of its own:\n"
            f"{STATUS_OPEN}\n{STATUS_CLOSE}",
        )
    before = path.read_bytes()
    new_text, changed = replace_status_block(before.decode("utf-8").replace("\r\n", "\n"), block)
    if not changed:
        return False
    if path.read_bytes() != before:
        raise SddError("source_changed", f"{rel} changed while the status block was built; retry.")
    atomic_write(path, new_text)
    return True
