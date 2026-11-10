"""T03B01: PT-13 / F14 / F15 — parallel joins, one entry per user and key.

Runs with ``RATE_LIMIT_ENABLED=false`` (config-and-errors.md §3, CR-3): the
unique constraints on ``(pool_id, user_id)`` and
``(pool_id, paypal_account_key)`` are what these tests prove, not the limiter.
``test_f14_concurrent_joins_one_entry`` is the 200-parallel-joins test the task
row names: 200 concurrent join transactions race over one pool — 100 buyers, each
submitting twice through an independent transaction (the F14 "same buyer, many
tabs" shape) — and exactly one entry per buyer may exist.
``test_f15_agent_and_human_same_account_one_entry`` covers the two identity paths
of one account through the same entry service: the buyer session and a
``delegations`` row (the ``/agent/v1`` HTTP lane arrives in Phase 7 and re-asserts
it at IG-7).

Data is committed on a dedicated engine: the joins must be real, concurrent,
separate transactions. The disposable ``*_test`` database is wiped afterwards.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from fairpool.db.session import normalize_database_url
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import verify_ed25519
from fairpool.modules.pools.receipts import public_key_b64url, signing_seed
from tests.conftest import database_url
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
async def engine(migrated_db: None) -> AsyncEngine:
    # The same loopback *_test resolution the rest of the suite uses, so this file
    # runs from a plain shell instead of demanding an exported DATABASE_URL (D-P3-05).
    # migrated_db is explicit: CI migrates before pytest, but a fresh clone runs
    # `make test` against an empty database, where these committed joins need tables.
    url = database_url()
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


async def test_f14_concurrent_joins_one_entry(engine: AsyncEngine) -> None:
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

    # F14's last word: one entry row per buyer in the database, not in the answers.
    async with maker() as session:
        final_count = await session.scalar(
            text("SELECT count(*) FROM pool_entries WHERE pool_id = :p"), {"p": pool_id}
        )
    assert final_count == BUYERS

    await _wipe(engine, pool_id, pool_tag)


async def test_f15_agent_and_human_same_account_one_entry(engine: AsyncEngine) -> None:
    """F15 (I6): one buyer session and one ``delegations`` row over one entry service.

    The two identity paths of the same linked PayPal account must land on the same
    single entry, whichever path got there first and whether or not they race. The
    ``/agent/v1`` HTTP lane is Phase 7 work, so this drives the same
    ``JoinService.join`` with a real ``delegations`` row (the entry service records the
    delegation id and ``submitted_via``; token authentication and cap enforcement are
    that lane's job, not invented here).
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    tag = uuid.uuid4()
    scenarios = ("agent-first", "human-first", "racing")

    async with maker() as session, session.begin():
        pool_id = await open_pool(session)
        players: dict[str, dict[str, uuid.UUID]] = {}
        for name in scenarios:
            user = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO users (id, email, password_hash, display_name) "
                    "VALUES (:id, :email, 'hash', 'Buyer')"
                ),
                {"id": user, "email": f"f15-{name}-{tag}@example.test"},
            )
            await session.execute(
                text(
                    "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
                    "VALUES (:id, :user, :account)"
                ),
                {
                    "id": uuid.uuid4(),
                    "user": user,
                    "account": f"F15ACCT-{tag}-{name}",
                },
            )
            delegation = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO delegations (id, user_id, token_hash, scope, max_cap_cents, "
                    "expires_at) VALUES (:id, :user, :hash, CAST(:scope AS jsonb), :cap, "
                    "now() + interval '1 hour')"
                ),
                {
                    "id": delegation,
                    "user": user,
                    "hash": f"f15-token-hash-{tag}-{name}",
                    "scope": json.dumps({"pool_ids": [str(pool_id)], "category": None}),
                    "cap": 60_000,
                },
            )
            players[name] = {
                "user": user,
                "delegation": delegation,
                "human_cr": await manual_confirm(session, user, pool_id, max_total_cents=51_000),
                "agent_cr": await manual_confirm(session, user, pool_id, max_total_cents=52_000),
            }
        await session.execute(
            text("UPDATE pools SET require_paypal_link = true WHERE id = :p"), {"p": pool_id}
        )

    service = join_service()

    async def join(player: dict[str, uuid.UUID], *, via_agent: bool, key: str) -> tuple[int, dict]:
        async with maker() as session, session.begin():
            outcome = await service.join(
                session,
                pool_id=pool_id,
                user_id=player["user"],
                confirmed_request_id=player["agent_cr"] if via_agent else player["human_cr"],
                idempotency_key=key,
                delegation_id=player["delegation"] if via_agent else None,
            )
        return outcome.status_code, outcome.body

    async def entry_row(player: dict[str, uuid.UUID]) -> tuple[str, str | None]:
        async with maker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT submitted_via, delegation_id::text FROM pool_entries "
                        "WHERE pool_id = :p AND user_id = :u"
                    ),
                    {"p": pool_id, "u": player["user"]},
                )
            ).one()
        return str(row[0]), row[1]

    try:
        # The agent path first: the entry carries the delegation, and the buyer's own
        # session then answers already_entered over the same receipt.
        agent_first = players["agent-first"]
        code, body = await join(agent_first, via_agent=True, key="f15-agent-first")
        assert code == 201 and body["already_entered"] is False
        session_code, session_body = await join(agent_first, via_agent=False, key="f15-agent-then")
        assert session_code == 200 and session_body["already_entered"] is True
        assert session_body["entry_id"] == body["entry_id"]
        assert await entry_row(agent_first) == ("agent", str(agent_first["delegation"]))

        # The buyer session first: the delegation-backed path cannot open a second door.
        human_first = players["human-first"]
        code, body = await join(human_first, via_agent=False, key="f15-human-first")
        assert code == 201
        agent_code, agent_body = await join(human_first, via_agent=True, key="f15-human-then")
        assert agent_code == 200 and agent_body["entry_id"] == body["entry_id"]
        assert await entry_row(human_first) == ("human", None)

        # Both paths at once: one entry row, and the loser replays the winner.
        racing = players["racing"]
        results = await asyncio.gather(
            join(racing, via_agent=False, key="f15-race-human"),
            join(racing, via_agent=True, key="f15-race-agent"),
        )
        assert sorted(code for code, _ in results) == [200, 201]
        assert results[0][1]["entry_id"] == results[1][1]["entry_id"]
        assert results[0][1]["receipt"] == results[1][1]["receipt"]

        async with maker() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT count(*), count(DISTINCT paypal_account_key) FROM pool_entries "
                        "WHERE pool_id = :p"
                    ),
                    {"p": pool_id},
                )
            ).one()
            # A delegation that is not the caller's own is refused, never recorded.
            other = players["racing"]
            stranger = players["human-first"]
        assert rows == (3, 3)
        with pytest.raises(ApplicationError) as refused:
            async with maker() as session, session.begin():
                await service.join(
                    session,
                    pool_id=pool_id,
                    user_id=other["user"],
                    confirmed_request_id=other["agent_cr"],
                    idempotency_key="f15-stranger",
                    delegation_id=stranger["delegation"],
                )
        assert refused.value.code == "DELEGATION_INVALID"
    finally:
        await _wipe(engine, pool_id, tag)


async def _wipe(engine: AsyncEngine, pool_id: uuid.UUID, tag: uuid.UUID) -> None:
    """Delete the committed fixture rows (audit rows stay: the chain is append-only)."""
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
        await conn.execute(
            text("DELETE FROM delegations WHERE token_hash LIKE :pattern"),
            {"pattern": f"%{tag}%"},
        )
        await conn.execute(text("DELETE FROM pools WHERE id = :p"), {"p": pool_id})
        await conn.execute(
            text("DELETE FROM paypal_links WHERE paypal_account_key LIKE :pattern"),
            {"pattern": f"%{tag}%"},
        )
        await conn.execute(
            text("DELETE FROM users WHERE email LIKE :pattern"),
            {"pattern": f"%{tag}%"},
        )
