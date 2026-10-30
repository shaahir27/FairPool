"""FastAPI application factory (T00A03).

`create_app()` never loads settings by itself; the composition root (main.py,
tests) passes a `Settings` instance when one is needed. That keeps imports
environment-free and `/health` usable before configuration exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from fairpool.api.errors import REQUEST_ID_HEADER, register_exception_handlers
from fairpool.api.routers import health
from fairpool.api.routers.health import ReadinessProbe
from fairpool.config import (
    SANDBOX_API_HOST,
    SANDBOX_CHECKOUT_HOST,
    Settings,
    assert_sandbox_host,
)
from fairpool.logging import request_id


async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a correlation ID to the contextvar and the response."""
    value = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
    token = request_id.set(value)
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    response.headers[REQUEST_ID_HEADER] = value
    return response


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    if settings is not None:
        # Defence in depth: Settings validates at load, the factory checks again
        # so a hand-built object cannot reach production with a live host.
        assert_sandbox_host(settings.paypal_api_base, SANDBOX_API_HOST)
        assert_sandbox_host(settings.paypal_checkout_base, SANDBOX_CHECKOUT_HOST)

    app = FastAPI(title="FairPool API", version="0.1.0")
    app.state.settings = settings
    app.state.readiness_probe = readiness_probe

    if settings is not None and settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.middleware("http")(add_request_id)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app
