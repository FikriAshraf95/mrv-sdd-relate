"""Link and spec-reference extraction and resolution (SPEC-03 §2, plan M01a §3).

Pure: inline tokens in, :class:`Found` expressions out; the resolver works on a
:class:`Catalog` built from parse results, not on a graph.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import unquote

from markdown_it.token import Token

from sdd.ids import InvalidIdError, id_from_filename, label_of, normalise
from sdd.parse.md import id_slug, inline_children
from sdd.parse.model import ParseResult, ParseWarning, Ref, warn

__all__ = [
    "DOC_STEMS",
    "Catalog",
    "Found",
    "Resolution",
    "backticked",
    "deviation_ids",
    "expand_range",
    "has_deviation_marker",
    "milestone_ids",
    "refs_in_inline",
    "refs_in_markdown",
    "resolve",
    "spec_refs",
]

DOC_STEMS = ("design-system", "IDEA", "HANDOFF", "README", "CLAUDE")
MAX_RANGE = 50
MAX_CHECKS = 100

# --------------------------------------------------------------------------- grammar (§2.2)
_NUM = r"\d+(?:\.\d+)*"
_RANGE = rf"{_NUM}(?:\s?[–-]\s?§?\s?{_NUM})?"
_PART = rf"(?:§\s?{_RANGE}|`[A-Za-z0-9_-]+`)"
_SECTIONS = rf"{_PART}(?:\s*(?:,|\band\b)\s*{_PART})*"

_SPEC_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])SPEC-(?P<num>\d+)(?:\s*(?P<secs>{_SECTIONS}))?"
    rf"(?:\s*\((?P<whole>whole file|whole section)\))?"
)
_DOC_SECS = rf"§\s?{_RANGE}(?:\s*(?:,|\band\b)\s*§\s?{_RANGE})*"
_DOC_RE = re.compile(
    rf"(?<![A-Za-z0-9_./-])(?P<stem>{'|'.join(re.escape(s) for s in DOC_STEMS)})(?:\.md)?"
    rf"\s*(?P<secs>{_DOC_SECS})"
)
_BARE_RE = re.compile(rf"(?P<secs>§\s?{_RANGE}(?:\s*(?:,|\band\b)\s*{_PART})*)")
_PART_ITER = re.compile(
    rf"§\s?(?P<a>{_NUM})(?:\s?[–-]\s?§?\s?(?P<b>{_NUM}))?|`(?P<ident>[A-Za-z0-9_-]+)`"
)

_LOOK_WHOLE = re.compile(r"\s*\((?P<w>whole file|whole section)\)")
_LOOK_CHECKS = re.compile(
    r"\s*,?\s*checks?\s+(?P<l>\d+(?:\s*[–-]\s*\d+)?"
    r"(?:\s*(?:,|\band\b)\s*\d+(?:\s*[–-]\s*\d+)?)*)"
)
_LOOK_PAREN = re.compile(r"\s*\((?P<n>[^()\n]{1,100})\)")
_LOOK_KEYWORD = re.compile(
    r"\s*(?P<n>(?:step|invariant|item|rule|case|row)s?\s+\d+(?:\s*[–-]\s*\d+)?)", re.IGNORECASE
)
_EXTERNAL_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
_DEV_RE = re.compile(r"(?<![A-Za-z0-9_])D\d{3,}\b")
_MS_RE = re.compile(r"(?<![A-Za-z0-9_])M\d+[a-z]?\b(?!\.\d)")
_MENTION_RE = re.compile(r"^[A-Za-z0-9_./-]+$")


@dataclass(frozen=True, slots=True)
class Found:
    """One reference expression: the Refs it produced plus what followed it.

    ``spec`` is the spec ID the expression names (used by VERIFIES); ``checks`` are the
    acceptance-check numbers that followed it (``checks 3–9, 12``).
    """

    refs: tuple[Ref, ...]
    start: int
    end: int
    line: int
    spec: str | None = None
    checks: tuple[int, ...] = ()
    warnings: tuple[ParseWarning, ...] = ()


# --------------------------------------------------------------------------- flattening
@dataclass(slots=True)
class _Link:
    start: int
    end: int
    href: str


@dataclass(slots=True)
class _Flat:
    plain: str
    incode: list[bool]
    links: list[_Link]
    codes: list[str] = field(default_factory=list)


def _flatten(children: list[Token] | None) -> _Flat:
    """Plain-text rendering with a per-character code flag and the link regions."""
    parts: list[str] = []
    incode: list[bool] = []
    links: list[_Link] = []
    codes: list[str] = []
    size = 0
    open_link: tuple[int, str] | None = None

    def put(s: str, code: bool) -> None:
        nonlocal size
        parts.append(s)
        incode.extend([code] * len(s))
        size += len(s)

    for ch in children or []:
        t = ch.type
        if t == "text":
            put(ch.content, False)
        elif t == "code_inline":
            put(f"`{ch.content}`", True)
            codes.append(ch.content)
        elif t in ("softbreak", "hardbreak"):
            put("\n", False)
        elif t == "link_open":
            open_link = (size, str(ch.attrGet("href") or ""))
        elif t == "link_close" and open_link is not None:
            links.append(_Link(open_link[0], size, open_link[1]))
            open_link = None
    return _Flat("".join(parts), incode, links, codes)


def _num_list(text: str) -> list[int]:
    """Expand ``3–9, 12 and 14`` (capped at :data:`MAX_CHECKS`)."""
    out: list[int] = []
    for piece in re.split(r"\s*(?:,|\band\b)\s*", text):
        m = re.fullmatch(r"(\d+)(?:\s*[–-]\s*(\d+))?", piece.strip())
        if not m:
            continue
        a = int(m[1])
        b = int(m[2]) if m[2] else a
        out.extend(range(a, b + 1) if a <= b else (a, b))
        if len(out) >= MAX_CHECKS:
            return out[:MAX_CHECKS]
    return out


def expand_range(spec_id: str, start: str, end: str) -> list[str] | None:
    """Section IDs for ``§start–end`` (siblings, inclusive), or ``None`` if it cannot expand."""
    a, b = start.split("."), end.split(".")
    if len(a) != len(b) or a[:-1] != b[:-1]:
        return None
    lo, hi = int(a[-1]), int(b[-1])
    if lo > hi or hi - lo + 1 > MAX_RANGE:
        return None
    prefix = ".".join(a[:-1])
    lead = f"{prefix}." if prefix else ""
    return [f"{spec_id}#{lead}{i}" for i in range(lo, hi + 1)]


# --------------------------------------------------------------------------- lookahead
@dataclass(slots=True)
class _Tail:
    whole: bool = False
    checks: tuple[int, ...] = ()
    note: str | None = None
    pos: int = 0


def _tidy(note: str) -> str | None:
    note = re.sub(r"\s+", " ", note).strip(" ,;:·→—–-()")
    return note[:120] or None


def _look(plain: str, pos: int, limit: int) -> _Tail:
    """What directly follows a reference: ``(whole file)``, ``checks 3–9``, a note."""
    tail = _Tail(pos=pos)
    for _ in range(4):
        if m := _LOOK_WHOLE.match(plain, tail.pos, limit):
            tail.whole = m["w"] == "whole file"
            tail.pos = m.end()
        elif not tail.checks and (m := _LOOK_CHECKS.match(plain, tail.pos, limit)):
            tail.checks = tuple(_num_list(m["l"]))
            tail.pos = m.end()
        elif tail.note is None and (m := _LOOK_KEYWORD.match(plain, tail.pos, limit)):
            tail.note = _tidy(m["n"])
            tail.pos = m.end()
        elif tail.note is None and (m := _LOOK_PAREN.match(plain, tail.pos, limit)):
            inner = m["n"].strip()
            if inner.lower().startswith(("after ", "whole ")) or "SPEC-" in inner:
                break
            tail.note = _tidy(inner)
            tail.pos = m.end()
        else:
            break
    return tail


def _tail_for(plain: str, end_pos: int, lk: _Link | None, bound: int) -> _Tail:
    """Lookahead for an expression, inside its link text first and then past the link."""
    if lk is None:
        return _look(plain, end_pos, len(plain))
    tail = _look(plain, end_pos, bound)
    rest = _tidy(plain[tail.pos : bound])
    if rest and tail.note is None:
        tail.note = rest
    if bound >= lk.end:
        after = _look(plain, lk.end, len(plain))
        tail = _Tail(
            tail.whole or after.whole,
            tail.checks or after.checks,
            tail.note or after.note,
            after.pos,
        )
    return tail


# --------------------------------------------------------------------------- building refs
def _spec_refs(
    spec: str,
    secs: str | None,
    *,
    whole: bool,
    note: str | None,
    line: int,
    path: str,
    text: str,
) -> tuple[list[Ref], list[ParseWarning]]:
    warnings: list[ParseWarning] = []
    if not secs:
        return [Ref("spec", spec, line, whole=whole, note=note, text=text)], warnings
    refs: list[Ref] = []
    for m in _PART_ITER.finditer(secs):
        if m["ident"]:
            refs.append(Ref("slug", spec, line, slug=m["ident"], note=note, text=text))
        elif m["b"]:
            ids = expand_range(spec, m["a"], m["b"])
            if ids is None:
                warnings.append(
                    warn(path, line, "ref_bad_range", f"cannot expand §{m['a']}–{m['b']}")
                )
                ids = [f"{spec}#{m['a']}", f"{spec}#{m['b']}"]
            refs.extend(Ref("section", i, line, note=note, text=text) for i in ids)
        else:
            refs.append(Ref("section", f"{spec}#{m['a']}", line, note=note, text=text))
    return refs, warnings


def _resolve_href(href: str, path: str) -> tuple[str, str | None]:
    """A relative link → (project-relative path, anchor)."""
    target, _, anchor = href.partition("#")
    target, anchor = unquote(target), unquote(anchor)
    if not target:
        return path, anchor or None
    return posixpath.normpath(posixpath.join(posixpath.dirname(path), target)), anchor or None


def _spec_of_target(target: str) -> str | None:
    ident = id_from_filename(posixpath.basename(target))
    return ident if ident and ident.startswith("SPEC-") else None


# --------------------------------------------------------------------------- the scan
def refs_in_inline(children: list[Token] | None, *, path: str, line: int) -> list[Found]:
    """Every link and spec-reference expression in inline children, in document order.

    ``path`` is the linking file; ``line`` the 1-based line of the inline token's first line.
    """
    flat = _flatten(children)
    plain = flat.plain
    if not plain:
        return []

    def line_at(pos: int) -> int:
        return line + plain.count("\n", 0, pos)

    spec_matches = [m for m in _SPEC_RE.finditer(plain) if not flat.incode[m.start()]]
    doc_matches = [
        m
        for m in _DOC_RE.finditer(plain)
        if not flat.incode[m.start()]
        and not any(s.start() <= m.start() < s.end() for s in spec_matches)
    ]
    matches = sorted([*spec_matches, *doc_matches], key=lambda m: m.start())

    def expression(m: re.Match[str], lk: _Link | None, bound: int) -> Found:
        ln = line_at(m.start())
        tail = _tail_for(plain, m.end(), lk, bound)
        if "stem" in m.groupdict() and m.groupdict().get("stem"):
            ref = Ref("doc", m["stem"], ln, note=_tidy(m["secs"]), text=m.group(0))
            return Found((ref,), m.start(), tail.pos, ln, None, tail.checks)
        spec = normalise(f"SPEC-{m['num']}")
        whole = tail.whole or m["whole"] == "whole file"
        refs, warns = _spec_refs(
            spec,
            m["secs"],
            whole=whole and not m["secs"],
            note=tail.note,
            line=ln,
            path=path,
            text=m.group(0),
        )
        return Found(tuple(refs), m.start(), tail.pos, ln, spec, tail.checks, tuple(warns))

    out: list[tuple[int, Found]] = []
    in_some_link: set[int] = set()
    for lk in flat.links:
        inner = [m for m in matches if lk.start <= m.start() < lk.end]
        in_some_link.update(m.start() for m in inner)
        if _EXTERNAL_RE.match(lk.href):
            continue  # external: ignore the link and anything its text says
        target, anchor = _resolve_href(lk.href, path)
        if inner:
            for n, m in enumerate(inner):
                bound = inner[n + 1].start() if n + 1 < len(inner) else lk.end
                out.append((m.start(), expression(m, lk, bound)))
            continue
        spec_of_target = _spec_of_target(target)
        bare = _BARE_RE.search(plain, lk.start, lk.end)
        tail = _look(plain, lk.end, len(plain))
        if bare and spec_of_target and not flat.incode[bare.start()]:
            ln = line_at(bare.start())
            refs, warns = _spec_refs(
                spec_of_target,
                bare["secs"],
                whole=False,
                note=tail.note,
                line=ln,
                path=path,
                text=bare.group(0),
            )
            found = Found(
                tuple(refs), bare.start(), tail.pos, ln, spec_of_target, tail.checks, tuple(warns)
            )
            out.append((bare.start(), found))
            continue
        ln = line_at(lk.start)
        text = plain[lk.start : lk.end]
        ref = Ref("path", target, ln, anchor=anchor, text=text)
        out.append((lk.start, Found((ref,), lk.start, tail.pos, ln, spec_of_target, tail.checks)))

    out.extend(
        (m.start(), expression(m, None, len(plain)))
        for m in matches
        if m.start() not in in_some_link
    )
    out.sort(key=lambda t: t[0])
    return [f for _, f in out]


def refs_in_markdown(md_text: str, *, path: str, line: int) -> list[Found]:
    return refs_in_inline(inline_children(md_text), path=path, line=line)


def spec_refs(raw: str) -> list[Ref]:
    """The section and spec Refs one typed reference names: a canonical ID (``SPEC-03#4.2``,
    ``SPEC-03 §4.2``, ``SPEC-03``), else the §2.2 grammar (``SPEC-02 §3–4``,
    ``SPEC-02 `documents` ``). Empty if it names neither. Used by ``read_section`` and
    ``log_deviation(amends)``.
    """
    try:
        ident = normalise(raw)
        label = label_of(ident)
    except InvalidIdError:
        label = ""
    if label == "Section":
        return [Ref("section", ident, 1)]
    if label == "Spec":
        return [Ref("spec", ident, 1)]
    return [
        ref
        for found in refs_in_markdown(raw, path="", line=1)
        for ref in found.refs
        if ref.kind in ("section", "slug", "spec")
    ]


# --------------------------------------------------------------------------- other mentions (§3.6)
def has_deviation_marker(children: list[Token] | None) -> bool:
    """True when the inline has ``**DEVIATION:**`` as bold text (never inside code)."""
    kids = children or []
    return any(
        kids[i].type == "strong_open"
        and kids[i + 1].type == "text"
        and kids[i + 1].content.strip() == "DEVIATION:"
        and kids[i + 2].type == "strong_close"
        for i in range(len(kids) - 2)
    )


def _unique(items: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _scan_ids(children: list[Token] | None, pattern: re.Pattern[str], prefix: str) -> list[str]:
    flat = _flatten(children)
    external = [lk for lk in flat.links if _EXTERNAL_RE.match(lk.href)]
    found: list[tuple[int, str]] = []
    for m in pattern.finditer(flat.plain):
        if flat.incode[m.start()] or any(lk.start <= m.start() < lk.end for lk in external):
            continue
        found.append((m.start(), normalise(m.group(0))))
    for lk in flat.links:
        if lk in external:
            continue
        ident = id_from_filename(posixpath.basename(unquote(lk.href.partition("#")[0])))
        if ident and ident.startswith(prefix) and "." not in ident:
            found.append((lk.start, ident))
    found.sort(key=lambda t: t[0])
    return _unique(i for _, i in found)


def deviation_ids(children: list[Token] | None) -> list[str]:
    """Normalised ``Dnnn`` mentions (text or link targets), outside code."""
    return _scan_ids(children, _DEV_RE, "D")


def milestone_ids(children: list[Token] | None) -> list[str]:
    """Normalised ``Mnn`` / ``Mnnx`` mentions (not ``M02.3``), text or link targets."""
    return _scan_ids(children, _MS_RE, "M")


def backticked(children: list[Token] | None) -> list[str]:
    """Inline-code identifiers that look like a table name or a path (MENTIONS candidates)."""
    return _unique(
        c
        for c in _flatten(children).codes
        if _MENTION_RE.match(c) and not c.startswith("-") and re.search(r"[A-Za-z]", c)
    )


# --------------------------------------------------------------------------- resolver (§3.7)
@dataclass(slots=True)
class Catalog:
    """What can be resolved: paths, IDs, section anchors and title slugs, doc stems."""

    paths: dict[str, str] = field(default_factory=dict)
    ids: set[str] = field(default_factory=set)
    anchors: dict[str, dict[str, str]] = field(default_factory=dict)
    slugs: dict[str, dict[str, str]] = field(default_factory=dict)
    docs: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_results(cls, results: Iterable[ParseResult]) -> Catalog:
        cat = cls()
        doc_paths: dict[str, str] = {}
        for res in results:
            for node in res.nodes:
                cat.ids.add(node.id)
                if node.label in ("Spec", "Milestone", "Deviation", "Doc"):
                    cat.paths[str(node.props.get("source_path", res.path))] = node.id
                if node.label == "Section":
                    spec = str(node.props["spec_id"])
                    anchor = str(node.props["anchor"]).lstrip("#")
                    cat.anchors.setdefault(spec, {}).setdefault(anchor, node.id)
                    slug = id_slug(str(node.props["title"]))
                    cat.slugs.setdefault(spec, {}).setdefault(slug, node.id)
                if node.label == "Doc":
                    stem = posixpath.splitext(posixpath.basename(res.path))[0]
                    best = doc_paths.get(stem)
                    if best is None or len(res.path) < len(best):
                        doc_paths[stem] = res.path
                        cat.docs[stem] = node.id
        return cat


@dataclass(slots=True)
class Resolution:
    targets: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    warnings: list[ParseWarning] = field(default_factory=list)


def resolve(ref: Ref, catalog: Catalog, *, path: str = "") -> Resolution:
    """Resolve one Ref against a Catalog. ``mention`` Refs are never resolved here."""
    res = Resolution()
    if ref.kind in ("id", "section", "spec"):
        (res.targets if ref.target in catalog.ids else res.unresolved).append(ref.target)
    elif ref.kind == "slug":
        hit = catalog.slugs.get(ref.target, {}).get(id_slug(ref.slug or ""))
        if hit:
            res.targets.append(hit)
        else:
            res.unresolved.append(f"{ref.target} `{ref.slug}`")
    elif ref.kind == "doc":
        hit = catalog.docs.get(ref.target)
        if hit:
            res.targets.append(hit)
        else:
            res.unresolved.append(ref.target)
    elif ref.kind == "path":
        _resolve_path(ref, catalog, res, path)
    return res


def _resolve_path(ref: Ref, catalog: Catalog, res: Resolution, path: str) -> None:
    node = catalog.paths.get(ref.target)
    if node is None:
        ident = id_from_filename(posixpath.basename(ref.target))
        if ident and ident in catalog.ids:
            node = ident
            res.warnings.append(warn(path, ref.line, "link_moved", f"{ref.target} moved to {node}"))
    if node is None:
        res.unresolved.append(ref.target + (f"#{ref.anchor}" if ref.anchor else ""))
        return
    if ref.anchor and node.startswith("SPEC-") and "#" not in node:
        hit = catalog.anchors.get(node, {}).get(ref.anchor)
        if hit:
            res.targets.append(hit)
            return
        res.targets.append(node)
        res.unresolved.append(f"{ref.target}#{ref.anchor}")
        return
    res.targets.append(node)
