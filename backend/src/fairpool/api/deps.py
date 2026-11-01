"""Auth dependency declarations for the frozen route table (T01B01).

Sessions, CSRF and roles use the database-backed identity service. Delegation
and merchant-key authentication remain fail-closed until their scheduled phase.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.db.session import create_engine
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService, Principal

session_cookie = APIKeyCookie(name="session", auto_error=False)
bearer = HTTPBearer(auto_error=False)


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


async def require_merchant(principal: Annotated[Principal, Security(require_session)]) -> Principal:
    if principal.role != "merchant":
        raise HTTPException(403, "FORBIDDEN")
    return principal


async def require_admin(principal: Annotated[Principal, Security(require_session)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "FORBIDDEN")
    return principal


async def require_agent(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> None:
    raise _unauthenticated()


async def require_merchant_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> None:
    raise _unauthenticated()
