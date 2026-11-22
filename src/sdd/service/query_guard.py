"""The query guard (SPEC-09 §3): read-only Cypher for the ``query`` tool, ``POST /api/query``
and ``sdd query``.

Three layers, each enough on its own for the cases it covers:

1. **Tokens.** The statement is tokenised (strings, backticked names and comments skipped) and
   rejected with ``query_rejected`` if it holds a write or procedure keyword, a second statement,
   or a variable-length pattern without an upper bound of at most 4 (``*``, ``*2..``, ``*..9``).
2. **Rollback.** It runs in a transaction that is always rolled back, so a write that slips past
   step 1 changes nothing (a ``read_only`` connection accepts writes inside a transaction and
   refuses only at commit, O11).
3. **Snapshot.** It runs on a fresh ``read_only=True`` snapshot (O12), off the writer's queue.

Limits: 100 rows (``truncated: true`` beyond); ``settings.query_timeout`` (5 s);
``settings.query_memory_mb``. ``relate-db`` 1.2.0 has no per-query timeout, row cap or memory
cap (O4), so a store on disk is queried in a worker process (``graph.store.QueryProcess``) that
is killed at the time limit or dies at its memory cap; the caller gets ``query_timeout``. An
in-memory store has no file for a worker to open, so its queries run on a thread that cannot be
stopped. One gate per process lets **one** guarded query run at a time; the next waits up to
the same limit.
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any

from sdd.errors import SddError
from sdd.service.coordination import agent_name, seen
from sdd.service.runtime import Runtime

__all__ = ["FORBIDDEN", "MAX_HOPS", "MAX_ROWS", "check", "run_query", "tokenize"]

MAX_ROWS = 100
MAX_HOPS = 4
MAX_CHARS = 20_000
FORBIDDEN = frozenset(
    {
        "CREATE",
        "MERGE",
        "SET",
        "DELETE",
        "DETACH",
        "REMOVE",
        "DROP",
        "LOAD",
        "FOREACH",
        "CALL",
        "USE",
    }
)

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<line>//[^\n]*)
  | (?P<block>/\*.*?(?:\*/|\Z))
  | (?P<str>'(?:[^'\\]|\\.)*(?:'|\Z)|"(?:[^"\\]|\\.)*(?:"|\Z))
  | (?P<name>`(?:[^`]|``)*(?:`|\Z))
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<num>\d+)
  | (?P<op>\.\.|.)
    """,
    re.VERBOSE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class Token:
    kind: str  # word | num | op | name | str
    text: str


def tokenize(cypher: str) -> list[Token]:
    """Significant tokens: whitespace and comments dropped; strings and backticked names kept
    as single opaque tokens, so their contents never look like keywords."""
    out: list[Token] = []
    for m in _TOKEN.finditer(cypher):
        kind = m.lastgroup or "op"
        if kind in ("ws", "line", "block"):
            continue
        out.append(Token(kind, m.group()))
    return out


def _reject(message: str, **details: Any) -> SddError:
    return SddError("query_rejected", message, details=details or None)


def check(cypher: str) -> None:
    """Step 1 and the hop bound (SPEC-09 §3 steps 1 and 4); ``query_rejected`` on failure."""
    if not cypher.strip():
        raise SddError("invalid_input", "cypher must not be empty.")
    if len(cypher) > MAX_CHARS:
        raise SddError("invalid_input", f"cypher is longer than {MAX_CHARS} characters.")
    tokens = tokenize(cypher)
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1].text if i else ""
        if tok.kind == "word":
            word = tok.text.upper()
            # a property (n.set) or parameter ($set) is a name, not a clause
            if prev in (".", "$"):
                continue
            if word in FORBIDDEN:
                raise _reject(f"{word} is not allowed: queries are read-only.", keyword=word)
            nxt = tokens[i + 1].text.upper() if i + 1 < len(tokens) else ""
            if word == "IN" and nxt == "TRANSACTIONS":
                raise _reject("IN TRANSACTIONS is not allowed.", keyword="IN TRANSACTIONS")
        elif tok.text == ";" and any(t.text != ";" for t in tokens[i + 1 :]):
            raise _reject("Only one statement is allowed.")
    _check_hops(tokens)


