"""Milestone files (SPEC-03 §4, plan M01a §6): header lines, tasks, goal, acceptance, status."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from markdown_it.token import Token

from sdd.ids import id_from_filename, normalise
from sdd.parse.links import (
    Found,
    backticked,
    deviation_ids,
    milestone_ids,
    refs_in_inline,
    refs_in_markdown,
)
from sdd.parse.md import (
    content_hash,
    header_pairs,
    heading_text,
    inline_children,
    nl,
    render_plain,
    split_number,
    tokens,
)
from sdd.parse.model import Node, ParseResult, Ref, Rel, add_rel, rel_props, warn

__all__ = ["parse_milestone"]

_H1_RE = re.compile(r"^(?P<id>M\d+[a-z]?)\s*[—–-]\s*(?P<title>.+)$", re.IGNORECASE)
_TASK_RE = re.compile(r"^\s*[-*] \[( |x|X)\] \*\*(M\d+[a-z]?\.\d+)\*\*\s+(.*)")
_LEGACY_RE = re.compile(r"^\s*[-*+] \[( |x|X)\]\s+(.*)")
_AFTER_RE = re.compile(r"\s*\(after\s+([^()]*)\)\s*$", re.IGNORECASE)
_TASK_ID_RE = re.compile(r"^M\d+[a-z]?\.\d+$", re.IGNORECASE)
_LINK_TEXT_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_NONE_VALUES = {"—", "-", "–", "nothing", "none"}
_MODELS = {"Opus", "Sonnet", "Opusplan", "Haiku"}
_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")
_SPEC_KINDS = ("section", "slug", "spec")


@dataclass(slots=True)
class _Head:
    tok_index: int
    level: int
    title: str
    start: int
    end: int


def _spec_refs(found: list[Found]) -> list[Ref]:
    """Refs a milestone or task may point at: Sections and Specs (SPEC-02 §4)."""
    out: list[Ref] = []
    for f in found:
        for ref in f.refs:
            if ref.kind in _SPEC_KINDS or (
                ref.kind == "path"
                and (ident := id_from_filename(posixpath.basename(ref.target)))
                and ident.startswith("SPEC-")
            ):
                out.append(ref)
    return out


def _title_of(h1: str, stem: str) -> tuple[str, str | None]:
    m = _H1_RE.match(h1)
    if m:
        return m["title"].strip(), normalise(m["id"])
    return (h1 or stem), None


def parse_milestone(path: str, text: str) -> ParseResult:  # noqa: PLR0915
    """Parse one milestone file. Never raises on bad Markdown; problems are warnings."""
    result = ParseResult(path)
    raw_text = text
    text = nl(text)
    ms = id_from_filename(posixpath.basename(path))
    if not ms or not ms.startswith("M"):
        result.warnings.append(warn(path, 1, "bad_filename", "file name has no M<nn> ID"))
        return result
    lines = text.split("\n")
    toks = tokens(text)
    seen: set[tuple[object, ...]] = set()
    num = re.match(r"M(\d+)([a-z]?)", ms)
    assert num is not None
    order = f"{int(num[1]):04d}{num[2]}"

    # ---- H1 and header
    h1_index = next(
        (i for i, t in enumerate(toks) if t.type == "heading_open" and t.tag == "h1"), None
    )
    stem = posixpath.splitext(posixpath.basename(path))[0]
    title = stem
    if h1_index is None:
        result.warnings.append(warn(path, 1, "missing_h1", "no H1"))
    else:
        title, h1_id = _title_of(heading_text(toks[h1_index + 1]), stem)
        if h1_id is not None and h1_id != ms:
            result.warnings.append(
                warn(path, (toks[h1_index].map or [0])[0] + 1, "h1_id_mismatch", h1_id)
            )
    header: dict[str, str] = {}
    model: str | None = None
    first_block = (h1_index + 3) if h1_index is not None else 0
    if first_block < len(toks) and toks[first_block].type == "blockquote_open":
        bq = toks[first_block].map or [0, 0]
        pairs, _ = header_pairs(lines[bq[0] : bq[1]], bq[0] + 1)
        for pair in pairs:
            header[pair.key] = pair.value
            kids = inline_children(pair.raw)
            key = pair.key.strip().lower()
            if key == "depends on" and pair.value.strip().lower() not in _NONE_VALUES:
                for other in milestone_ids(kids):
                    if other != ms:
                        add_rel(
                            result.rels, seen, Rel("DEPENDS_ON", ms, Ref("id", other, pair.line))
                        )
            elif key == "blocks" and pair.value.strip().lower() not in _NONE_VALUES:
                for other in milestone_ids(kids):
                    if other != ms:
                        add_rel(
                            result.rels, seen, Rel("DEPENDS_ON", other, Ref("id", ms, pair.line))
                        )
            elif key == "read first":
                found = refs_in_markdown(pair.raw, path=path, line=pair.line)
                for f in found:
                    result.warnings.extend(f.warnings)
                for ref in _spec_refs(found):
                    add_rel(result.rels, seen, Rel("READS", ms, ref, rel_props(ref)))
            elif key == "model":
                first = pair.value.split(" ")[0].rstrip(".,;:") if pair.value else ""
                model = first if first in _MODELS else None

    # ---- sections: goal, acceptance, later checks
    heads = _heads(toks)
    goal = ""
    acceptance: list[str] = []
    for hi, head in enumerate(heads):
        if head.level not in (2, 3):
            continue
        name = split_number(head.title)[1].strip().lower()
        stop_idx = next((h for h in heads[hi + 1 :] if h.level <= head.level), None)
        stop_line = stop_idx.start if stop_idx else len(lines)
        stop_tok = stop_idx.tok_index if stop_idx else len(toks)
        body = "\n".join(lines[head.end : stop_line]).strip()
        if name == "goal":
            goal = body
        elif name == "acceptance criteria":
            acceptance = _numbered_items(toks, lines, head.tok_index, stop_tok)
        elif name == "checks finished in later milestones":
            header["later_checks"] = body

    # ---- tasks
    tasks = _tasks(path, ms, toks, lines, heads, result, seen)

    # ---- status
    status_text, done_date, status = _status(toks, lines, any(t["checked"] for t in tasks))
    if status_text:
        for dev in deviation_ids(inline_children(status_text)):
            add_rel(result.rels, seen, Rel("RAISED_IN", dev, Ref("id", ms, 1)))

    result.nodes.insert(
        0,
        Node(
            "Milestone",
            ms,
            {
                "title": title,
                "order": order,
                "status": status,
                "status_text": status_text,
                "done_date": done_date,
                "model": model,
                "goal": goal,
                "acceptance": acceptance,
                "path": path,
                "header": header,
                "source_path": path,
                "source_line": 1,
                "content_hash": content_hash(raw_text),
            },
        ),
    )
    return result


def _heads(toks: list[Token]) -> list[_Head]:
    return [
        _Head(i, int(t.tag[1]), heading_text(toks[i + 1]), t.map[0], t.map[1])
        for i, t in enumerate(toks)
        if t.type == "heading_open" and t.level == 0 and t.map
    ]


def _numbered_items(toks: list[Token], lines: list[str], start: int, stop: int) -> list[str]:
    """Top-level numbered list items between two token indexes, continuation lines joined."""
    out: list[str] = []
    for i in range(start, stop):
        t = toks[i]
        if t.type == "ordered_list_open" and t.level == 0:
            for j in range(i + 1, stop):
                item = toks[j]
                if item.type == "ordered_list_close" and item.level == 0:
                    break
                if item.type == "list_item_open" and item.level == 1 and item.map:
                    chunk = lines[item.map[0] : item.map[1]]
                    first = re.sub(r"^\s*\d+[.)]\s+", "", chunk[0])
                    out.append(" ".join(p.strip() for p in [first, *chunk[1:]] if p.strip()))
    return out


def _close_index(toks: list[Token], i: int) -> int:
    level = toks[i].level
    for j in range(i + 1, len(toks)):
        if toks[j].type == "list_item_close" and toks[j].level == level:
            return j
    return len(toks) - 1


def _tasks(  # noqa: PLR0915, PLR0917
    path: str,
    ms: str,
    toks: list[Token],
    lines: list[str],
    heads: list[_Head],
    result: ParseResult,
    seen: set[tuple[object, ...]],
) -> list[dict[str, object]]:
    items: list[tuple[int, Token, re.Match[str] | None, re.Match[str]]] = []
    for i, t in enumerate(toks):
        if t.type != "list_item_open" or not t.map:
            continue
        first = lines[t.map[0]]
        stable = _TASK_RE.match(first)
        legacy = _LEGACY_RE.match(first)
        if m := (stable or legacy):
            items.append((i, t, stable, m))
    ranges = [(t.map[0], t.map[1]) for _, t, _, _ in items if t.map]
    taken: set[str] = set()
    out: list[dict[str, object]] = []
    for order, (i, t, stable, m) in enumerate(items, start=1):
        assert t.map is not None
        start, end = t.map
        excluded = {
            ln
            for s, e in ranges
            if (s, e) != (start, end) and start <= s and e <= end
            for ln in range(s, e)
        }
        kept = [(n, lines[n]) for n in range(start, end) if n not in excluded]
        first_text = (stable.group(3) if stable else m.group(2)).strip() if kept else ""
        title = _assemble(first_text, [ln for _, ln in kept[1:]])
        prev = next((h for h in reversed(heads) if h.start < start and h.level in (2, 3)), None)
        group = prev.title if prev is not None and prev.level == 3 else None
        checked = m.group(1) in ("x", "X")
        line = start + 1
        after_ids, bad = _after(title)
        head, _, tail = title.partition("\n")
        head2 = _AFTER_RE.sub("", head)
        title = head2 + (("\n" + tail) if tail else "")
        for token in bad:
            result.warnings.append(warn(path, line, "task_bad_after", token))

        if stable:
            raw_id = normalise(stable.group(2))
            if raw_id.split(".")[0] != ms:
                result.warnings.append(warn(path, line, "task_id_mismatch", f"{raw_id} in {ms}"))
            if raw_id in taken:
                result.warnings.append(warn(path, line, "task_duplicate_id", raw_id))
                task_id, stable_id = f"{ms}.p{order}", False
            else:
                task_id, stable_id = raw_id, True
        else:
            task_id, stable_id = f"{ms}.p{order}", False
            result.warnings.append(warn(path, line, "task_unstable_id", f"line {line}"))
        taken.add(task_id)
        raw_item = "\n".join(ln for _, ln in kept)
        out.append({"checked": checked, "id": task_id})
        result.nodes.append(
            Node(
                "Task",
                task_id,
                {
                    "milestone_id": ms,
                    "title": title,
                    "group": group,
                    "order": order,
                    "checked": checked,
                    "stable_id": stable_id,
                    "source_path": path,
                    "source_line": line,
                    "content_hash": content_hash(raw_item),
                },
            )
        )
        result.rels.append(Rel("INCLUDES", ms, Ref("id", task_id, line)))
        for dep in after_ids:
            add_rel(result.rels, seen, Rel("BLOCKED_BY", task_id, Ref("id", dep, line)))

        # references in the task's own inline tokens (not nested checkbox items)
        for k in range(i + 1, _close_index(toks, i)):
            tk = toks[k]
            if tk.type != "inline" or not tk.map or tk.map[0] in excluded:
                continue
            kids = tk.children or []
            found = refs_in_inline(kids, path=path, line=tk.map[0] + 1)
            for f in found:
                result.warnings.extend(f.warnings)
            for ref in _spec_refs(found):
                add_rel(result.rels, seen, Rel("GOVERNED_BY", task_id, ref, rel_props(ref)))
            for f in found:
                if f.spec and f.checks:
                    for n in f.checks:
                        ac = Ref("id", f"{f.spec}#ac{n}", f.line)
                        add_rel(result.rels, seen, Rel("VERIFIES", task_id, ac))
            for ident in backticked(kids):
                add_rel(result.rels, seen, Rel("MENTIONS", task_id, Ref("mention", ident, line)))
    return out


def _assemble(first: str, rest: list[str]) -> str:
    """Join a task's lines: continuation lines with spaces, nested bullets on their own line."""
    parts = [first]
    for ln in rest:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^[-*+] ", s):
            parts.append("\n" + s)
        else:
            parts.append(" " + s)
    text = "".join(parts)
    text = _LINK_TEXT_RE.sub(r"\1", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _after(title: str) -> tuple[list[str], list[str]]:
    """Task IDs from a trailing ``(after M02.1, M01.4)`` and the tokens that are not task IDs."""
    head = title.partition("\n")[0]
    m = _AFTER_RE.search(head)
    if not m:
        return [], []
    ids: list[str] = []
    bad: list[str] = []
    for raw_tok in re.split(r"\s*(?:,|\band\b)\s*", m.group(1).strip()):
        tok = raw_tok.strip()
        if not tok:
            continue
        if _TASK_ID_RE.match(tok):
            ids.append(normalise(tok))
        else:
            bad.append(tok)
    return ids, bad


def _status(
    toks: list[Token], lines: list[str], any_checked: bool
) -> tuple[str | None, str | None, str]:
    for i, t in enumerate(toks):
        if t.type != "paragraph_open" or t.level != 0 or not t.map:
            continue
        inline = toks[i + 1]
        kids = [k for k in inline.children or [] if k.type != "text" or k.content]
        rendered = render_plain(kids).lstrip()
        if not (kids and kids[0].type == "strong_open" and rendered.startswith("Status:")):
            continue
        end = t.map[1]
        nxt = i + 3
        if nxt < len(toks) and toks[nxt].type == "bullet_list_open" and toks[nxt].map:
            end = toks[nxt].map[1]  # type: ignore[index]
        raw = "\n".join(lines[t.map[0] : end]).strip()
        body = rendered[len("Status:") :].strip(" *")
        has_list = end != t.map[1]
        if not body and not has_list:
            return None, None, "in_progress" if any_checked else "todo"
        if re.match(r"(?i)done\b", body):
            m = _DATE_RE.search(raw)
            return raw, (m.group(1) if m else None), "done"
        return raw, None, "in_progress" if any_checked else "todo"
    return None, None, "in_progress" if any_checked else "todo"
