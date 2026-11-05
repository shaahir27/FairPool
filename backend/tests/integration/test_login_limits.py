"""CR-10: login is limited per address *and* per account, and counted once.

Section 3 lists 10 attempts per minute per address for login and register. One
address trying many accounts and many addresses trying one account are different
attacks, so login also fills a bucket keyed by the SHA-256 of the address it is
trying — never the address itself, because the limiter's map is process memory (I14).

The route used to call the limiter twice (once as a dependency, once in the body),
which halved the contracted allowance. The count test below fails if that returns.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.routers.auth import AUTH_RATE_LIMIT, rate_limit_account
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.integration

PASSWORD = "a-secure-password"
HEX = re.compile(r"[0-9a-f]{64}")


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(make_settings(rate_limit_enabled=True))

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def sign_up(db_session: AsyncSession, email: str) -> None:
    await IdentityService("test-signing-key", DbClock()).register(
        db_session, email=email, password=PASSWORD, display_name="Buyer"
    )


def request_for(app: object) -> Request:
    return Request({"type": "http", "app": app, "headers": [], "method": "POST", "path": "/"})


def test_the_account_bucket_refuses_the_eleventh_attempt_for_one_address() -> None:
    app = create_app(make_settings())
    request = request_for(app)
    for _ in range(AUTH_RATE_LIMIT):
        rate_limit_account(request, "Target@Example.test")
    with pytest.raises(HTTPException) as refused:
        # The lookup normalises case, so the bucket must too.
        rate_limit_account(request, "target@example.test")
    assert refused.value.status_code == 429
    assert int(refused.value.headers["Retry-After"]) >= 1


def test_the_account_bucket_holds_hashes_not_addresses() -> None:
    app = create_app(make_settings())
    request = request_for(app)
    rate_limit_account(request, "hash-me@example.test")
    keys = list(app.state.login_account_limiter._hits)
    assert len(keys) == 1 and HEX.fullmatch(keys[0])
    assert "hash-me" not in keys[0]


def test_one_account_being_guessed_does_not_block_another() -> None:
    app = create_app(make_settings())
    request = request_for(app)
    for _ in range(AUTH_RATE_LIMIT):
        rate_limit_account(request, "first@example.test")
    rate_limit_account(request, "second@example.test")


def test_the_disabled_switch_lets_every_attempt_through() -> None:
    app = create_app(make_settings(rate_limit_enabled=False))
    request = request_for(app)
    for _ in range(AUTH_RATE_LIMIT * 2):
        rate_limit_account(request, "off@example.test")
    assert not hasattr(app.state, "login_account_limiter")


async def test_login_counts_each_attempt_once(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Ten attempts are allowed; the double call used to refuse the sixth."""
    await sign_up(db_session, "counted@example.test")
    for index in range(AUTH_RATE_LIMIT):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "counted@example.test", "password": "wrong-one"}
        )
        assert response.status_code == 401, (index, response.text)
    eleventh = await client.post(
        "/api/v1/auth/login", json={"email": "counted@example.test", "password": "wrong-one"}
    )
    assert eleventh.status_code == 429
    assert eleventh.json()["error"]["code"] == "RATE_LIMITED"


async def test_a_login_with_a_foreign_origin_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await sign_up(db_session, "origin@example.test")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "origin@example.test", "password": PASSWORD},
        headers={"Origin": "https://evil.test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_a_login_without_an_origin_header_is_still_allowed(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A CLI or a server-to-server client sends no Origin; the register gate stays strict."""
    await sign_up(db_session, "no-origin@example.test")
    response = await client.post(
        "/api/v1/auth/login", json={"email": "no-origin@example.test", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    strict = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "x@example.test",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "display_name": "X",
        },
    )
    assert strict.status_code == 403
    assert strict.json()["error"]["code"] == "FORBIDDEN"
