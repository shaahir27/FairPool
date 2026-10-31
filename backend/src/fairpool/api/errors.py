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

from fairpool.domain.errors import ApplicationError
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


_APPLICATION_ERRORS: Final[dict[str, tuple[int, str]]] = {
    "VALIDATION_ERROR": (422, "Body or parameters invalid."),
    "UNAUTHENTICATED": (401, "No valid session or token."),
    "FORBIDDEN": (403, "Wrong role or not the owner."),
    "NOT_FOUND": (404, "Unknown resource."),
    "RATE_LIMITED": (429, "Over the limit."),
    "IDEMPOTENCY_KEY_REQUIRED": (400, "Missing `Idempotency-Key`."),
    "IDEMPOTENCY_CONFLICT": (409, "Same key, different body."),
    "FEATURE_DISABLED": (403, "Helper or toggle not enabled."),
    "POOL_NOT_OPEN": (409, "Pool is not OPEN."),
    "POOL_CLOSED": (409, "The entry window has closed."),
    "PAYPAL_LINK_REQUIRED": (403, "The pool needs a linked PayPal account."),
    "PAYPAL_LINK_CONFLICT": (
        409,
        "Account key already linked to another user, or relink blocked by active entries.",
    ),
    "REQUEST_INVALID": (422, "Confirmed request fails pool validation."),
    "NO_MATCHING_POOL": (404, "No open pool matches."),
    "DELEGATION_INVALID": (401, "Agent token unknown, expired or revoked."),
    "DELEGATION_CAP_EXCEEDED": (403, "Agent cap above the delegation limit."),
    "API_KEY_INVALID": (401, "Merchant API key unknown, revoked or malformed."),
    "API_KEY_SCOPE": (403, "The key lacks the scope for this operation."),
    "LOT_NOT_FUNDED": (
        409,
        "Fulfillment, shipments or manifest requested before the lot is FUNDED.",
    ),
    "VAULT_REQUIRED": (409, "The entry has no active saved PayPal permission."),
    "VAULT_SETUP_EXPIRED": (409, "The saving step was not completed in time."),
    "SHIPMENT_INVALID": (422, "A shipment row is invalid (reported per row)."),
    "BID_FORBIDDEN": (403, "Not your bid or lot."),
    "LOT_NOT_BIDDING": (409, "Lot not in BIDDING."),
    "BID_WINDOW_CLOSED": (409, "Past the bid deadline."),
    "BID_UNCONFIRMED": (409, "Fields not confirmed by the merchant."),
    "OFFER_EXPIRED": (409, "Offer window ended."),
    "SEAT_NOT_VALID": (409, "The seat was released."),
    "ORDER_STATE_INVALID": (409, "Action not allowed in the order's state."),
    "PAYPAL_UNAVAILABLE": (502, "PayPal call failed after retries."),
    "INTERNAL_ERROR": (500, "Unexpected."),
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
    if isinstance(exc.detail, str) and exc.detail in _APPLICATION_ERRORS:
        allowed_status, public_message = _APPLICATION_ERRORS[exc.detail]
        if allowed_status == status_code:
            code, message = exc.detail, public_message
    headers = dict(exc.headers) if exc.headers else None
    return error_response(
        status_code=status_code,
        code=code,
        message=message,
        request=request,
        headers=headers,
    )


async def application_exception_handler(request: Request, exc: ApplicationError) -> JSONResponse:
    status, message = _APPLICATION_ERRORS.get(exc.code, (500, "An unexpected error occurred."))
    return error_response(
        status_code=status,
        code=exc.code if exc.code in _APPLICATION_ERRORS else "INTERNAL_ERROR",
        message=message,
        request=request,
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
    app.add_exception_handler(ApplicationError, application_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
