"""OAuth 2.1 endpoints for the buyer MCP surface (CR-17, api.md section 4.7).

The well-known documents live at the origin root because that is where RFC 9728
clients look. The consent decision is an ordinary session-and-CSRF route: the buyer
is signed in to FairPool in their own browser, and the mandate they ratify there is
the one the token endpoint may mint. No route here creates a PayPal order or moves
money (I1, I2, rule 22).
"""

from __future__ import annotations

import time
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.config import Settings
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.limits import SlidingWindowLimiter
from fairpool.modules.identity.agent_oauth import AgentOAuthService, OAuthError
from fairpool.modules.identity.delegations import DelegationService
from fairpool.modules.identity.service import Principal

router = APIRouter()

#: Registration is unauthenticated, so it gets one shared window rather than none.
REGISTER_LIMIT = 20
SCOPES = "pools entries"


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        raise OAuthError("server_error", "Settings unavailable")
    return settings


def _service(request: Request) -> AgentOAuthService:
    settings = _settings(request)
    hmac_key = settings.hmac_key.get_secret_value()
    return AgentOAuthService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        hmac_key=hmac_key,
        delegations=DelegationService(clock=DbClock(), audit=PostgresAuditLog(), hmac_key=hmac_key),
    )


def _base(request: Request) -> str:
    return _settings(request).public_base_url.rstrip("/")


def _error(exc: OAuthError, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": exc.error, "error_description": exc.description},
    )


async def _form(request: Request) -> dict[str, str]:
    """OAuth's form-encoded body, parsed with the standard library (no new dependency)."""
    raw = await request.body()
    if len(raw) > 8192:
        raise OAuthError("invalid_request", "Form too large")
    try:
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError:
        raise OAuthError("invalid_request", "Form is not UTF-8") from None
    return {key: values[0] for key, values in parsed.items()}


def _with_query(uri: str, params: dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
async def protected_resource(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse(
        {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
            "scopes_supported": SCOPES.split(),
        }
    )


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def authorization_server(request: Request) -> JSONResponse:
    base = _base(request)
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": SCOPES.split(),
        }
    )


@router.post(
    "/oauth/register",
    response_model=schemas.OAuthClientRegistered,
    status_code=201,
    include_in_schema=False,
)
async def register(
    payload: schemas.OAuthClientRegisterRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    settings = _settings(request)
    if settings.rate_limit_enabled:
        limiter: SlidingWindowLimiter | None = getattr(
            request.app.state, "oauth_register_limiter", None
        )
        if limiter is None:
            limiter = SlidingWindowLimiter(limit=REGISTER_LIMIT)
            request.app.state.oauth_register_limiter = limiter
        limiter.check("register", time.monotonic())
    try:
        row = await _service(request).register(
            db, name=payload.client_name, redirect_uris=payload.redirect_uris
        )
    except OAuthError as exc:
        return _error(exc)
    await db.commit()
    return JSONResponse(
        status_code=201,
        content={
            "client_id": row.client_id,
            "client_name": row.name,
            "redirect_uris": row.redirect_uris,
            "token_endpoint_auth_method": "none",
        },
    )


@router.get("/oauth/authorize", include_in_schema=False, response_model=None)
async def authorize(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    scope: str = "",
) -> JSONResponse | RedirectResponse:
    """Validate first, then send the browser to FairPool's own consent page.

    An invalid request is answered here as JSON: redirecting an unvalidated
    ``redirect_uri`` would be an open redirect.
    """
    if response_type != "code":
        return _error(OAuthError("unsupported_response_type", "Only code is supported"))
    try:
        client = await _service(request).check_request(
            db,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
    except OAuthError as exc:
        return _error(exc)
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"client_name": client.name, "redirect_uri": redirect_uri})
    settings = _settings(request)
    consent = _with_query(
        f"{settings.frontend_base_url.rstrip('/')}/agents/authorize",
        {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "scope": scope or SCOPES,
        },
    )
    return RedirectResponse(consent, status_code=302)


@router.post(
    "/oauth/authorize/decision",
    response_model=schemas.OAuthDecisionResponse,
    include_in_schema=False,
)
async def decision(
    payload: schemas.OAuthDecisionRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    try:
        if not payload.approved:
            await _service(request).check_request(
                db,
                client_id=payload.client_id,
                redirect_uri=payload.redirect_uri,
                code_challenge=payload.code_challenge,
                code_challenge_method=payload.code_challenge_method,
                state=payload.state,
            )
            return JSONResponse(
                {
                    "redirect_to": _with_query(
                        payload.redirect_uri, {"error": "access_denied", "state": payload.state}
                    )
                }
            )
        if payload.scope is None or payload.max_cap_cents is None or payload.expires_at is None:
            raise OAuthError("invalid_request", "A ratified mandate is required")
        code = await _service(request).issue_code(
            db,
            user_id=principal.user_id,
            client_id=payload.client_id,
            redirect_uri=payload.redirect_uri,
            code_challenge=payload.code_challenge,
            code_challenge_method=payload.code_challenge_method,
            state=payload.state,
            scope=payload.scope.model_dump(mode="json"),
            max_cap_cents=payload.max_cap_cents,
            expires_at=payload.expires_at,
        )
    except OAuthError as exc:
        return _error(exc)
    await db.commit()
    return JSONResponse(
        {"redirect_to": _with_query(payload.redirect_uri, {"code": code, "state": payload.state})}
    )


@router.post("/oauth/token", include_in_schema=False)
async def token(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    try:
        form = await _form(request)
        if form.get("grant_type") != "authorization_code":
            raise OAuthError("unsupported_grant_type", "Only authorization_code is supported")
        service = _service(request)
        delegation, access_token = await service.exchange(
            db,
            code=form.get("code", ""),
            client_id=form.get("client_id", ""),
            redirect_uri=form.get("redirect_uri", ""),
            code_verifier=form.get("code_verifier", ""),
        )
        now = await DbClock().db_now(db)
        expires_in = service.expires_in(delegation, now)
    except OAuthError as exc:
        return _error(exc)
    await db.commit()
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": SCOPES,
        }
    )


@router.post("/oauth/revoke", include_in_schema=False)
async def revoke(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    try:
        form = await _form(request)
        await _service(request).revoke_token(db, token=form.get("token", ""))
    except OAuthError as exc:
        return _error(exc)
    await db.commit()
    return JSONResponse({})
