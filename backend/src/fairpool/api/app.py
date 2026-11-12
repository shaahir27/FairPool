"""FastAPI application factory (T00A03, route surface T01B01).

`create_app()` never loads settings by itself; the composition root (main.py,
tests) passes a `Settings` instance when one is needed. That keeps imports
environment-free and `/health` usable before configuration exists.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.routing import Route

from fairpool.api.errors import REQUEST_ID_HEADER, register_exception_handlers
from fairpool.api.merchant_api.app import app as merchant_api_app
from fairpool.api.routers import (
    admin_ops,
    admin_pools,
    admin_sim,
    agent,
    agent_oauth,
    auth,
    checkout,
    demand,
    entries,
    health,
    intake,
    merchant,
    merchant_fulfillment,
    merchant_keys,
    notifications,
    paypal_login,
    pools,
    public,
    webhooks,
)
from fairpool.api.routers.health import ReadinessProbe
from fairpool.config import (
    SANDBOX_API_HOST,
    SANDBOX_CHECKOUT_HOST,
    Settings,
    assert_sandbox_host,
)
from fairpool.infra.clock import DbClock
from fairpool.infra.metrics import metrics_route
from fairpool.infra.security_headers import SecurityHeadersMiddleware, sanitize_request_id
from fairpool.logging import request_id
from fairpool.modules.mcp.transport import build_mcp_app

#: Where the hosted image puts the built frontend, so the page and the API share one
#: origin. `onrender.com` is on the Public Suffix List, which makes the two
#: *.onrender.com subdomains cross-site, and a cross-site SameSite=Lax cookie set in a
#: fetch response is dropped: login answered 200 and /me then read 401.
WEB_DIR: Final = Path("/app/web")
_API_PREFIXES: Final = frozenset(
    {
        "api",
        "docs",
        "health",
        "mcp",
        "merchant-api",
        "openapi.json",
        "ready",
        "redoc",
        "webhooks",
    }
)


def _serve_web(app: FastAPI) -> None:
    """Serve the SPA from this origin when the image carries it."""
    index = WEB_DIR / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="web_assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def web_client(path: str) -> FileResponse:
        first = path.split("/", 1)[0]
        if first in _API_PREFIXES:
            raise HTTPException(status_code=404)
        file = (WEB_DIR / path).resolve() if path else index
        if path and file.is_file() and file.is_relative_to(WEB_DIR.resolve()):
            return FileResponse(file)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


ROUTERS = (
    auth,
    paypal_login,
    pools,
    intake,
    entries,
    public,
    merchant,
    merchant_keys,
    agent,
    admin_pools,
    admin_sim,
    checkout,
    webhooks,
    admin_ops,
    merchant_fulfillment,
    notifications,
    agent_oauth,
    demand,
)


async def add_request_id(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a correlation ID to the contextvar and the response."""
    value = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
    token = request_id.set(value)
    try:
        response = await call_next(request)
    finally:
        request_id.reset(token)
    response.headers[REQUEST_ID_HEADER] = value
    # Vite changes the filename when bytes change; private API responses never match.
    if response.status_code == 200 and re.fullmatch(
        r"/assets/[^/]+-[A-Za-z0-9_-]{8}\.(?:js|css)", request.url.path
    ):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
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
            expose_headers=["X-CSRF-Token"],
        )

    app.add_middleware(SecurityHeadersMiddleware)
    app.middleware("http")(add_request_id)
    register_exception_handlers(app)
    # The merchant sub-app answers with the same error envelope as the parent and
    # reads the same settings; both are set before the mount (T07A06).
    merchant_api_app.state.settings = settings
    register_exception_handlers(merchant_api_app)
    app.include_router(health.router)
    for module in ROUTERS:
        app.include_router(module.router)
    if settings is None or settings.merchant_api_enabled:
        app.mount("/merchant-api/v1", merchant_api_app)
    if settings is not None and settings.mcp_enabled:
        # An ASGI app at exactly /mcp, not a documented route: the parent OpenAPI
        # must not grow an operation for it. ``Mount`` is not used because the
        # pinned Starlette matches a mount path only with a trailing slash, and
        # api.md section 2 fixes the path as ``/mcp``.
        app.router.routes.append(
            Route("/mcp", endpoint=build_mcp_app(app, settings, clock=DbClock()))
        )
    # A scrape endpoint, not a documented operation: the frozen route-table test
    # must not grow an entry for it (T08A05).
    app.router.routes.append(metrics_route())
    _serve_web(app)
    return app
