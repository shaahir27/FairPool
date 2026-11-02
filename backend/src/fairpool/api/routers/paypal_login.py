"""Log in with PayPal routes (T03B03); paths, operation IDs and shapes are api.md.

The three handlers only translate HTTP to ``modules.identity.paypal_login``: the
session dependency, the single-use state ladder, the keyed storage rule and the
relink block all live in that module. The identity port implementation is injected
through ``app.state.paypal_identity`` so a test or a simulation run can script it;
with nothing injected the composition root supplies the real Sandbox identity
adapter. This router never imports the adapter (``tools/check_imports.py`` rule 3).

The callback's ``error`` parameter is read from the raw query string instead of
being declared as a route parameter: api.md section 2 fixes this route's
documented parameters, and the OpenAPI snapshot the frontend generates types from
must not change when the stub is wired.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.api.errors import error_response
from fairpool.config import Settings
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.paypal_login import PayPalLoginService, ProviderDeclined
from fairpool.modules.identity.service import Principal
from fairpool.ports import PayPalIdentity
from fairpool.wiring import paypal_identity

router = APIRouter()

#: config-and-errors.md section 3: these three routes fall under "everything
#: else", 120 per minute per IP.
LOGIN_RATE_LIMIT = 120
LOGIN_RATE_WINDOW_S = 60.0


class LoginRateLimiter:
    """Same shape as ``AuthRateLimiter`` (auth.py), keyed by IP (CR-3)."""

    def __init__(self) -> None:
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, ip: str, now: float) -> None:
        # shortcut: per-process limits; require shared enforcement before multi-process deployment.
        hits = self.clients.setdefault(ip, deque())
        self.clients.move_to_end(ip)
        while hits and now - hits[0] >= LOGIN_RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= LOGIN_RATE_LIMIT:
            raise HTTPException(
                429,
                "RATE_LIMITED",
                headers={
                    "Retry-After": str(max(1, int(LOGIN_RATE_WINDOW_S - (now - hits[0])) + 1))
                },
            )
        hits.append(now)
        if len(self.clients) > 4096:
            self.clients.popitem(last=False)


def rate_limit_login(request: Request) -> None:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        if not hasattr(request.app.state, "login_limiter"):
            request.app.state.login_limiter = LoginRateLimiter()
        request.app.state.login_limiter.check(
            request.client.host if request.client else "unknown", time.monotonic()
        )


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    return settings


def _identity(request: Request) -> PayPalIdentity:
    """Tests inject their fake; enabled application traffic uses the Sandbox adapter."""
    injected = getattr(request.app.state, "paypal_identity", None)
    if injected is not None:
        return injected  # type: ignore[no-any-return]
    created = paypal_identity(_settings(request))
    request.app.state.paypal_identity = created
    return created


def _service(request: Request) -> PayPalLoginService:
    settings = _settings(request)
    return PayPalLoginService(
        _identity(request),
        DbClock(),
        PostgresAuditLog(),
        # Read once, used only to key the stored digest; never logged (rule 2).
        hmac_key=settings.hmac_key.get_secret_value(),
        dedupe_mode=settings.dedupe_mode,
        enabled=settings.paypal_login_enabled,
        client_id=settings.paypal_client_id,
        redirect_uri=settings.paypal_login_redirect_uri,
        checkout_base=settings.paypal_checkout_base,
        state_ttl_s=settings.oauth_state_ttl_s,
    )


def _declined() -> JSONResponse:
    """A provider decline: 400 with nothing written (api.md "Account link").

    `PROVIDER_DECLINED` was added to the closed code list for exactly this case,
    so the 400 that api.md fixes does not have to borrow a 422 code.
    """
    return error_response(
        status_code=400, code="PROVIDER_DECLINED", message="The login request was declined."
    )


@router.get(
    "/api/v1/paypal/login/start",
    response_model=schemas.PayPalLoginStartResponse,
    operation_id="paypal_login_start",
)
async def paypal_login_start(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    _limiter: None = Depends(rate_limit_login),
):
    result = await _service(request).start(db, principal)
    # Only the authorize URL leaves here; it carries the state (api.md).
    return {"authorize_url": result.authorize_url}


@router.get(
    "/api/v1/paypal/login/callback",
    response_model=schemas.PayPalLoginCallbackResponse,
    operation_id="paypal_login_callback",
)
async def paypal_login_callback(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    code: str | None = Query(None),
    state: str | None = Query(None),
    _limiter: None = Depends(rate_limit_login),
):
    # Undeclared so the documented parameter set stays exactly as api.md fixes it.
    provider_error = request.query_params.get("error")
    try:
        result = await _service(request).complete(
            db, principal, code=code, state=state, provider_error=provider_error
        )
    except ProviderDeclined:
        return _declined()
    return {"paypal_linked": result.linked}


@router.delete("/api/v1/paypal/link", operation_id="paypal_link_delete")
async def paypal_link_delete(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    _limiter: None = Depends(rate_limit_login),
):
    await _service(request).unlink(db, principal)
    # The link state only: no identifier, no key, no vault statement (rule 27).
    return JSONResponse(status_code=200, content={"paypal_linked": False})