def _check_hops(tokens: list[Token]) -> None:
    """Every ``*`` inside a relationship pattern (``-[ … ]-``) needs an upper bound ≤ 4."""
    depth = 0  # nesting of '[' inside the current relationship pattern
    for i, tok in enumerate(tokens):
        if tok.text == "[":
            if depth:
                depth += 1
            elif i and tokens[i - 1].text == "-":
                depth = 1
        elif tok.text == "]" and depth:
            depth -= 1
        elif tok.text == "*" and depth == 1:
            _check_bound(tokens, i)


def _check_bound(tokens: list[Token], star: int) -> None:
    rest = [t.text for t in tokens[star + 1 : star + 4]]
    low: str | None = None
    if rest and rest[0].isdigit():
        low = rest.pop(0)
    if not rest or rest[0] != "..":
        if low is None:
            raise _reject(
                f"A variable-length pattern needs an upper bound: use *..{MAX_HOPS} at most.",
                pattern="*",
            )
        high: str | None = low  # *3 means exactly 3
    else:
        high = rest[1] if len(rest) > 1 and rest[1].isdigit() else None
        if high is None:
            raise _reject(
                f"A variable-length pattern needs an upper bound: use *..{MAX_HOPS} at most.",
                pattern=f"*{low or ''}..",
            )
    if high is not None and int(high) > MAX_HOPS:
        raise _reject(
            f"Variable-length patterns go at most {MAX_HOPS} hops (*..{MAX_HOPS}).",
            pattern=f"*{low or ''}..{high}",
        )


# ---------------------------------------------------------------- running


def _execute(
    runtime: Runtime, cypher: str, params: dict[str, Any]
) -> tuple[list[str], list[list[Any]]]:
    """Steps 2 and 3: a rolled-back transaction on a ``read_only`` snapshot."""
    try:
        return runtime.store.query_snapshot(cypher, params, limit=MAX_ROWS + 1)
    except SddError:
        raise
    except Exception as exc:  # the engine's syntax and runtime errors
        raise SddError(
            "invalid_input", f"The query failed: {str(exc).splitlines()[0][:300]}"
        ) from None


def run_query(
    runtime: Runtime,
    cypher: str,
    params: dict[str, Any] | None = None,
    agent: str | None = None,
    *,
    tokens_checked: bool = True,
) -> dict[str, Any]:
    """``{columns, rows, truncated, synced_at}`` for one read-only statement.

    ``tokens_checked=False`` skips step 1; only the tests use it, to prove that the rollback
    alone keeps the store unchanged (SPEC-09 §6 check 5).
    """
    name = agent_name(agent, required=False)
    if params is not None and (
        not isinstance(params, dict) or not all(isinstance(k, str) for k in params)
    ):
        raise SddError("invalid_input", "params must be a JSON object.")
    if not isinstance(cypher, str):
        raise SddError("invalid_input", "cypher must be a string.")
    if tokens_checked:
        check(cypher)
    seen(runtime, name)
    limit = runtime.settings.query_timeout
    gate = runtime.query_gate
    if not gate.acquire(timeout=limit):
        raise SddError(
            "query_timeout",
            f"Another query is still running; try again in a few seconds (limit {limit:g} s).",
            retryable=True,
        )
    if runtime.store.in_memory:
        columns, rows = _on_thread(runtime, cypher, params, gate, limit)
    else:
        # a store on disk: the worker process, killed at the limit (it holds the gate till then)
        try:
            columns, rows = runtime.queries().run(
                runtime.store.path, cypher, params, limit=MAX_ROWS + 1, timeout=limit
            )
        finally:
            gate.release()
    return {
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "truncated": len(rows) > MAX_ROWS,
        "synced_at": runtime.synced(),
    }


def _on_thread(
    runtime: Runtime,
    cypher: str,
    params: dict[str, Any] | None,
    gate: threading.Lock,
    limit: float,
) -> tuple[list[str], list[list[Any]]]:
    """An in-memory store has no file a worker process could open: run on a thread, which
    cannot be stopped, so the gate stays held until the abandoned query really ends."""
    future: Future[tuple[list[str], list[list[Any]]]] = Future()

    def work() -> None:
        try:
            future.set_result(_execute(runtime, cypher, dict(params or {})))
        except BaseException as exc:
            future.set_exception(exc)
        finally:
            gate.release()  # only when the query has really ended

    try:
        threading.Thread(target=work, name="sdd-query", daemon=True).start()
    except BaseException:
        gate.release()
        raise
    try:
        return future.result(timeout=limit)
    except TimeoutError:
        raise SddError(
            "query_timeout",
            f"The query ran longer than {limit:g} s. Add a LIMIT or narrow the pattern.",
            retryable=True,
        ) from None
