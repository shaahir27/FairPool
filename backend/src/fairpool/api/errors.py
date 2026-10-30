"""Error envelope, exception handlers and request IDs (T00A03, api.md section 1).

Every error leaves the API as
`{"error": {"code", "message", "details", "request_id"}}` with a code from
`config-and-errors.md`. Raw exception text is never returned to a client.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from fairpool.logging import request_id

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

logger = logging.getLogger("fairpool.api")

_STATUS_CODES: Final[dict[int, tuple[str, str]]] = {
    400: ("VALIDATION_ERROR", "Bad request."),
    401: ("UNAUTHENTICATED", "Authentication required."),
    403: ("FORBIDDEN", "You do not have permission to perform this action."),
    404: ("NOT_FOUND", "Resource not found."),
    422: ("VALIDATION_ERROR", "Request validation failed."),
}


def current_request_id(request: Request | None = None) -> str:
    """Return the request's correlation ID, creating one if necessary."""
    value = request_id.get()
    if not value and request is not None:
        value = request.headers.get(REQUEST_ID_HEADER)
    return value or uuid.uuid4().hex


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = current_request_id(request)
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = rid
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": rid,
        }
    }
    return JSONResponse(status_code=status_code, content=payload, headers=response_headers)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Only location and message: pydantic's `input` may echo request bodies.
    fields = [
        {
            "loc": ".".join(str(part) for part in error.get("loc", ())),
            "message": str(error.get("msg", "Invalid value.")),
        }
        for error in exc.errors()
    ]
    return error_response(
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed.",
        details={"fields": fields},
        request=request,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status_code = exc.status_code
    default = _STATUS_CODES.get(status_code)
    if default is None:
        if status_code >= 500:
            code, message = "INTERNAL_ERROR", "An unexpected error occurred."
        else:
            code, message = "VALIDATION_ERROR", "Request failed."
    else:
        code, message = default
    headers = dict(exc.headers) if exc.headers else None
    return error_response(
        status_code=status_code,
        code=code,
        message=message,
        request=request,
        headers=headers,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # I14: the type is useful, the message may contain a token, so never log it.
    logger.error("unhandled_exception type=%s", type(exc).__name__)
    return error_response(
        status_code=500,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
        request=request,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
