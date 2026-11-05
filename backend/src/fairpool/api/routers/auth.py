"""Authentication and buyer address management (CR-6, CR-7)."""

from __future__ import annotations

import time
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, identity_service, require_session
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import sha256_hex
from fairpool.domain.paypal_identity import PayPalIdentityDeclined, PayPalIdentityUnavailable
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.limits import SlidingWindowLimiter
from fairpool.modules.identity.addresses import AddressBook
from fairpool.modules.identity.service import Principal
from fairpool.modules.identity.signup import SIGNUP_SETUP_TTL_S, PayPalSignupService
from fairpool.wiring import paypal_identity

router = APIRouter()
SIGNUP_COOKIE = "fairpool_signup"
#: The session cookie. The ``__Host-`` prefix makes the browser itself enforce
#: Secure, Path=/ and no Domain, so a subdomain cannot set or read it (I14).
SESSION_COOKIE = "__Host-session"

#: config-and-errors.md section 3: login and register are 10/min per address.
AUTH_RATE_LIMIT = 10
AUTH_RATE_WINDOW_S = 60.0


def _signup(request: Request) -> PayPalSignupService:
    settings = request.app.state.settings
    if settings is None:
        raise ApplicationError("FEATURE_DISABLED")
    provider = getattr(request.app.state, "paypal_signup_identity", None)
    if provider is None:
        provider = paypal_identity(settings)
    return PayPalSignupService(
        settings, provider, DbClock(), PostgresAuditLog(), identity_service(request)
    )


def _signup_origin(request: Request) -> None:
    """Refuse a browser form post from a page that is not ours.

    The page is either the configured frontend origin or the API's own origin (the
    hosted build serves both from one host). Local development serves the page on a
    loopback port that is not fixed, so loopback origins are accepted only when
    ``APP_ENV`` is local or test; production compares exact origins.
    """
    settings = request.app.state.settings
    if settings is None:
        raise ApplicationError("FORBIDDEN")
    origin = (request.headers.get("origin") or "").rstrip("/")
    if not origin:
        raise ApplicationError("FORBIDDEN")
    if origin in {settings.frontend_base_url.rstrip("/"), str(request.base_url).rstrip("/")}:
        return
    if settings.app_env in {"local", "test"}:
        host = urlsplit(origin).hostname
        if host in {"localhost", "127.0.0.1", "::1"}:
            return
    raise ApplicationError("FORBIDDEN")


def _session_cookie(request: Request, response: Response, value: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        value,
        httponly=True,
        # Unconditional: the hosted origin is https and a cookie that is only Secure
        # when the request happened to arrive over https is one downgrade away from
        # being sent in clear text. The __Host- prefix requires it anyway.
        secure=True,
        samesite="lax",
        max_age=86400,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/api/v1/auth/paypal/start",
    response_model=schemas.PayPalLoginStartResponse,
    operation_id="paypal_signup_start",
)
async def paypal_signup_start(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database_session),
):
    _signup_origin(request)
    rate_limit(request)
    # Duplicate control is by PayPal account, not by browser: a second person on a
    # shared device must be able to enroll their own PayPal account, and the account
    # check in complete() and register() is what refuses a repeat of the same one.
    authorize_url, browser = await _signup(request).start(db, request.cookies.get(SIGNUP_COOKIE))
    response.set_cookie(
        SIGNUP_COOKIE,
        browser,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=request.app.state.settings.oauth_state_ttl_s,
        path="/api/v1/auth",
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return {"authorize_url": authorize_url}


@router.get(
    "/api/v1/auth/paypal/status",
    response_model=schemas.SignupStatusResponse,
    operation_id="paypal_signup_status",
)
async def paypal_signup_status(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database_session),
):
    response.headers["Cache-Control"] = "no-store"
    return await _signup(request).status(db, request.cookies.get(SIGNUP_COOKIE))


