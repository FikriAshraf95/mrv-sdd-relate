"""Node ID formats and normalisation (SPEC-02 §1).

Stdlib only (SPEC-01 §3), so an invalid ID raises :class:`InvalidIdError` (a ``ValueError``);
callers in ``service/`` map it to ``invalid_input``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

__all__ = [
    "InvalidIdError",
    "id_from_filename",
    "label_of",
    "normalise",
]


class InvalidIdError(ValueError):
    """The text is not any node ID form from SPEC-02 §1."""


# Path-keyed and name-keyed IDs: `<prefix>:<rest>`. Prefixes are lower-case.
_PATH_PREFIXES = {"doc": "Doc", "dir": "Folder", "file": "File"}
_NAME_PREFIXES = {
    "table": "Table",
    "column": "Column",
    "feature": "Feature",
    "domain": "Domain",
    "agent": "Agent",
}

_SEC_NUM = r"\d+(?:\.\d+)*"

# SPEC-03 §5.2, `SPEC-03 §5.2`, `spec-03#5.2`, `SPEC-3 5.2`, `SPEC-03§5.2`, `SPEC-03#ac6`,
# `SPEC-02#attachments`. The separator is `§`, `#` or whitespace, with or without spaces around
# it ("nothing" in SPEC-02 §1 means `SPEC-03§5.2`; `SPEC-035.2` would be ambiguous).
_SPEC_RE = re.compile(
    rf"""^SPEC\s*-?\s*(?P<num>\d+)
        (?:
            (?:\s*[§#]\s*|\s+)
            (?:(?P<sec>{_SEC_NUM})|AC\s*(?P<ac>\d+)|(?P<slug>[a-z0-9][a-z0-9_-]*))
        )?$""",
    re.IGNORECASE | re.VERBOSE,
)
# `M02`, `m2`, `M20F`, `M100`, `M02.3`, `m20f.12`
_MILESTONE_RE = re.compile(r"^M\s*(?P<num>\d+)(?P<suffix>[a-z])?(?:\.(?P<task>\d+))?$", re.I)
_DEVIATION_RE = re.compile(r"^D\s*-?\s*(?P<num>\d+)$", re.I)
_COMMIT_RE = re.compile(r"^commit:(?P<sha>[0-9a-f]{40}|[0-9a-f]{64})$", re.I)
_EVENT_RE = re.compile(r"^event:(?P<ulid>[0-9A-HJKMNP-TV-Z]{26})$", re.I)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")

# File-name IDs: `SPEC-3-x.md` → SPEC-03, `M2-x.md` → M02, `M20f-plan.md` → M20f, `D12-x.md` → D012
_FILENAME_RE = re.compile(
    r"^(?:(?P<spec>SPEC-\d+)|(?P<ms>M\d+[a-z]?)|(?P<dev>D\d+))(?=-|\.md$)", re.IGNORECASE
)


def _pad(num: str, width: int) -> str:
    return str(int(num)).zfill(width)


def _spec(num: str) -> str:
    return f"SPEC-{_pad(num, 2)}"


def _norm_path(raw: str, original: str) -> str:
    path = raw.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    path = path.rstrip("/")
    if not path or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise InvalidIdError(f"{original!r}: paths in IDs are relative to the project root")
    parts = PurePosixPath(path).parts
    if any(p in ("..", ".") for p in parts):
        raise InvalidIdError(f"{original!r}: paths in IDs may not contain '.' or '..'")
    return "/".join(parts)


def normalise(text: str) -> str:
    """Return the canonical node ID for any form people type.

    Prefixes are upper-cased (``SPEC``, ``M``, ``D``), milestone letter suffixes lower-cased,
    spec and milestone numbers zero-padded to at least 2 digits and deviation numbers to 3.
    ``§``, ``#``, a space or nothing may separate a spec from its section number.

    >>> normalise("SPEC-3 5.2"), normalise("m2.3"), normalise("d12")
    ('SPEC-03#5.2', 'M02.3', 'D012')
    """
    if not isinstance(text, str):
        raise InvalidIdError(f"an ID must be a string, got {type(text).__name__}")
    s = text.strip()
    if not s:
        raise InvalidIdError("empty ID")

    if s.lower() == "meta":
        return "meta"

    prefix, sep, rest = s.partition(":")
    if sep:
        key = prefix.strip().lower()
        if key in _PATH_PREFIXES:
            return f"{key}:{_norm_path(rest, text)}"
        if key in _NAME_PREFIXES:
            return _name_id(key, rest.strip(), text)
        if key == "commit":
            if m := _COMMIT_RE.match(f"commit:{rest.strip()}"):
                return f"commit:{m['sha'].lower()}"
            raise InvalidIdError(f"{text!r}: a commit ID is 'commit:<full sha>'")
        if key == "event":
            if m := _EVENT_RE.match(f"event:{rest.strip()}"):
                return f"event:{m['ulid'].upper()}"
            raise InvalidIdError(f"{text!r}: an event ID is 'event:<ulid>'")

    if m := _SPEC_RE.match(s):
        spec = _spec(m["num"])
        if m["sec"]:
            return f"{spec}#{m['sec']}"
        if m["ac"]:
            return f"{spec}#ac{int(m['ac'])}"
        if m["slug"]:
            return f"{spec}#{m['slug'].lower()}"
        return spec
    if m := _MILESTONE_RE.match(s):
        ms = f"M{_pad(m['num'], 2)}{(m['suffix'] or '').lower()}"
        return f"{ms}.{int(m['task'])}" if m["task"] else ms
    if m := _DEVIATION_RE.match(s):
        return f"D{_pad(m['num'], 3)}"

    raise InvalidIdError(
        f"{text!r} is not a node ID. Use forms like SPEC-03, SPEC-03 §5.2, M02, M02.3, D012, "
        "file:src/x.py"
    )


def _name_id(key: str, rest: str, original: str) -> str:
    if key in ("feature", "domain"):
        slug = rest.lower()
        if _SLUG_RE.match(slug):
            return f"{key}:{slug}"
        raise InvalidIdError(f"{original!r}: a {key} ID is '{key}:<slug>' (a-z, 0-9, '-', '_')")
    if key == "column":
        table, dot, col = rest.partition(".")
        if dot and _NAME_RE.match(table) and _NAME_RE.match(col) and "." not in col:
            return f"column:{table}.{col}"
        raise InvalidIdError(f"{original!r}: a column ID is 'column:<table>.<name>'")
    if _NAME_RE.match(rest) and not (key == "table" and "." in rest):
        return f"{key}:{rest}"
    raise InvalidIdError(f"{original!r}: a {key} ID is '{key}:<name>'")


def label_of(node_id: str) -> str:
    """The SPEC-02 label a canonical ID belongs to (``normalise`` it first)."""
    prefix, sep, _ = node_id.partition(":")
    if sep:
        if prefix in _PATH_PREFIXES:
            return _PATH_PREFIXES[prefix]
        if prefix in _NAME_PREFIXES:
            return _NAME_PREFIXES[prefix]
        if prefix == "commit":
            return "Commit"
        if prefix == "event":
            return "Event"
    if node_id == "meta":
        return "Meta"
    if node_id.startswith("SPEC-"):
        _, hash_, part = node_id.partition("#")
        if not hash_:
            return "Spec"
        return "AcceptanceCheck" if re.fullmatch(r"ac\d+", part) else "Section"
    if node_id.startswith("M"):
        return "Task" if "." in node_id else "Milestone"
    if node_id.startswith("D"):
        return "Deviation"
    raise InvalidIdError(f"{node_id!r} is not a canonical node ID")


def id_from_filename(name: str) -> str | None:
    """The Spec, Milestone or Deviation ID a file name starts with, padded like ``normalise``.

    ``SPEC-3-sync.md`` → ``SPEC-03``, ``M2-x.md`` → ``M02``, ``M20f-plan.md`` → ``M20f``,
    ``D12-title.md`` → ``D012``. Returns ``None`` for other names.
    """
    m = _FILENAME_RE.match(PurePosixPath(name.replace("\\", "/")).name)
    if not m:
        return None
    return normalise(m["spec"] or m["ms"] or m["dev"])
