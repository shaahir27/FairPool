"""T03B01 / CR-3: the join limiter gets its own boundary test at 10/min/user.

config-and-errors.md section 3: functional join tests run with
``RATE_LIMIT_ENABLED=false`` and assert the constraint outcome; this file is
the one place that proves the limiter boundary itself, so the two mechanisms
are never conflated.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.integration.test_join_receipts import (
    SEED,
    error_code,
    login,
    manual_confirm,
    open_pool,
)
from tests.unit.test_settings import make_settings


def join_url(pool_id: uuid.UUID) -> str:
    return f"/api/v1/pools/{pool_id}/entries"


def limiter_settings(**overrides: Any):
    # The limiter test must not be the only thing the rate switch controls:
    # the signing key stays a valid 32-byte seed (SEED) so nothing leaks.
    assert SEED
    return make_settings(rate_limit_enabled=True, receipt_signing_key=SEED, **overrides)


@pytest.fixture
async def client(db_session: AsyncSession) -> httpx.AsyncClient:
    app = create_app(limiter_settings())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def test_join_route_limited_to_ten_per_minute_per_user(client, db_session):
    csrf = await login(client, "limited@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)

    # Attempts count even when the request is otherwise invalid: the limiter
    # guards the route, not the success path.
    for index in range(10):
        response = await client.post(
            join_url(pool_id),
            json={"confirmed_request_id": str(cr_id)},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 400, (index, response.text)
    eleventh = await client.post(
        join_url(pool_id),
        json={"confirmed_request_id": str(cr_id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert eleventh.status_code == 429
    assert error_code(eleventh) == "RATE_LIMITED"
    assert int(eleventh.headers["Retry-After"]) >= 1


async def test_the_limit_is_per_user_not_shared(client, db_session):
    csrf_a = await login(client, "limit-a@example.test")
    user_a = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_a = await manual_confirm(db_session, user_a, pool_id)
    for _ in range(10):
        await client.post(
            join_url(pool_id),
            json={"confirmed_request_id": str(cr_a)},
            headers={"X-CSRF-Token": csrf_a},
        )
    exhausted = await client.post(
        join_url(pool_id),
        json={"confirmed_request_id": str(cr_a)},
        headers={"X-CSRF-Token": csrf_a},
    )
    assert exhausted.status_code == 429

    # A second buyer on the same IP and pool is untouched by the first's limit.
    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        csrf_b = await login(other, "limit-b@example.test")
        user_b = uuid.UUID((await other.get("/api/v1/me")).json()["user_id"])
        cr_b = await manual_confirm(db_session, user_b, pool_id)
        response = await other.post(
            join_url(pool_id),
            json={"confirmed_request_id": str(cr_b)},
            headers={"Idempotency-Key": "ok", "X-CSRF-Token": csrf_b},
        )
        assert response.status_code == 201, response.text


async def test_only_the_join_route_carries_the_ten_per_minute_limit(client, db_session):
    csrf = await login(client, "route-scope@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    for _ in range(10):
        await client.post(
            join_url(pool_id),
            json={"confirmed_request_id": str(cr_id)},
            headers={"X-CSRF-Token": csrf},
        )
    assert (
        await client.post(
            join_url(pool_id),
            json={"confirmed_request_id": str(cr_id)},
            headers={"X-CSRF-Token": csrf},
        )
    ).status_code == 429
    # Reads and withdrawals are on other routes and keep working.
    assert (await client.get("/api/v1/me")).status_code == 200
    assert (
        await client.delete(f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": csrf})
    ).status_code == 404
