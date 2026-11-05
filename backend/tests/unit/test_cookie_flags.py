"""CR-10: the session cookie is ``Secure``, host-only and ``__Host-`` prefixed.

A cookie whose ``Secure`` flag follows the request scheme is one downgrade away from
travelling in clear text, a cookie without a ``Domain`` attribute can be shadowed by
a sibling subdomain, and a name without the ``__Host-`` prefix lets that subdomain
set it. The browser enforces all three for ``__Host-``, so the name is part of the
fix and every route that writes or clears it is asserted here.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.routers.auth import SESSION_COOKIE
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.integration

PASSWORD = "a-secure-password"


async def sign_up(db_session: AsyncSession, email: str) -> None:
    await IdentityService("test-signing-key", DbClock()).register(
        db_session, email=email, password=PASSWORD, display_name="Buyer"
    )


def client_for(db_session: AsyncSession, *, scheme: str = "https") -> httpx.AsyncClient:
    app = create_app(make_settings())

    async def session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[database_session] = session
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"{scheme}://api.test"
    )


async def test_login_sets_a_secure_host_prefixed_session_cookie(
    db_session: AsyncSession,
) -> None:
    await sign_up(db_session, "cookie@example.test")
    async with client_for(db_session) as client:
        response = await client.post(
            "/api/v1/auth/login", json={"email": "cookie@example.test", "password": PASSWORD}
        )
    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE == "__Host-session"
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    # __Host- forbids a Domain attribute, and so does the browser.
    assert "Domain=" not in cookie


async def test_the_secure_flag_does_not_depend_on_the_request_scheme(
    db_session: AsyncSession,
) -> None:
    """The flag used to follow ``request.url.scheme``; a plain-http login proved it."""
    await sign_up(db_session, "cookie-http@example.test")
    async with client_for(db_session, scheme="http") as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "cookie-http@example.test", "password": PASSWORD},
        )
    assert response.status_code == 200, response.text
    assert "Secure" in response.headers["set-cookie"]


async def test_logout_clears_the_same_cookie(db_session: AsyncSession) -> None:
    await sign_up(db_session, "cookie-out@example.test")
    async with client_for(db_session) as client:
        login = await client.post(
            "/api/v1/auth/login", json={"email": "cookie-out@example.test", "password": PASSWORD}
        )
        csrf = login.json()["csrf_token"]
        response = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200, response.text
        assert (await client.get("/api/v1/me")).status_code == 401
    cleared = response.headers["set-cookie"]
    # A delete that names the old cookie leaves the real one in place.
    assert cleared.startswith(f"{SESSION_COOKIE}=")
    assert "Path=/" in cleared
