"""The login Origin gate accepts our page and refuses a foreign one."""

from __future__ import annotations

import httpx
import pytest

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.identity_helpers import provision_buyer
from tests.integration.test_join_receipts import settings_for

pytestmark = pytest.mark.integration

PASSWORD = "a long test password"


def _app(db_session):
    app = create_app(settings_for())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    return app


async def test_login_accepts_the_configured_page_origin(db_session) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db_session)), base_url="https://api.test"
    ) as client:
        await provision_buyer(
            client, email="origin-ok@example.test", password=PASSWORD, display_name="Origin"
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "origin-ok@example.test", "password": PASSWORD},
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200, response.text


async def test_login_refuses_a_foreign_origin(db_session) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db_session)), base_url="https://api.test"
    ) as client:
        await provision_buyer(
            client, email="origin-bad@example.test", password=PASSWORD, display_name="Origin"
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "origin-bad@example.test", "password": PASSWORD},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_login_without_an_origin_still_works_for_clients(db_session) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(db_session)), base_url="https://api.test"
    ) as client:
        await provision_buyer(
            client, email="origin-none@example.test", password=PASSWORD, display_name="Origin"
        )
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "origin-none@example.test", "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
