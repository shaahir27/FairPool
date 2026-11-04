"""T07A05: delegation tokens are hashed, scoped, capped, expiring and revocable.

Contract: ``api.md`` sections 1 and 4.4, ``db-schema.md`` ``delegations``, rule 25
and ``product-spec.md`` FR-AG-02. The token is shown once, stored only as an HMAC,
never logged or audited, and every authentication failure is one answer
(``401 DELEGATION_INVALID``), so an attacker cannot tell "unknown" from "expired"
from "revoked".
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.errors import ApplicationError
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.delegations import (
    DelegationService,
    PostgresDelegationAuth,
    hash_token,
)
from tests.integration.test_join_receipts import login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
HMAC_KEY = SETTINGS.hmac_key.get_secret_value()
TOKEN_SHAPE = re.compile(r"^fpd_[0-9a-f]{8}_[A-Za-z0-9_-]{43}$")
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


def auth() -> PostgresDelegationAuth:
    return PostgresDelegationAuth(clock=DbClock(), hmac_key=HMAC_KEY)


async def create_delegation(
    client: httpx.AsyncClient,
    csrf: str,
    *,
    scope: dict[str, Any] | None = None,
    max_cap_cents: int = 60000,
    expires_at: str = FUTURE,
) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/me/delegations",
        headers={"X-CSRF-Token": csrf},
        json={
            "scope": scope or {"pool_ids": [], "category": None},
            "max_cap_cents": max_cap_cents,
            "expires_at": expires_at,
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def stored(delegation_id: UUID, db_session: AsyncSession) -> dict[str, Any]:
    row = await db_session.execute(
        text(
            "SELECT token_hash, scope, max_cap_cents, expires_at, revoked_at "
            "FROM delegations WHERE id = :id"
        ),
        {"id": str(delegation_id)},
    )
    return dict(row.mappings().one())


async def test_create_shows_the_token_once_and_stores_only_its_hmac(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "delegation-hash@example.test")
    body = await create_delegation(
        client, csrf, scope={"pool_ids": [], "category": "monitors"}, max_cap_cents=75000
    )
    assert set(body) == {"id", "scope", "max_cap_cents", "expires_at", "revoked_at", "token"}
    assert TOKEN_SHAPE.match(body["token"]), body["token"]
    assert body["scope"] == {"pool_ids": [], "category": "monitors"}
    assert body["max_cap_cents"] == 75000

    row = await stored(UUID(body["id"]), db_session)
    assert row["token_hash"] == hash_token(HMAC_KEY, body["token"])
    assert body["token"] not in row["token_hash"]
    assert row["revoked_at"] is None
    leaked = await db_session.scalar(
        text("SELECT count(*) FROM audit_log WHERE payload::text LIKE :like"),
        {"like": f"%{body['token']}%"},
    )
    assert leaked == 0


async def test_list_and_revoke_are_owner_scoped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "delegation-owner@example.test")
    created = await create_delegation(client, csrf)

    listed = await client.get("/api/v1/me/delegations")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [created["id"]]
    assert "token" not in items[0]

    revoked = await client.delete(
        f"/api/v1/me/delegations/{created['id']}", headers={"X-CSRF-Token": csrf}
    )
    assert revoked.status_code == 200, revoked.text
    row = await stored(UUID(created["id"]), db_session)
    assert row["revoked_at"] is not None

    with pytest.raises(ApplicationError) as invalid:
        await auth().from_token(db_session, created["token"])
    assert invalid.value.code == "DELEGATION_INVALID"


async def test_another_buyers_delegation_is_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    first = await login(client, "delegation-first@example.test")
    created = await create_delegation(client, first)
    second = await login(client, "delegation-second@example.test")

    missing = await client.delete(
        f"/api/v1/me/delegations/{created['id']}", headers={"X-CSRF-Token": second}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"

    listed = await client.get("/api/v1/me/delegations")
    assert listed.json()["items"] == []


async def test_expired_unknown_malformed_and_revoked_tokens_are_one_answer(
    db_session: AsyncSession,
) -> None:
    service = DelegationService(clock=DbClock(), audit=PostgresAuditLog(), hmac_key=HMAC_KEY)
    row, token = await service.create(
        db_session,
        user_id=UUID(
            str(
                await db_session.scalar(
                    text(
                        "INSERT INTO users (id, email, password_hash, display_name, role) "
                        "VALUES (gen_random_uuid(), 'expired@example.test', 'h', 'E', 'buyer') "
                        "RETURNING id"
                    )
                )
            )
        ),
        scope={"pool_ids": [], "category": None},
        max_cap_cents=1000,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert row.id
    for candidate in (token, "fpd_00000000_" + "A" * 43, "not-a-token", ""):
        with pytest.raises(ApplicationError) as invalid:
            await auth().from_token(db_session, candidate)
        assert invalid.value.code == "DELEGATION_INVALID"


async def test_agent_route_requires_a_live_delegation(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    anonymous = await client.get("/agent/v1/pools")
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "DELEGATION_INVALID"

    csrf = await login(client, "delegation-live@example.test")
    created = await create_delegation(client, csrf)
    allowed = await client.get(
        "/agent/v1/pools", headers={"Authorization": f"Bearer {created['token']}"}
    )
    assert allowed.status_code == 200, allowed.text

    await client.delete(f"/api/v1/me/delegations/{created['id']}", headers={"X-CSRF-Token": csrf})
    refused = await client.get(
        "/agent/v1/pools", headers={"Authorization": f"Bearer {created['token']}"}
    )
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "DELEGATION_INVALID"


async def test_a_naive_expiry_is_rejected(db_session: AsyncSession) -> None:
    service = DelegationService(clock=DbClock(), audit=PostgresAuditLog(), hmac_key=HMAC_KEY)
    with pytest.raises(ApplicationError) as invalid:
        await service.create(
            db_session,
            user_id=UUID(
                str(
                    await db_session.scalar(
                        text(
                            "INSERT INTO users (id, email, password_hash, display_name, role) "
                            "VALUES (gen_random_uuid(), 'naive@example.test', 'h', 'N', 'buyer') "
                            "RETURNING id"
                        )
                    )
                )
            ),
            scope={"pool_ids": [], "category": None},
            max_cap_cents=1000,
            expires_at=datetime(2099, 1, 1),
        )
    assert invalid.value.code == "VALIDATION_ERROR"
