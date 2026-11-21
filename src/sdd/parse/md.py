"""Shared Markdown helpers (plan M01a §4): one parser instance, slugs, headings, header blocks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

__all__ = [
    "HeaderPair",
    "content_hash",
    "github_slug",
    "header_pairs",
    "heading_text",
    "id_slug",
    "inline_children",
    "nl",
    "render_plain",
    "split_number",
    "tokens",
]

_MD = MarkdownIt("commonmark").enable("table")


def nl(text: str) -> str:
    """Normalise ``\r\n`` and ``\r`` to ``\n`` (line numbers are unchanged)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def tokens(text: str) -> list[Token]:
    """Block tokens of ``text`` (already newline-normalised by the caller)."""
    return _MD.parse(text)


def inline_children(md_text: str) -> list[Token]:
    """Inline tokens of a Markdown fragment (no block structure)."""
    out: list[Token] = []
    for tok in _MD.parseInline(nl(md_text)):
        out.extend(tok.children or [])
    return out


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def render_plain(children: list[Token] | None) -> str:
    """Inline children as plain text: code loses backticks, link text kept, emphasis dropped."""
    out: list[str] = []
    for ch in children or []:
        if ch.type in ("text", "code_inline"):
            out.append(ch.content)
        elif ch.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif ch.type == "image":
            out.append(ch.content)
    return "".join(out)


def heading_text(inline: Token) -> str:
    return render_plain(inline.children).strip()


_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$")


def split_number(heading: str) -> tuple[str | None, str]:
    """``'5.2 Chunking'`` → ``('5.2', 'Chunking')``; ``'6. Global'`` → ``('6', 'Global')``."""
    m = _NUMBER_RE.match(heading)
    if m:
        return m.group(1), m.group(2).strip()
    return None, heading.strip()


def github_slug(text: str) -> str:
    """GitHub's heading anchor (without ``#`` and without the ``-1`` duplicate suffix)."""
    kept = "".join(ch for ch in text.lower() if ch.isalnum() or ch in "_- ")
    return kept.replace(" ", "-")


_NUMERIC_SLUG_RE = re.compile(r"^(?:\d+(?:\.\d+)*|ac\d+)$")


def id_slug(title: str) -> str:
    """Our section-ID slug (SPEC-02 §1): lower-case ``[a-z0-9_-]``, never numeric-looking."""
    slug = re.sub(r"[^a-z0-9_]+", "-", title.lower().replace("`", "")).strip("-_")
    if not slug:
        return "section"
    if _NUMERIC_SLUG_RE.match(slug):
        return f"s-{slug}"
    return slug


@dataclass(frozen=True, slots=True)
class HeaderPair:
    key: str
    value: str  # whitespace collapsed
    raw: str  # as written (``\n`` between source lines, `` · `` between pieces)
    line: int  # 1-based line of the ``**Key:**``


_QUOTE_RE = re.compile(r"^(?:\s*>)+ ?")
_KEY_RE = re.compile(r"^\*\*(?P<key>[^*\n]+?):\*\*\s*(?P<val>.*)$", re.DOTALL)


def header_pairs(
    raw_lines: list[str], first_line: int
) -> tuple[list[HeaderPair], list[tuple[int, str]]]:
    """Split a header blockquote's raw lines into ``**Key:** value`` pairs and Feature lines.

    Pairs split on `` · ``; a piece without a ``**Key:**`` start continues the previous value.
    Lines starting ``**Feature:**`` are returned separately as ``(line, text)``.
    """
    keys: list[tuple[str, int, list[str]]] = []  # key, line, raw chunks (sep+text)
    features: list[tuple[int, str]] = []
    for i, raw in enumerate(raw_lines):
        lineno = first_line + i
        line = _QUOTE_RE.sub("", raw).strip()
        if not line:
            continue
        if line.startswith("**Feature:**"):
            features.append((lineno, line))
            keys_open = False
        else:
            keys_open = True
        if not keys_open:
            continue
        for j, piece in enumerate(line.split(" · ")):
            m = _KEY_RE.match(piece)
            if m:
                keys.append((m["key"].strip(), lineno, [m["val"]]))
            elif keys:
                sep = " · " if j > 0 else "\n"
                keys[-1][2].append(sep + piece)
    pairs = []
    for key, lineno, chunks in keys:
        raw_val = "".join(chunks).strip()
        pairs.append(HeaderPair(key, re.sub(r"\s+", " ", raw_val), raw_val, lineno))
    return pairs, features
