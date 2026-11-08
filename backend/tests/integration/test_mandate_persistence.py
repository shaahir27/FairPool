"""CR-14: a ratified mandate survives the delegation create path (FR-AI-06).

``DelegationService.create`` rebuilds ``scope`` as exactly ``{pool_ids, category}``. Before
CR-14 that rebuild dropped every other key without an error, so a mandate would have been
persisted as a bare scope and the token minted from a gutted object -- while the buyer had
ratified something the database never stored. The keys are inert for authorization: scope is
still resolved from ``pool_ids`` and ``category`` alone.

The buyer's ratification is a hash over the canonical mandate fields, not over the rendered
card, because the server cannot recompute a card it did not build. These tests compute that
same hash, so a token is minted only from fields the buyer actually ratified.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.errors import ApplicationError
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.delegations import DelegationService, PostgresDelegationAuth
from fairpool.modules.identity.mandate import canonical_mandate
from tests.integration.test_join_receipts import login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
HMAC_KEY = "test-hmac-key-for-mandate-persistence"

CONDITIONS: list[dict[str, Any]] = [
    {"predicate": "PRICE_ABOVE", "action": "REASK", "params": {"amount": "520.00"}},
    {"predicate": "BLOCKING_FLAG_ON_AWARD", "action": "REASK", "params": {}},
]


async def _buyer(session: AsyncSession) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Mandate Buyer', 'buyer')"
        ),
        {"id": user_id, "email": f"mandate-{user_id}@example.test"},
    )
    return user_id


def _service() -> DelegationService:
    return DelegationService(clock=DbClock(), audit=PostgresAuditLog(), hmac_key=HMAC_KEY)


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


def _ratified_scope(
    *,
    max_cap_cents: int,
    expires_at: datetime,
    category: str | None = "monitors",
) -> dict[str, Any]:
    """A scope whose hash covers exactly the fields the caller will post."""
    pool_ids = [str(uuid4())]
    scope: dict[str, Any] = {
        "pool_ids": pool_ids,
        "category": category,
        "mandate_version": "1",
        "conditions": CONDITIONS,
    }
    scope["ratification_sha256"] = hashlib.sha256(
        canonical_mandate(
            category=category,
            conditions=CONDITIONS,
            expires_at=expires_at,
            max_cap_cents=max_cap_cents,
            pool_ids=pool_ids,
        ).encode()
    ).hexdigest()
    return scope


async def test_a_ratified_mandate_survives_creation(db_session: AsyncSession) -> None:
    user_id = await _buyer(db_session)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    scope = _ratified_scope(max_cap_cents=60000, expires_at=expires_at)
    row, token = await _service().create(
        db_session,
        user_id=user_id,
        scope=scope,
        max_cap_cents=60000,
        expires_at=expires_at,
    )
    assert row.scope["mandate_version"] == "1"
    assert row.scope["ratification_sha256"] == scope["ratification_sha256"]
    assert row.scope["conditions"] == CONDITIONS

    # The same three keys must come back out of authentication, or the card can ratify a
    # mandate the token does not actually carry.
    principal = await PostgresDelegationAuth(clock=DbClock(), hmac_key=HMAC_KEY).from_token(
        db_session, token
    )
    assert principal.scope["mandate_version"] == "1"
    assert principal.scope["conditions"] == CONDITIONS
    assert principal.max_cap_cents == 60000


async def test_a_cap_above_the_ratified_mandate_is_refused(db_session: AsyncSession) -> None:
    """The hash covers the cap, so a token can never be wider than what the buyer ratified."""
    user_id = await _buyer(db_session)
    expires_at = datetime.now(UTC) + timedelta(days=7)
    scope = _ratified_scope(max_cap_cents=60000, expires_at=expires_at)

    with pytest.raises(ApplicationError) as refused:
        await _service().create(
            db_session,
            user_id=user_id,
            scope=scope,
            max_cap_cents=900000,
            expires_at=expires_at,
        )
    assert refused.value.code == "VALIDATION_ERROR"

    row, _ = await _service().create(
        db_session,
        user_id=user_id,
        scope=scope,
        max_cap_cents=60000,
        expires_at=expires_at,
    )
    assert row.max_cap_cents == 60000


async def test_a_mandate_version_without_a_hash_is_refused(db_session: AsyncSession) -> None:
    user_id = await _buyer(db_session)
    with pytest.raises(ApplicationError) as refused:
        await _service().create(
            db_session,
            user_id=user_id,
            scope={
                "pool_ids": [],
                "category": "monitors",
                "mandate_version": "1",
                "conditions": CONDITIONS,
            },
            max_cap_cents=100,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    assert refused.value.code == "VALIDATION_ERROR"


async def test_conditions_without_a_ratification_hash_are_dropped(
    db_session: AsyncSession,
) -> None:
    """They survive together or not at all: the hash is what makes them ratified."""
    user_id = await _buyer(db_session)
    row, _ = await _service().create(
        db_session,
        user_id=user_id,
        scope={"pool_ids": [], "category": None, "conditions": CONDITIONS},
        max_cap_cents=100,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert "conditions" not in row.scope
    assert "mandate_version" not in row.scope


async def test_an_unknown_scope_key_is_still_dropped(db_session: AsyncSession) -> None:
    user_id = await _buyer(db_session)
    expires_at = datetime.now(UTC) + timedelta(days=1)
    scope = _ratified_scope(max_cap_cents=100, expires_at=expires_at)
    scope["injected"] = "not a mandate field"
    row, _ = await _service().create(
        db_session,
        user_id=user_id,
        scope=scope,
        max_cap_cents=100,
        expires_at=expires_at,
    )
    assert "injected" not in row.scope
    assert row.scope["category"] == "monitors"


async def test_the_route_accepts_a_verified_mandate_and_refuses_a_raised_cap(
    client: httpx.AsyncClient,
) -> None:
    """The reported repro: a cap above the ratified mandate must not answer 201."""
    csrf = await login(client, "mandate-route@example.test")
    expires_at = datetime.now(UTC) + timedelta(days=7)
    scope = _ratified_scope(max_cap_cents=60000, expires_at=expires_at)

    created = await client.post(
        "/api/v1/me/delegations",
        headers={"X-CSRF-Token": csrf},
        json={"scope": scope, "max_cap_cents": 60000, "expires_at": expires_at.isoformat()},
    )
    assert created.status_code == 201, created.text
    assert created.json()["scope"]["ratification_sha256"] == scope["ratification_sha256"]

    refused = await client.post(
        "/api/v1/me/delegations",
        headers={"X-CSRF-Token": csrf},
        json={"scope": scope, "max_cap_cents": 900000, "expires_at": expires_at.isoformat()},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_the_route_refuses_a_mandate_version_without_a_hash(
    client: httpx.AsyncClient,
) -> None:
    csrf = await login(client, "mandate-no-hash@example.test")
    refused = await client.post(
        "/api/v1/me/delegations",
        headers={"X-CSRF-Token": csrf},
        json={
            "scope": {
                "pool_ids": [],
                "category": "monitors",
                "mandate_version": "1",
                "conditions": CONDITIONS,
            },
            "max_cap_cents": 100,
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