@router.get("/api/v1/auth/paypal/callback", operation_id="paypal_signup_callback")
async def paypal_signup_callback(
    request: Request,
    db: AsyncSession = Depends(database_session),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if request.app.state.settings is None:
        raise ApplicationError("FEATURE_DISABLED")
    reason = "cancelled" if error else None
    if reason is None:
        try:
            await _signup(request).complete(
                db,
                browser=request.cookies.get(SIGNUP_COOKIE),
                state=state,
                code=code,
            )
        except PayPalIdentityDeclined:
            reason = "cancelled"
        except PayPalIdentityUnavailable:
            reason = "unavailable"
        except ApplicationError as failure:
            reason = "account_exists" if failure.code == "PAYPAL_LINK_CONFLICT" else "expired"
    base = request.app.state.settings.frontend_base_url.rstrip("/")
    target = "/register/connected" if reason is None else "/register?reason=" + reason
    response = RedirectResponse(base + target, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    if reason is None:
        browser = request.cookies.get(SIGNUP_COOKIE)
        if browser:
            response.set_cookie(
                SIGNUP_COOKIE,
                browser,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=SIGNUP_SETUP_TTL_S,
                path="/api/v1/auth",
            )
    else:
        response.delete_cookie(SIGNUP_COOKIE, path="/api/v1/auth")
    return response


class AuthRateLimiter(SlidingWindowLimiter):
    """The per-address auth window (``config-and-errors.md`` section 3)."""

    def __init__(self) -> None:
        super().__init__(limit=AUTH_RATE_LIMIT, window_s=AUTH_RATE_WINDOW_S)


def rate_limit(request: Request) -> None:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        if not hasattr(request.app.state, "auth_limiter"):
            request.app.state.auth_limiter = AuthRateLimiter()
        request.app.state.auth_limiter.check(
            request.client.host if request.client else "unknown", time.monotonic()
        )


def rate_limit_account(request: Request, email: str) -> None:
    """A second bucket per account, keyed by the SHA-256 of the address.

    The address bucket stops one client trying every account; this one stops every
    client trying one account, which is what a distributed guessing run looks like.
    The key is a hash so the map holds no addresses (I14), and it is normalised the
    way ``IdentityService.login`` normalises the lookup.
    """
    settings = request.app.state.settings
    if settings is None or not settings.rate_limit_enabled:
        return
    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "login_account_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(limit=AUTH_RATE_LIMIT, window_s=AUTH_RATE_WINDOW_S)
        request.app.state.login_account_limiter = limiter
    limiter.check(sha256_hex(email.strip().lower()), time.monotonic())


@router.post(
    "/api/v1/auth/register",
    response_model=schemas.RegisterResponse,
    operation_id="auth_register",
    dependencies=[Depends(rate_limit)],
)
async def auth_register(
    payload: schemas.RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database_session),
):
    _signup_origin(request)
    result, login = await _signup(request).register(
        db, browser=request.cookies.get(SIGNUP_COOKIE), **payload.model_dump()
    )
    _session_cookie(request, response, login.cookie)
    response.delete_cookie(SIGNUP_COOKIE, path="/api/v1/auth")
    return {"user_id": result["user_id"], "email": result["email"], "csrf_token": login.csrf_token}


@router.post(
    "/api/v1/auth/login",
    response_model=schemas.LoginResponse,
    operation_id="auth_login",
    dependencies=[Depends(rate_limit)],
)
async def auth_login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database_session),
):
    # The address bucket is the dependency above; this is the account bucket. Both are
    # needed: one address trying many accounts and many addresses trying one account
    # are different attacks (config-and-errors.md section 3).
    rate_limit_account(request, payload.email)
    # The register route's Origin gate means "this is our own page posting". A login
    # from a non-browser client has no Origin to check, so the rule applies only when
    # one arrives: refusing every header-less client would break the CLI and the tests
    # without adding a check.
    if request.headers.get("origin") is not None:
        _signup_origin(request)
    login = await identity_service(request).login(
        db, email=payload.email, password=payload.password
    )
    _session_cookie(request, response, login.cookie)
    return {"user_id": login.user_id, "csrf_token": login.csrf_token}


@router.post("/api/v1/auth/logout", operation_id="auth_logout")
async def auth_logout(
    response: Response,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    await identity_service(request).logout(db, principal)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=True)


@router.get("/api/v1/me", response_model=schemas.MeResponse, operation_id="me_get")
async def me_get(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    return await identity_service(request).me(db, principal)


def _address_book(request: Request, principal: Principal) -> AddressBook:
    if principal.role != "buyer":
        raise ApplicationError("FORBIDDEN")
    return AddressBook(
        request.app.state.settings.address_encryption_key.get_secret_value(), PostgresAuditLog()
    )


@router.get(
    "/api/v1/me/addresses",
    response_model=schemas.SavedAddressesResponse,
    operation_id="buyer_addresses_list",
)
async def buyer_addresses_list(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    addresses = await _address_book(request, principal).list(db, principal.user_id)
    return {"addresses": addresses}


@router.post(
    "/api/v1/me/addresses",
    response_model=schemas.SavedAddressResponse,
    operation_id="buyer_addresses_create",
)
async def buyer_addresses_create(
    payload: schemas.SavedAddressRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    return await _address_book(request, principal).save(
        db,
        principal.user_id,
        payload.address.model_dump(),
        is_default=payload.is_default,
    )


@router.put(
    "/api/v1/me/addresses/{address_id}",
    response_model=schemas.SavedAddressResponse,
    operation_id="buyer_addresses_update",
)
async def buyer_addresses_update(
    address_id: schemas.UUID,
    payload: schemas.SavedAddressRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    return await _address_book(request, principal).save(
        db,
        principal.user_id,
        payload.address.model_dump(),
        is_default=payload.is_default,
        address_id=address_id,
    )


@router.delete(
    "/api/v1/me/addresses/{address_id}",
    status_code=204,
    operation_id="buyer_addresses_delete",
)
async def buyer_addresses_delete(
    address_id: schemas.UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
) -> None:
    await _address_book(request, principal).delete(db, principal.user_id, address_id)
