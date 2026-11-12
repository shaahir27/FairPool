"""Auth dependency declarations for the frozen route table (T01B01).

Sessions, CSRF and roles use the database-backed identity service. Delegations
(``fpd_``) and merchant API keys (``fpm_``) resolve through their own HMAC
lookups; both are fail-closed.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Annotated, Final

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.db.models.auction import Merchant
from fairpool.db.session import create_engine
from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.infra.limits import SlidingWindowLimiter
from fairpool.modules.identity.delegations import AgentPrincipal, PostgresDelegationAuth
from fairpool.modules.identity.service import IdentityService, Principal
from fairpool.modules.merchants.api_keys import KEY_PREFIX, PREFIX_CHARS
from fairpool.modules.merchants.auth import PostgresMerchantAuth
from fairpool.ports import MerchantPrincipal

session_cookie = APIKeyCookie(name="__Host-session", auto_error=False)
bearer = HTTPBearer(auto_error=False)

#: config-and-errors.md section 3: the whole ``/merchant-api/v1`` surface is 120 requests
#: a minute per key, counted whether the route reads, writes or is refused by a scope.
MERCHANT_KEY_LIMIT: Final[int] = 120


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="UNAUTHENTICATED",
    )


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    settings = request.app.state.settings
    if settings is None:
        raise _unauthenticated()
    if not hasattr(request.app.state, "session_factory"):
        request.app.state.engine = create_engine(settings)
        request.app.state.session_factory = async_sessionmaker(
            request.app.state.engine, expire_on_commit=False
        )
    # Not ``session_factory.begin()``: a route may own more than one transaction.
    # ``domain-ports.md`` 4.4 and ``vault-charge.md`` 2 forbid provider I/O inside a
    # transaction that holds a pool, lot or entry lock, and a savepoint release does
    # not free a Postgres row lock, so such a route commits one phase and opens the
    # next (M2, the withdrawal route). A failed request still writes nothing: the
    # rollback below and the session close replace what ``begin()`` used to do.
    async with request.app.state.session_factory() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
        if db.in_transaction():
            await db.commit()


def identity_service(request: Request) -> IdentityService:
    if request.app.state.settings is None:
        raise _unauthenticated()
    if not hasattr(request.app.state, "identity_service"):
        request.app.state.identity_service = IdentityService(
            request.app.state.settings.secret_key.get_secret_value(), DbClock()
        )
    return request.app.state.identity_service


async def require_session(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    session: Annotated[str | None, Security(session_cookie)] = None,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Principal:
    return await identity_service(request).authenticate(
        db, session, csrf=x_csrf_token, unsafe=request.method not in {"GET", "HEAD", "OPTIONS"}
    )


async def require_merchant(
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> Principal:
    """A merchant role alone is not enough: the profile row must exist (T05A06)."""
    if principal.role != "merchant":
        raise HTTPException(403, "FORBIDDEN")
    merchant_id = await db.scalar(
        select(Merchant.id).where(Merchant.user_id == principal.user_id).limit(1)
    )
    if merchant_id is None:
        raise HTTPException(403, "FORBIDDEN")
    return principal


async def require_buyer(
    principal: Annotated[Principal, Security(require_session)],
) -> Principal:
    """A buyer-only route: the session is still required, the role decides access.

    Buyer routes used to accept any signed-in role, so a merchant or an admin
    session could read the buyer surface. The refusal is the contract's ``FORBIDDEN``
    at 403, never a 401: the caller is authenticated and simply has no entry lane.
    """
    if principal.role != "buyer":
        raise ApplicationError("FORBIDDEN")
    return principal


async def require_admin(principal: Annotated[Principal, Security(require_session)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "FORBIDDEN")
    return principal


async def require_agent(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> AgentPrincipal:
    """Resolve ``Authorization: Bearer fpd_<prefix>_<secret>`` (api.md section 4.4).

    Every refusal is ``DELEGATION_INVALID`` at 401: an absent header, a malformed
    token, an unknown hash, an expired row and a revoked row are not distinguished
    (I11). A token that resolves stamps ``last_used_at`` (CR-17), and that write is
    committed here so it survives the request, exactly as the merchant-key path does.
    """
    settings = request.app.state.settings
    if credentials is None or settings is None:
        raise ApplicationError("DELEGATION_INVALID")
    auth = PostgresDelegationAuth(clock=DbClock(), hmac_key=settings.hmac_key.get_secret_value())
    principal = await auth.from_token(db, credentials.credentials)
    await auth.mark_used(db, delegation_id=principal.delegation_id)
    await db.commit()
    return principal


def _merchant_key_bucket(bearer_value: str) -> str:
    """The key's public prefix is its bucket; a malformed key shares one bucket."""
    head, _, rest = bearer_value.partition("_")
    prefix = rest.partition("_")[0]
    return prefix if head == KEY_PREFIX and len(prefix) == PREFIX_CHARS else "invalid"


def _merchant_key_limiter(request: Request) -> SlidingWindowLimiter | None:
    """The sub-app's window, or ``None`` when ``RATE_LIMIT_ENABLED=false``.

    The limiter lives on the app that hosts the keyed routes (``api/merchant_api/app.py``),
    so a parent-app route can never spend a merchant key's budget by accident.
    """
    settings = request.app.state.settings
    if settings is None or not settings.rate_limit_enabled:
        return None
    limiter: SlidingWindowLimiter | None = getattr(request.app.state, "merchant_key_limiter", None)
    if limiter is None:
        limiter = SlidingWindowLimiter(limit=MERCHANT_KEY_LIMIT)
        request.app.state.merchant_key_limiter = limiter
    return limiter


async def require_merchant_key(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> MerchantPrincipal:
    """A merchant API key resolves to the same principal a session does, narrower scopes.

    Every refusal is ``API_KEY_INVALID`` at 401 (``api.md`` section 4.3): an absent
    header, a malformed key, an unknown prefix, a hash that does not match and a revoked
    key are not distinguished, because the difference is a probe answer. A key that
    resolves but lacks the scope is the route's own ``API_KEY_SCOPE`` at 403. A key that
    resolves is then counted against its own per-minute window, and nothing about the
    route it chose exempts it.
    """
    settings = request.app.state.settings
    if credentials is None or settings is None:
        raise ApplicationError("API_KEY_INVALID")
    auth = PostgresMerchantAuth(clock=DbClock(), hmac_key=settings.hmac_key.get_secret_value())
    principal = await auth.from_api_key(db, credentials.credentials)
    limiter = _merchant_key_limiter(request)
    if limiter is not None:
        limiter.check(_merchant_key_bucket(credentials.credentials), time.monotonic())
    # ``last_used_at`` is the only write and it must survive the request, so it is
    # committed here rather than left to the session's end-of-request flush.
    await db.commit()
    return principal
