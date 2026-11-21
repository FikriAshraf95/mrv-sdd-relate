"""HTTP statuses of the error codes (SPEC-07 §1 rule 2) and the error response."""

from __future__ import annotations

from starlette.responses import JSONResponse

from sdd.errors import SddError

__all__ = ["HTTP_STATUS", "error_response"]

# A code without a status here is a bug; a test asserts the keys equal ``errors.CODES``.
HTTP_STATUS: dict[str, int] = {
    "invalid_input": 400,
    "query_rejected": 400,
    "ambiguous_target": 400,
    "unauthorized": 401,
    "read_only": 403,
    "forbidden_origin": 403,
    "forbidden_host": 403,
    "writeback_disabled": 403,
    "task_not_found": 404,
    "milestone_not_found": 404,
    "node_not_found": 404,
    "file_not_found": 404,
    "unknown_section": 404,
    "already_claimed": 409,
    "task_done": 409,
    "task_blocked": 409,
    "not_claimed_by_you": 409,
    "milestone_incomplete": 409,
    "source_changed": 409,
    "daemon_running": 409,  # SPEC-07 §1 rule 2 (added in M02)
    "rate_limited": 429,
    "write_conflict": 503,
    "query_timeout": 503,
}


def error_response(err: SddError) -> JSONResponse:
    headers = {"Retry-After": "1"} if err.code == "rate_limited" else None
    return JSONResponse(err.to_dict(), status_code=HTTP_STATUS[err.code], headers=headers)
