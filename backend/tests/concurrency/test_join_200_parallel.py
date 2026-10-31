"""T03B01: PT-13 / F14 / F15 — 200 parallel joins, one entry per user and key.

Runs with ``RATE_LIMIT_ENABLED=false`` (config-and-errors.md §3, CR-3): the
unique constraints on ``(pool_id, user_id)`` and
``(pool_id, paypal_account_key)`` are what this test proves, not the limiter.
200 concurrent join transactions race over one pool: 100 buyers, each
submitting twice through an independent transaction (the F14 "same buyer,
many tabs and lanes" shape). Exactly one entry per buyer may exist. F15 is
asserted over the two identity paths that exist today — the buyer session
path and a second submission through the same entry service for the same
account — because the ``/agent/v1`` HTTP lane arrives in Phase 7 (IG-7
re-asserts it there).

Data is committed on a dedicated engine: the joins must be real, concurrent,
separate transactions. The disposable ``*_test`` database is wiped afterwards.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from fairpool.db.safety import require_test_database
from fairpool.db.session import normalize_database_url
from fairpool.domain.hashing import verify_ed25519
from fairpool.modules.pools.receipts import public_key_b64url, signing_seed
from tests.integration.test_join_receipts import (
    SEED,
    join_service,
    manual_confirm,
    open_pool,
)

pytestmark = pytest.mark.concurrency

BUYERS = 100
JOINS = 200  # every buyer submits twice, concurrently


@pytest.fixture
async def engine() -> AsyncEngine:
    url = os.environ["DATABASE_URL"]
    require_test_database(url)
    parsed, connect_args = normalize_database_url(url)
    # A bounded pool: 200 concurrent joins queue for connections instead of
    # opening 200 sockets against the disposable database.
    created = create_async_engine(
        parsed, connect_args=connect_args, pool_size=10, max_overflow=15, pool_timeout=120
    )
    try:
        yield created
    finally:
        await created.dispose()


async def test_200_parallel_joins_leave_exactly_one_entry_per_buyer(engine: AsyncEngine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    pool_tag = uuid.uuid4()
    users = [uuid.uuid4() for _ in range(BUYERS)]

    async with maker() as session, session.begin():
        pool_id = await open_pool(session)

    async with maker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, 'hash', 'Joiner')"
            ),
            [
                {"id": user, "email": f"joiner-{i}-{pool_tag}@example.test"}
                for i, user in enumerate(users)
            ],
        )
        await session.execute(
            text(
                "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
                "VALUES (:id, :user, :account)"
            ),
            [
                {"id": uuid.uuid4(), "user": user, "account": f"ACCT-{pool_tag}-{i}"}
                for i, user in enumerate(users)
            ],
        )
        await session.execute(
            text("UPDATE pools SET require_paypal_link = true WHERE id = :p"), {"p": pool_id}
        )

    # Two confirmed requests per buyer: each racing submission carries its
    # own request and its own idempotency key, so nothing but the database
    # constraints can collapse them.
    requests: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with maker() as session, session.begin():
        for index, user in enumerate(users):
            for half in (0, 1):
                cap = 50_000 + 100 * index + half
                cr_id = await manual_confirm(session, user, pool_id, max_total_cents=cap)
                requests.append((user, cr_id))
    assert len(requests) == JOINS

    service = join_service()

    async def attempt(user: uuid.UUID, cr_id: uuid.UUID) -> tuple[int, dict]:
        async with maker() as session, session.begin():
            outcome = await service.join(
                session,
                pool_id=pool_id,
                user_id=user,
                confirmed_request_id=cr_id,
                idempotency_key=str(uuid.uuid4()),
            )
        return outcome.status_code, outcome.body

    results = await asyncio.gather(*(attempt(user, cr) for user, cr in requests))

    # PT-13 / F14: exactly one creating join per buyer; the rival submission
    # swallows its constraint violation and answers with the winner's receipt.
    assert len(results) == JOINS
    assert sum(1 for code, _ in results if code == 201) == BUYERS
    assert sum(1 for code, _ in results if code == 200) == BUYERS
    entries_per_winner: dict[str, int] = {}
    for _code, body in results:
        entries_per_winner[body["entry_id"]] = entries_per_winner.get(body["entry_id"], 0) + 1
    assert len(entries_per_winner) == BUYERS
    # Each entry is named by exactly two bodies: the creating join and the
    # already_entered answer to the rival submission.
    assert set(entries_per_winner.values()) == {2}

    public_key = public_key_b64url(signing_seed(SEED))
    for code, body in results:
        assert verify_ed25519(body["receipt"]["payload"], body["receipt"]["signature"], public_key)
        commitment = body["receipt"]["payload"]["commitment"]
        assert len(commitment) == 64
        if code == 200:
            assert body["already_entered"] is True

    async with maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM pool_entries WHERE pool_id = :p), "
                    "(SELECT count(*) FROM entry_receipts r JOIN pool_entries e ON e.id=r.entry_id "
                    " WHERE e.pool_id = :p), "
                    "(SELECT count(DISTINCT user_id) FROM pool_entries WHERE pool_id = :p), "
                    "(SELECT count(DISTINCT paypal_account_key) "
                    "FROM pool_entries WHERE pool_id = :p)"
                ),
                {"p": pool_id},
            )
        ).one()
    assert row == (BUYERS, BUYERS, BUYERS, BUYERS)

    # F15: the same buyer submitting a third time through the same entry
    # service (the shape the agent lane will use) gets the one entry.
    by_user: dict[uuid.UUID, str] = {}
    for (user, _cr), (_code, body) in zip(requests, results, strict=True):
        by_user.setdefault(user, body["entry_id"])
    probe_user = users[0]
    async with maker() as session, session.begin():
        third_cr = await manual_confirm(session, probe_user, pool_id, max_total_cents=59000)
    async with maker() as session, session.begin():
        replay = await service.join(
            session,
            pool_id=pool_id,
            user_id=probe_user,
            confirmed_request_id=third_cr,
            idempotency_key=str(uuid.uuid4()),
        )
    assert replay.status_code == 200
    assert replay.body["already_entered"] is True
    assert replay.body["entry_id"] == by_user[probe_user]

    async with maker() as session:
        final_count = await session.scalar(
            text("SELECT count(*) FROM pool_entries WHERE pool_id = :p"), {"p": pool_id}
        )
    assert final_count == BUYERS

    # Cleanup of the committed fixture data (audit rows stay: append-only).
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM entry_receipts WHERE entry_id IN "
                "(SELECT id FROM pool_entries WHERE pool_id = :p)"
            ),
            {"p": pool_id},
        )
        await conn.execute(
            text("DELETE FROM confirmed_requests WHERE pool_id = :p"), {"p": pool_id}
        )
        await conn.execute(text("DELETE FROM pool_entries WHERE pool_id = :p"), {"p": pool_id})
        await conn.execute(
            text("DELETE FROM idempotency_keys WHERE key LIKE :pattern"),
            {"pattern": f"entries_join:{pool_id}:%"},
        )
        await conn.execute(text("DELETE FROM pools WHERE id = :p"), {"p": pool_id})
        await conn.execute(
            text("DELETE FROM paypal_links WHERE paypal_account_key LIKE :pattern"),
            {"pattern": f"%{pool_tag}%"},
        )
        await conn.execute(
            text("DELETE FROM users WHERE email LIKE :pattern"),
            {"pattern": f"%{pool_tag}%"},
        )
