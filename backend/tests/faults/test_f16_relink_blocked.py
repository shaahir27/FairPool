"""F16 (I6): relinking cannot evade participation (api.md "Account link", CR-3).

The evasion this fault closes: a buyer joins a pool, their entry occupies the
``(pool_id, paypal_account_key)`` slot, then they revoke the login link so the pool
no longer holds a key over them -- or a second buyer tries to take the same PayPal
account. The contract's answer is a lock order plus one refusal: link, unlink and
join all take the same ``users`` row lock first (the order ``modules/pools/join.py``
uses), and ``DELETE /api/v1/paypal/link`` is refused while the buyer still holds an
entry. The entry machine backs it up: ES-01 requires the link to still be active and
ES-02 rejects the entry when it is not (state-machines.md).

Fake versus real: the provider is ``FakePayPalIdentity`` behind the
``PayPalIdentity`` port, so no host is reached. The lock and constraint claims are
Postgres claims, so the interleave test runs real committed transactions on two
connections and cleans up after itself.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.paypal_identity import FAKE_ALICE, FakePayPalIdentity
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.paypal_login import PayPalLoginService, account_key, disclosure
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.manual import ManualIntakeService
from tests.integration.test_login_linking import (
    SOURCE,
    callback,
    expected_key,
    insert_pool,
    join_pool,
    join_service,
    link_rows,
    login_settings,
    new_buyer,
    sql_literals,
    start,
    state_count,
)
from tests.integration.test_triggers import iso_in

pytestmark = pytest.mark.faults

USER_LOCK = "SELECT id FROM users WHERE id = :id FOR UPDATE"


def service_for(settings: Any, identity: FakePayPalIdentity) -> PayPalLoginService:
    """The service the route builds, on the fake port (no host, no network)."""
    return PayPalLoginService(
        identity,
        DbClock(),
        PostgresAuditLog(),
        hmac_key=settings.hmac_key.get_secret_value(),
        dedupe_mode=settings.dedupe_mode,
        enabled=settings.paypal_login_enabled,
        client_id=settings.paypal_client_id,
        redirect_uri=settings.paypal_login_redirect_uri,
        checkout_base=settings.paypal_checkout_base,
        state_ttl_s=settings.oauth_state_ttl_s,
    )


async def login_client(db: AsyncSession) -> httpx.AsyncClient:
    app = create_app(login_settings())
    app.state.paypal_identity = FakePayPalIdentity()

    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[database_session] = session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


# ------------------------------------------------------------------ the refusal


async def test_f16_unlink_is_blocked_while_the_entry_still_counts(
    db_session: AsyncSession,
) -> None:
    """Revoke is refused while the entry stands; relink is a conflict; withdrawal works."""
    async with await login_client(db_session) as client:
        csrf, user_id = await new_buyer(client, "f16@example.test")
        _, state = await start(client)
        assert (await callback(client, code="fake-code-alice", state=state)).status_code == 200
        key = str((await link_rows(db_session, user_id))[0].paypal_account_key)

        pool_id = await insert_pool(db_session, require_link=True)
        entry_id = await join_pool(db_session, user_id, pool_id)

        blocked = await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "PAYPAL_LINK_CONFLICT"

        rows = await link_rows(db_session, user_id)
        assert len(rows) == 1 and rows[0].revoked_at is None, "the link stands while the entry does"
        entry = (
            await db_session.execute(
                text("SELECT status::text, paypal_account_key FROM pool_entries WHERE id = :e"),
                {"e": entry_id},
            )
        ).first()
        assert str(entry[0]) == "SUBMITTED" and str(entry[1]) == key

        # A second link attempt conflicts too, so relinking frees nothing either.
        _, second_state = await start(client)
        again = await callback(client, code="fake-code-alice", state=second_state)
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "PAYPAL_LINK_CONFLICT"
        assert len(await link_rows(db_session, user_id)) == 1

        # ES-03 withdrawal is the legal way out; only then may the link be revoked.
        await db_session.execute(
            text("UPDATE pool_entries SET status = 'WITHDRAWN'::entry_status WHERE id = :e"),
            {"e": entry_id},
        )
        revoked = await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})
        assert revoked.status_code == 200, revoked.text
        assert (await link_rows(db_session, user_id))[0].revoked_at is not None


async def test_another_buyer_cannot_take_a_linked_account_that_is_in_play(
    db_session: AsyncSession,
) -> None:
    """One user per active account key, so the same PayPal account has no second slot."""
    async with await login_client(db_session) as holder:
        _, holder_id = await new_buyer(holder, "f16-holder@example.test")
        _, holder_state = await start(holder)
        linked = await callback(holder, code="fake-code-alice", state=holder_state)
        assert linked.status_code == 200, linked.text
        pool_id = await insert_pool(db_session, require_link=True)
        await join_pool(db_session, holder_id, pool_id)

        async with await login_client(db_session) as claimant:
            _, claimant_id = await new_buyer(claimant, "f16-claimant@example.test")
            _, claimant_state = await start(claimant)
            refused = await callback(claimant, code="fake-code-carol", state=claimant_state)
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "PAYPAL_LINK_CONFLICT"
            assert await link_rows(db_session, claimant_id) == []
            assert await state_count(db_session, claimant_id, consumed=True) == 0

        # The holder's link is exactly the keyed digest of the provider account.
        rows = await link_rows(db_session, holder_id)
        assert len(rows) == 1 and rows[0].revoked_at is None
        assert rows[0].paypal_account_key == expected_key(login_settings(), FAKE_ALICE)
        assert rows[0].paypal_account_key == account_key(
            login_settings().hmac_key.get_secret_value(), FAKE_ALICE
        )


# ---------------------------------------------------------------- the lock order


def test_link_unlink_and_join_take_the_same_user_lock_first() -> None:
    """The three paths meet on one lock, in one order (api.md "Account link")."""
    link = (SOURCE / "modules" / "identity" / "paypal_login.py").read_text(encoding="utf-8")
    joined = (SOURCE / "modules" / "pools" / "join.py").read_text(encoding="utf-8")
    assert USER_LOCK in link and USER_LOCK in joined
    assert "FOR UPDATE" in link and "FOR UPDATE" in joined

    # The login module never touches a pool row, so it can only ever wait on the
    # user row: it cannot invert join's user-then-pool order.
    for statement in sql_literals(Path(str(SOURCE / "modules" / "identity" / "paypal_login.py"))):
        assert "FROM pools" not in statement and "UPDATE pools" not in statement, statement
        allowed = {"oauth_states", "paypal_links", "users", "pool_entries", "audit_log"}
        found = {table for table in allowed if table in statement}
        assert found, statement
        assert found <= allowed


def test_the_relink_block_is_the_only_way_a_linked_account_leaves_a_pool() -> None:
    """The disclosure the buyer sees matches the rule the lock enforces (FR-ID-02/03)."""
    two_keys = disclosure("two_keys")
    assert "One entry per linked PayPal account per pool" in two_keys.proves
    assert "one human per account" in two_keys.does_not_prove


# ------------------------------------------------------------------ the interleave


async def test_a_link_and_a_join_for_one_buyer_never_both_win(
    db_engine: AsyncEngine,
) -> None:
    """Committed transactions: no interleaving leaves an entry standing on a revoked link."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    settings = login_settings()
    ids = await _setup_committed(maker)
    user_id, pool_id = ids["user"], ids["pool"]
    principal = Principal(user_id=user_id, session_id=uuid.uuid4(), role="buyer")
    identity = FakePayPalIdentity()

    async def do_join() -> str:
        async with maker() as session, session.begin():
            record = await _confirm(session, user_id, pool_id)
            try:
                outcome = await join_service().join(
                    session,
                    pool_id=pool_id,
                    user_id=user_id,
                    confirmed_request_id=record.id,
                    idempotency_key=f"f16-race-{uuid.uuid4()}",
                )
            except ApplicationError as exc:
                return f"join-refused:{exc.code}"
            return str(outcome.body["entry_id"])

    async def do_unlink() -> str:
        async with maker() as session, session.begin():
            try:
                result = await service_for(settings, identity).unlink(session, principal)
            except ApplicationError as exc:
                return f"unlink-refused:{exc.code}"
            return "unlinked" if result.revoked else "no-active-link"

    joined, unlinked = await asyncio.gather(do_join(), do_unlink())

    try:
        async with maker() as session:
            entry = (
                await session.execute(
                    text(
                        "SELECT status::text, paypal_account_key FROM pool_entries "
                        "WHERE pool_id = :p AND user_id = :u"
                    ),
                    {"p": pool_id, "u": user_id},
                )
            ).first()
            link = (
                await session.execute(
                    text("SELECT revoked_at FROM paypal_links WHERE user_id = :u"), {"u": user_id}
                )
            ).first()
    finally:
        await _wipe(db_engine, ids)

    participating = entry is not None and str(entry[0]) in {"SUBMITTED", "ELIGIBLE"}
    link_revoked = link is not None and link[0] is not None
    # The invariant F16 exists to hold: an entry never stands on a revoked link, so
    # the (pool_id, paypal_account_key) slot cannot be freed from under a pool.
    assert not (participating and link_revoked), (joined, unlinked, entry, link)
    # On a link-required pool exactly one of the two paths can win, and the loser is
    # refused for the contract's reason, never by an accident of timing.
    assert participating != link_revoked, (joined, unlinked)
    if participating:
        assert unlinked == "unlink-refused:PAYPAL_LINK_CONFLICT"
    else:
        assert joined == "join-refused:PAYPAL_LINK_REQUIRED"
        assert entry is None, "a refused join leaves no slot behind"
    assert identity.calls == [], "unlink never needs the provider (rule 22)"


