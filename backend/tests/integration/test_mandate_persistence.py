"""CR-14: a ratified mandate survives the delegation create path (FR-AI-06).

``DelegationService.create`` rebuilds ``scope`` as exactly ``{pool_ids, category}``. Before
CR-14 that rebuild dropped every other key without an error, so a mandate would have been
persisted as a bare scope and the token minted from a gutted object -- while the buyer had
ratified something the database never stored. The keys are inert for authorization: scope is
still resolved from ``pool_ids`` and ``category`` alone.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.delegations import DelegationService, PostgresDelegationAuth

pytestmark = pytest.mark.integration

HMAC_KEY = "test-hmac-key-for-mandate-persistence"

CONDITIONS: list[dict[str, object]] = [
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


async def test_a_ratified_mandate_survives_creation(db_session: AsyncSession) -> None:
    user_id = await _buyer(db_session)
    sha = hashlib.sha256(b"the rendered mandate text").hexdigest()
    row, token = await _service().create(
        db_session,
        user_id=user_id,
        scope={
            "pool_ids": [str(uuid4())],
            "category": "monitors",
            "mandate_version": "m1",
            "ratification_sha256": sha,
            "conditions": CONDITIONS,
        },
        max_cap_cents=60000,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    assert row.scope["mandate_version"] == "m1"
    assert row.scope["ratification_sha256"] == sha
    assert row.scope["conditions"] == CONDITIONS

    # The same three keys must come back out of authentication, or the card can ratify a
    # mandate the token does not actually carry.
    principal = await PostgresDelegationAuth(clock=DbClock(), hmac_key=HMAC_KEY).from_token(
        db_session, token
    )
    assert principal.scope["mandate_version"] == "m1"
    assert principal.scope["conditions"] == CONDITIONS
    assert principal.max_cap_cents == 60000


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
    row, _ = await _service().create(
        db_session,
        user_id=user_id,
        scope={
            "pool_ids": [],
            "category": "monitors",
            "ratification_sha256": hashlib.sha256(b"x").hexdigest(),
            "injected": "not a mandate field",
        },
        max_cap_cents=100,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert "injected" not in row.scope
    assert row.scope["category"] == "monitors"


async def test_a_mandate_never_widens_the_cap_or_the_scope(db_session: AsyncSession) -> None:
    """The mandate narrows authority; it can never raise what the token already allows."""
    user_id = await _buyer(db_session)
    row, _ = await _service().create(
        db_session,
        user_id=user_id,
        scope={
            "pool_ids": [],
            "category": "monitors",
            "mandate_version": "m1",
            "ratification_sha256": hashlib.sha256(b"y").hexdigest(),
            "conditions": CONDITIONS,
        },
        max_cap_cents=60000,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    assert row.max_cap_cents == 60000
    assert row.scope["pool_ids"] == []
    assert row.scope["category"] == "monitors"
