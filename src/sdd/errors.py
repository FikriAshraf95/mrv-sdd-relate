"""The one error type for MCP, HTTP and CLI (SPEC-00 §6.4, codes in SPEC-05 §8).

Stdlib only (SPEC-01 §3).
"""

from __future__ import annotations

from typing import Any

# SPEC-05 §8: the complete list. A new code is added there and here in the same change.
CODES: frozenset[str] = frozenset(
    {
        "invalid_input",
        "task_not_found",
        "milestone_not_found",
        "node_not_found",
        "file_not_found",
        "unknown_section",
        "ambiguous_target",
        "already_claimed",
        "task_done",
        "task_blocked",
        "not_claimed_by_you",
        "milestone_incomplete",
        "source_changed",
        "writeback_disabled",
        "write_conflict",
        "query_rejected",
        "query_timeout",
        "daemon_running",
        "read_only",
        "unauthorized",
        "forbidden_origin",
        "forbidden_host",
        "rate_limited",
    }
)

# Codes that are retryable by definition (SPEC-05 §8).
RETRYABLE: frozenset[str] = frozenset({"write_conflict", "rate_limited"})


class SddError(Exception):
    """An expected failure with a stable ``code``.

    ``message`` says what happened and what to do next. Callers and tests branch on ``code``,
    never on ``message``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if code not in CODES:
            raise ValueError(f"unknown error code {code!r}: add it to SPEC-05 §8 and errors.CODES")
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = code in RETRYABLE if retryable is None else retryable
        self.details: dict[str, Any] = dict(details) if details else {}

    def to_dict(self) -> dict[str, Any]:
        """The wire shape: ``{"error": {"code", "message", "retryable", "details"}}``."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            }
        }

    def __repr__(self) -> str:
        return f"SddError({self.code!r}, {self.message!r})"