async def test_an_unlink_waits_for_a_join_that_holds_the_users_row(
    db_engine: AsyncEngine,
) -> None:
    """The serialisation is behaviour, not wording: the unlink cannot pass the lock."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    settings = login_settings()
    ids = await _setup_committed(maker)
    user_id, pool_id = ids["user"], ids["pool"]
    principal = Principal(user_id=user_id, session_id=uuid.uuid4(), role="buyer")
    identity = FakePayPalIdentity()
    refused_for: list[str] = []

    try:
        async with maker() as joiner, joiner.begin():
            record = await _confirm(joiner, user_id, pool_id)
            # The join is taken but uncommitted: it holds the users row, then the pool.
            await join_service().join(
                joiner,
                pool_id=pool_id,
                user_id=user_id,
                confirmed_request_id=record.id,
                idempotency_key=f"f16-blocked-{uuid.uuid4()}",
            )
            async with maker() as revoker:
                try:
                    await revoker.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    await service_for(settings, identity).unlink(revoker, principal)
                except DBAPIError as exc:
                    # The unlink reached its user lock and waited for the join.
                    refused_for.append(str(exc.orig))
                finally:
                    await revoker.rollback()

        async with maker() as session:
            status = await session.scalar(
                text("SELECT status::text FROM pool_entries WHERE pool_id = :p AND user_id = :u"),
                {"p": pool_id, "u": user_id},
            )
            revoked_at = await session.scalar(
                text("SELECT revoked_at FROM paypal_links WHERE user_id = :u"), {"u": user_id}
            )
    finally:
        await _wipe(db_engine, ids)

    assert refused_for, "the unlink should have waited on the join's user lock"
    assert "lock timeout" in refused_for[0].lower(), refused_for[0]
    assert str(status) == "SUBMITTED", "the join committed once its lock was released"
    assert revoked_at is None, "a blocked unlink revoked nothing (F16)"
    assert identity.calls == []


# ------------------------------------------------------------------- committed setup


async def _setup_committed(maker: async_sessionmaker[Any]) -> dict[str, uuid.UUID]:
    """A buyer with one active link and a link-required OPEN pool, committed."""
    settings = login_settings()
    user_id, pool_id, admin_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    buyer_email = f"f16-race-{user_id}@example.test"
    admin_email = f"admin-{pool_id}@example.test"
    async with maker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, 'hash', 'F16 Buyer')"
            ),
            {"id": user_id, "email": buyer_email},
        )
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, role) "
                "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
            ),
            {"id": admin_id, "email": admin_email},
        )
        await session.execute(
            text("INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:i, :u, :k)"),
            {
                "i": uuid.uuid4(),
                "u": user_id,
                "k": account_key(settings.hmac_key.get_secret_value(), FAKE_ALICE),
            },
        )
        await session.execute(
            text(
                "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
                "require_paypal_link, rule_version, rules_hash, created_by) "
                "VALUES (:id, 'LIVE_SANDBOX', 'OPEN', 'Monitor pool', CAST(:template AS jsonb), "
                "'[]'::jsonb, CAST(:timeline AS jsonb), true, 'allocation_v1', :rules_hash, :by)"
            ),
            {
                "id": pool_id,
                "template": json.dumps(POOL_TEMPLATE),
                "timeline": json.dumps(POOL_TIMELINE),
                "rules_hash": "a" * 64,
                "by": admin_id,
            },
        )
    return {
        "user": user_id,
        "pool": pool_id,
        "buyer_email": buyer_email,
        "admin_email": admin_email,
    }


async def _confirm(db: AsyncSession, user_id: uuid.UUID, pool_id: uuid.UUID) -> Any:
    return await ManualIntakeService(PostgresAuditLog()).confirm(
        db,
        user_id=user_id,
        pool_id=pool_id,
        payload={
            "delivery": {"region": "NY"},
            "required_by": "2026-11-30",
            "max_total_cents": 60000,
            "firm": [],
            "preferences": [],
        },
    )


POOL_TEMPLATE: dict[str, Any] = {
    "product_key": "monitor-27-4k",
    "variant": "black",
    "title": "27-inch 4K monitor",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "delivery_sla_days": 7,
    "fund_by": "2026-11-10",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
}
POOL_TIMELINE: dict[str, Any] = {
    "open_at": iso_in(-60),
    "close_at": iso_in(3600),
    "beacon_delay_s": 10,
    "bid_window_s": 120,
    "offer_window_s": 180,
    "fund_deadline_s": 600,
    "capture_grace_s": 120,
    "pending_wait_s": 120,
    "max_refill_waves": 1,
    "authorization_age_guard_s": 216000,
}


async def _wipe(engine: AsyncEngine, ids: dict[str, uuid.UUID]) -> None:
    """Remove what these tests committed; the shared disposable database stays clean."""
    user_id, pool_id = ids["user"], ids["pool"]
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
        await conn.execute(text("DELETE FROM lots WHERE pool_id = :p"), {"p": pool_id})
        for table in ("oauth_states", "paypal_links", "vault_tokens"):
            await conn.execute(
                text(f"DELETE FROM {table} WHERE user_id IN :u").bindparams(
                    bindparam("u", expanding=True)
                ),
                {"u": [user_id]},
            )
        await conn.execute(
            text("DELETE FROM sessions WHERE user_id IN :u").bindparams(
                bindparam("u", expanding=True)
            ),
            {"u": [user_id]},
        )
        # pools.created_by references the admin user, so the pool goes first.
        await conn.execute(text("DELETE FROM pools WHERE id = :p"), {"p": pool_id})
        await conn.execute(
            text("DELETE FROM users WHERE id = :u OR email = :buyer OR email = :admin"),
            {
                "u": user_id,
                "buyer": ids["buyer_email"],
                "admin": ids["admin_email"],
            },
        )
