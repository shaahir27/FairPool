"""Auth dependency declarations for the frozen route table (T01B01).

PH1 registers the six auth modes so the route table and OpenAPI are stable.
Real session, role, delegation and API-key checks arrive in T02B01/T06B04;
until then every protected route fails closed with 401 UNAUTHENTICATED.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, Security, status
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer

session_cookie = APIKeyCookie(name="session", auto_error=False)
bearer = HTTPBearer(auto_error=False)


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="UNAUTHENTICATED",
    )


async def require_session(
    session: Annotated[str | None, Security(session_cookie)] = None,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    raise _unauthenticated()


async def require_merchant(_: Annotated[None, Security(require_session)] = None) -> None:
    raise _unauthenticated()


async def require_admin(_: Annotated[None, Security(require_session)] = None) -> None:
    raise _unauthenticated()


async def require_agent(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> None:
    raise _unauthenticated()


async def require_merchant_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> None:
    raise _unauthenticated()
