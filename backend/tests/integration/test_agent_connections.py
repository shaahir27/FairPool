"""CR-17: a buyer's agents are named connections, not anonymous tokens.

Contract: ``api.md`` section 4.4 (connection identity), ``db-schema.md``
``delegations``. The merchant key surface already carries ``name``/``key_prefix``/
``last_used_at``; these tests pin the same behaviour for buyer delegations, plus the
rule that a refused token never stamps a use.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.integration.test_join_receipts import login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
FUTURE = "2099-01-01T00:00:00Z"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def create(client: httpx.AsyncClient, csrf: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "My assistant",
        "scope": {"pool_ids": [], "category": None},
        "max_cap_cents": 60000,
        "expires_at": FUTURE,
    }
    body.update(overrides)
    response = await client.post(
        "/api/v1/me/delegations", headers={"X-CSRF-Token": csrf}, json=body
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_a_connection_is_named_and_carries_the_public_prefix(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "connection-name@example.test")
    body = await create(client, csrf, name="Desk research agent")

    assert body["name"] == "Desk research agent"
    assert body["key_prefix"] == body["token"].split("_")[1]
    assert body["last_used_at"] is None

    listed = await client.get("/api/v1/me/delegations")
    assert listed.status_code == 200, listed.text
    item = next(x for x in listed.json()["items"] if x["id"] == body["id"])
    assert item["name"] == "Desk research agent"
    assert item["key_prefix"] == body["key_prefix"]
    assert item["last_used_at"] is None
    assert "token" not in item

    stored = await db_session.execute(
        text("SELECT name, key_prefix, token_hash FROM delegations WHERE id = :id"),
        {"id": body["id"]},
    )
    row = stored.mappings().one()
    assert row["name"] == "Desk research agent"
    assert body["token"] not in row["token_hash"]


async def test_an_empty_or_overlong_name_is_refused(client: httpx.AsyncClient) -> None:
    csrf = await login(client, "connection-bad-name@example.test")
    for name in ("", "   ", "x" * 121):
        response = await client.post(
            "/api/v1/me/delegations",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": name,
                "scope": {"pool_ids": [], "category": None},
                "max_cap_cents": 60000,
                "expires_at": FUTURE,
            },
        )
        assert response.status_code == 422, (name, response.text)


async def test_a_successful_agent_call_stamps_last_used(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "connection-use@example.test")
    body = await create(client, csrf)

    response = await client.get(
        "/agent/v1/pools?limit=1", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert response.status_code == 200, response.text

    stamped = await db_session.scalar(
        text("SELECT last_used_at FROM delegations WHERE id = :id"), {"id": body["id"]}
    )
    assert stamped is not None
    listed = await client.get("/api/v1/me/delegations")
    item = next(x for x in listed.json()["items"] if x["id"] == body["id"])
    assert item["last_used_at"] is not None


async def test_a_refused_token_never_stamps_a_use(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "connection-revoked@example.test")
    body = await create(client, csrf)
    revoked = await client.delete(
        f"/api/v1/me/delegations/{body['id']}", headers={"X-CSRF-Token": csrf}
    )
    assert revoked.status_code in (200, 204), revoked.text

    response = await client.get(
        "/agent/v1/pools?limit=1", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert response.status_code == 401
    stamped = await db_session.scalar(
        text("SELECT last_used_at FROM delegations WHERE id = :id"), {"id": body["id"]}
    )
    assert stamped is None


async def test_a_delegation_minted_before_the_migration_still_lists(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """An existing row has no name or prefix; it must stay usable and listable."""
    csrf = await login(client, "connection-legacy@example.test")
    body = await create(client, csrf)
    await db_session.execute(
        text("UPDATE delegations SET name = NULL, key_prefix = NULL WHERE id = :id"),
        {"id": body["id"]},
    )
    await db_session.flush()

    listed = await client.get("/api/v1/me/delegations")
    assert listed.status_code == 200, listed.text
    item = next(x for x in listed.json()["items"] if x["id"] == body["id"])
    assert item["name"] is None
    assert item["key_prefix"] is None

    response = await client.get(
        "/agent/v1/pools?limit=1", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert response.status_code == 200, response.text


async def test_two_connections_may_share_a_name_but_not_a_prefix(
    client: httpx.AsyncClient,
) -> None:
    csrf = await login(client, "connection-prefix@example.test")
    first = await create(client, csrf, name="Same name")
    second = await create(client, csrf, name="Same name")
    assert first["key_prefix"] != second["key_prefix"]
    assert UUID(first["id"]) != UUID(second["id"])
