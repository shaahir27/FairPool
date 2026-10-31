"""T01A01: every trigger and every named unique/partial index is enforced."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

HEX64 = "0" * 64


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utc_in(seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def iso_in(seconds: int) -> str:
    return utc_in(seconds).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def as_json(value: Any) -> str:
    return json.dumps(value)


async def expect_error(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any] | None = None,
    *,
    sqlstate: str = "23514",
) -> DBAPIError:
    with pytest.raises(DBAPIError) as excinfo:
        async with session.begin_nested():
            await session.execute(text(sql), params or {})
    actual = getattr(excinfo.value.orig, "sqlstate", None)
    assert actual == sqlstate, f"expected SQLSTATE {sqlstate}, got {actual}: {excinfo.value}"
    return excinfo.value


async def add_user(
    session: AsyncSession, *, role: str = "buyer", email: str | None = None
) -> uuid.UUID:
    user_id = new_id()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', CAST(:role AS user_role), 'Test User')"
        ),
        {"id": user_id, "email": email or f"{user_id}@example.test", "role": role},
    )
    return user_id


async def add_pool(
    session: AsyncSession,
    *,
    mode: str = "LIVE_SANDBOX",
    status: str = "OPEN",
    close_in: int = 3600,
    currency: str = "USD",
) -> uuid.UUID:
    pool_id = new_id()
    admin = await add_user(session, role="admin")
    template = {
        "product_key": "monitor-27-4k",
        "variant": "black",
        "title": "27-inch 4K monitor",
        "condition": "NEW",
        "quantity": 1,
        "currency": currency,
        "bundle_contents": ["monitor", "stand", "power cable"],
        "delivery_sla_days": 7,
        "fund_by": "2026-11-10",
        "min_return_days": 14,
        "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
    }
    timeline = {
        "open_at": iso_in(-60),
        "close_at": iso_in(close_in),
        "beacon_delay_s": 10,
        "bid_window_s": 120,
        "offer_window_s": 180,
        "fund_deadline_s": 600,
        "capture_grace_s": 120,
        "pending_wait_s": 120,
        "max_refill_waves": 1,
        "authorization_age_guard_s": 216000,
    }
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, created_by) "
            "VALUES (:id, CAST(:mode AS pool_mode), CAST(:status AS pool_status), 'Monitor', "
            "CAST(:template AS jsonb), CAST(:lot_plan AS jsonb), CAST(:timeline AS jsonb), "
            "true, 'allocation_v1', :created_by)"
        ),
        {
            "id": pool_id,
            "mode": mode,
            "status": status,
            "template": as_json(template),
            "lot_plan": as_json([]),
            "timeline": as_json(timeline),
            "created_by": admin,
        },
    )
    return pool_id


async def add_entry(
    session: AsyncSession,
    pool_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    synthetic: bool = False,
    account_key: str | None = None,
    currency: str = "USD",
) -> uuid.UUID:
    entry_id = new_id()
    user = user_id or await add_user(session)
    request = {
        "v": 1,
        "pool_id": str(pool_id),
        "product_key": "monitor-27-4k",
        "variant": "black",
        "condition": "NEW",
        "quantity": 1,
        "currency": currency,
        "delivery": {"zone_id": "US-EAST", "region": "NY", "country": "US"},
        "required_by": "2026-11-30",
        "max_total_cents": 60000,
        "firm": [],
        "preferences": [],
    }
    await session.execute(
        text(
            "INSERT INTO pool_entries (id, pool_id, user_id, paypal_account_key, "
            "canonical_request, request_hash, cap_cents, zone_id, status, submitted_via, synthetic) "
            "VALUES (:id, :pool, :user, :account, CAST(:request AS jsonb), :hash, 60000, "
            "'US-EAST', 'SUBMITTED', 'human', :synthetic)"
        ),
        {
            "id": entry_id,
            "pool": pool_id,
            "user": user,
            "account": account_key,
            "request": as_json(request),
            "hash": HEX64,
            "synthetic": synthetic,
        },
    )
    return entry_id


async def add_lot(
    session: AsyncSession,
    pool_id: uuid.UUID,
    *,
    status: str = "AWARDED",
    seats: int = 3,
    lot_index: int = 0,
    lot_order: int = 0,
) -> uuid.UUID:
    lot_id = new_id()
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, 'US-EAST', :idx, :order, "
            ":seats, 2, CAST(:status AS lot_status), now(), now())"
        ),
        {
            "id": lot_id,
            "pool": pool_id,
            "idx": lot_index,
            "order": lot_order,
            "seats": seats,
            "status": status,
        },
    )
    return lot_id


async def add_merchant(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = await add_user(session)
    merchant_id = new_id()
    await session.execute(
        text("INSERT INTO merchants (id, user_id, display_name) VALUES (:id, :user, 'Merchant')"),
        {"id": merchant_id, "user": user_id},
    )
    return merchant_id, user_id


async def add_bid(session: AsyncSession, lot_id: uuid.UUID, merchant_id: uuid.UUID) -> uuid.UUID:
    bid_id = new_id()
    await session.execute(
        text(
            "INSERT INTO bids (id, lot_id, merchant_id, status) "
            "VALUES (:id, :lot, :merchant, 'CONFIRMED')"
        ),
        {"id": bid_id, "lot": lot_id, "merchant": merchant_id},
    )
    return bid_id


async def add_bid_revision(
    session: AsyncSession, bid_id: uuid.UUID, revision: int = 1
) -> uuid.UUID:
    revision_id = new_id()
    await session.execute(
        text(
            "INSERT INTO bid_revisions (id, bid_id, revision, structured, receipt_hash, receipt_signature) "
            "VALUES (:id, :bid, :revision, CAST(:structured AS jsonb), :hash, 'sig')"
        ),
        {
            "id": revision_id,
            "bid": bid_id,
            "revision": revision,
            "structured": as_json({"v": 1, "capacity": 3, "moq": 2, "tiers": []}),
            "hash": HEX64,
        },
    )
    return revision_id


async def add_award(
    session: AsyncSession, lot_id: uuid.UUID, revision_id: uuid.UUID, merchant_id: uuid.UUID
) -> uuid.UUID:
    award_id = new_id()
    await session.execute(
        text(
            "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, item_cents, "
            "moq, totals, valid_until, rule_version, award_hash) "
            "VALUES (:id, :lot, :revision, :merchant, 0, 47000, 2, CAST(:totals AS jsonb), "
            ":valid_until, 'ranking_v1', :hash)"
        ),
        {
            "id": award_id,
            "lot": lot_id,
            "revision": revision_id,
            "merchant": merchant_id,
            "totals": as_json({}),
            "valid_until": utc_in(3600),
            "hash": HEX64,
        },
    )
    return award_id


async def add_buyer_order(
    session: AsyncSession,
    lot_id: uuid.UUID,
    entry_id: uuid.UUID,
    *,
    status: str = "CAPTURED",
    total_cents: int = 50000,
) -> uuid.UUID:
    order_id = new_id()
    await session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, "
            "total_cents, breakdown) VALUES (:id, :lot, :entry, CAST(:status AS buyer_order_status), "
            ":expires, :total, CAST(:breakdown AS jsonb))"
        ),
        {
            "id": order_id,
            "lot": lot_id,
            "entry": entry_id,
            "status": status,
            "expires": utc_in(3600),
            "total": total_cents,
            "breakdown": as_json({"item_cents": total_cents, "shipping_cents": 0, "tax_cents": 0}),
        },
    )
    return order_id


async def add_paypal_order(
    session: AsyncSession,
    buyer_order_id: uuid.UUID,
    *,
    attempt: int = 0,
    paypal_id: str | None = None,
) -> str:
    paypal_order_id = paypal_id or f"ORDER-{uuid.uuid4()}"
    await session.execute(
        text(
            "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, intent, "
            "amount_cents, raw) VALUES (:id, :buyer, :attempt, :paypal, 'COMPLETED', 'AUTHORIZE', "
            "50000, CAST(:raw AS jsonb))"
        ),
        {
            "id": new_id(),
            "buyer": buyer_order_id,
            "attempt": attempt,
            "paypal": paypal_order_id,
            "raw": as_json({}),
        },
    )
    return paypal_order_id


async def add_capture(
    session: AsyncSession, buyer_order_id: uuid.UUID, *, capture_id: str | None = None
) -> str:
    paypal_capture_id = capture_id or f"CAP-{uuid.uuid4()}"
    await session.execute(
        text(
            "INSERT INTO paypal_captures (id, buyer_order_id, paypal_capture_id, status, "
            "amount_cents, final_capture, raw) VALUES (:id, :buyer, :capture, 'COMPLETED', "
            "50000, true, CAST(:raw AS jsonb))"
        ),
        {"id": new_id(), "buyer": buyer_order_id, "capture": paypal_capture_id, "raw": as_json({})},
    )
    return paypal_capture_id


async def add_ledger(session: AsyncSession, lot_id: uuid.UUID, buyer_order_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO ledger_entries (id, lot_id, buyer_order_id, kind, amount_cents, paypal_ref, "
            "idempotency_key, source) VALUES (:id, :lot, :buyer, 'CAPTURE_COMPLETED', 50000, "
            "'CAP-1', :key, 'api')"
        ),
        {"id": new_id(), "lot": lot_id, "buyer": buyer_order_id, "key": f"ledger-{uuid.uuid4()}"},
    )


async def add_webhook(session: AsyncSession) -> str:
    event_id = f"WH-{uuid.uuid4()}"
    await session.execute(
        text(
            "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body) "
            "VALUES (:id, :event, 'PAYMENT.CAPTURE.COMPLETED', '{\"id\":\"x\"}')"
        ),
        {"id": new_id(), "event": event_id},
    )
    return event_id


async def add_audit(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO audit_log (prev_hash, hash, actor, action, subject_type, payload) "
            "VALUES (:prev, :hash, 'tester', 'test', 'test', CAST('{}' AS jsonb))"
        ),
        {"prev": HEX64, "hash": HEX64},
    )


async def test_audit_ledger_and_awards_are_append_only(db_session: AsyncSession):
    await add_audit(db_session)
    await expect_error(db_session, "UPDATE audit_log SET actor = 'x'")
    await expect_error(db_session, "DELETE FROM audit_log")

    pool_id = await add_pool(db_session)
    entry_id = await add_entry(db_session, pool_id)
    lot_id = await add_lot(db_session, pool_id)
    order_id = await add_buyer_order(db_session, lot_id, entry_id)
    await add_ledger(db_session, lot_id, order_id)
    await expect_error(db_session, "UPDATE ledger_entries SET amount_cents = 1")
    await expect_error(db_session, "DELETE FROM ledger_entries")

    merchant_id, _ = await add_merchant(db_session)
    bid_id = await add_bid(db_session, lot_id, merchant_id)
    revision_id = await add_bid_revision(db_session, bid_id)
    await add_award(db_session, lot_id, revision_id, merchant_id)
    await expect_error(db_session, "UPDATE awards SET moq = 3")
    await expect_error(db_session, "DELETE FROM awards")


async def test_webhook_raw_body_is_immutable(db_session: AsyncSession):
    event_id = await add_webhook(db_session)
    await expect_error(
        db_session,
        "UPDATE webhook_events SET raw_body = 'changed' WHERE paypal_event_id = :event",
        {"event": event_id},
    )
    await db_session.execute(
        text("UPDATE webhook_events SET event_type = 'OTHER' WHERE paypal_event_id = :event"),
        {"event": event_id},
    )
    await db_session.execute(
        text("DELETE FROM webhook_events WHERE paypal_event_id = :event"), {"event": event_id}
    )


async def test_pool_mode_is_immutable_after_draft(db_session: AsyncSession):
    pool_id = await add_pool(db_session, status="DRAFT")
    await db_session.execute(
        text("UPDATE pools SET mode = 'SIMULATION' WHERE id = :pool"), {"pool": pool_id}
    )
    await db_session.execute(
        text("UPDATE pools SET status = 'OPEN' WHERE id = :pool"), {"pool": pool_id}
    )
    await expect_error(
        db_session,
        "UPDATE pools SET mode = 'LIVE_SANDBOX' WHERE id = :pool",
        {"pool": pool_id},
    )


async def test_entry_insert_window(db_session: AsyncSession):
    draft_pool = await add_pool(db_session, status="DRAFT")
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, cap_cents, "
        "zone_id, submitted_via) VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, 60000, "
        "'US-EAST', 'human')",
        {
            "id": new_id(),
            "pool": draft_pool,
            "user": await add_user(db_session),
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
    )
    past_pool = await add_pool(db_session, close_in=-60)
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, cap_cents, "
        "zone_id, submitted_via) VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, 60000, "
        "'US-EAST', 'human')",
        {
            "id": new_id(),
            "pool": past_pool,
            "user": await add_user(db_session),
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
    )
    open_pool = await add_pool(db_session)
    await add_entry(db_session, open_pool)


async def test_entry_synthetic_flag_must_match_pool_mode(db_session: AsyncSession):
    live_pool = await add_pool(db_session, mode="LIVE_SANDBOX")
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, cap_cents, "
        "zone_id, submitted_via, synthetic) VALUES (:id, :pool, :user, CAST(:request AS jsonb), "
        ":hash, 60000, 'US-EAST', 'human', true)",
        {
            "id": new_id(),
            "pool": live_pool,
            "user": await add_user(db_session),
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
    )
    sim_pool = await add_pool(db_session, mode="SIMULATION")
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, cap_cents, "
        "zone_id, submitted_via, synthetic) VALUES (:id, :pool, :user, CAST(:request AS jsonb), "
        ":hash, 60000, 'US-EAST', 'human', false)",
        {
            "id": new_id(),
            "pool": sim_pool,
            "user": await add_user(db_session),
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
    )
    await add_entry(db_session, live_pool)
    await add_entry(db_session, sim_pool, synthetic=True)


async def test_paypal_rows_are_live_only(db_session: AsyncSession):
    sim_pool = await add_pool(db_session, mode="SIMULATION")
    sim_entry = await add_entry(db_session, sim_pool, synthetic=True)
    sim_lot = await add_lot(db_session, sim_pool)
    sim_order = await add_buyer_order(db_session, sim_lot, sim_entry)
    await expect_error(
        db_session,
        "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, intent, "
        "amount_cents, raw) VALUES (:id, :buyer, 0, :paypal, 'COMPLETED', 'AUTHORIZE', 50000, "
        "CAST('{}' AS jsonb))",
        {"id": new_id(), "buyer": sim_order, "paypal": f"ORDER-{uuid.uuid4()}"},
    )
    triggers = await db_session.scalar(
        text(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_paypal_rows_live_only' "
            "AND NOT tgisinternal"
        )
    )
    assert triggers == 4

    live_pool = await add_pool(db_session)
    live_entry = await add_entry(db_session, live_pool)
    live_lot = await add_lot(db_session, live_pool)
    live_order = await add_buyer_order(db_session, live_lot, live_entry)
    live_paypal_order = await add_paypal_order(db_session, live_order)
    await expect_error(
        db_session,
        "INSERT INTO paypal_authorizations (id, buyer_order_id, paypal_order_id, paypal_auth_id, "
        "status, amount_cents, raw) VALUES (:id, :buyer, :paypal, :auth, 'CREATED', 50000, "
        "CAST('{}' AS jsonb))",
        {
            "id": new_id(),
            "buyer": sim_order,
            "paypal": live_paypal_order,
            "auth": f"AUTH-{uuid.uuid4()}",
        },
    )
    await expect_error(
        db_session,
        "INSERT INTO paypal_captures (id, buyer_order_id, paypal_capture_id, status, amount_cents, "
        "final_capture, raw) VALUES (:id, :buyer, :capture, 'COMPLETED', 50000, true, "
        "CAST('{}' AS jsonb))",
        {"id": new_id(), "buyer": sim_order, "capture": f"CAP-{uuid.uuid4()}"},
    )
    live_capture = await add_capture(db_session, live_order)
    await expect_error(
        db_session,
        "INSERT INTO paypal_refunds (id, buyer_order_id, paypal_capture_id, paypal_refund_id, seq, "
        "status, amount_cents, raw) VALUES (:id, :buyer, :capture, :refund, 1, 'COMPLETED', "
        "50000, CAST('{}' AS jsonb))",
        {
            "id": new_id(),
            "buyer": sim_order,
            "capture": live_capture,
            "refund": f"REF-{uuid.uuid4()}",
        },
    )


async def test_shipments_require_a_funded_lot_and_captured_order(db_session: AsyncSession):
    pool_id = await add_pool(db_session)
    entry_id = await add_entry(db_session, pool_id)
    lot_id = await add_lot(db_session, pool_id, status="AWARDED")
    order_id = await add_buyer_order(db_session, lot_id, entry_id, status="CAPTURED")
    merchant_id, _ = await add_merchant(db_session)
    insert = (
        "INSERT INTO shipments (id, lot_id, buyer_order_id, merchant_id, carrier, tracking_number, "
        "shipped_at) VALUES (:id, :lot, :buyer, :merchant, 'UPS', :tracking, now())"
    )
    params = {
        "id": new_id(),
        "lot": lot_id,
        "buyer": order_id,
        "merchant": merchant_id,
        "tracking": f"TRACK-{uuid.uuid4()}",
    }
    await expect_error(db_session, insert, params)
    await db_session.execute(
        text("UPDATE lots SET status = 'FUNDED' WHERE id = :lot"), {"lot": lot_id}
    )
    await db_session.execute(text(insert), params)
    second_entry = await add_entry(db_session, pool_id)
    second_order = await add_buyer_order(db_session, lot_id, second_entry, status="AUTHORIZED")
    await expect_error(
        db_session,
        insert,
        {**params, "id": new_id(), "buyer": second_order, "tracking": f"TRACK-{uuid.uuid4()}"},
    )


async def test_identity_unique_constraints(db_session: AsyncSession):
    user_id = await add_user(db_session, email="Case@Example.test")
    await expect_error(
        db_session,
        "INSERT INTO users (id, email, password_hash, display_name) "
        "VALUES (:id, 'case@example.test', 'x', 'Dup')",
        {"id": new_id()},
        sqlstate="23505",
    )
    await db_session.execute(
        text(
            "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
            "VALUES (:id, :user, :account)"
        ),
        {"id": new_id(), "user": user_id, "account": f"ACCOUNT-{uuid.uuid4()}"},
    )
    await expect_error(
        db_session,
        "INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:id, :user, :account)",
        {"id": new_id(), "user": user_id, "account": f"ACCOUNT-{uuid.uuid4()}"},
        sqlstate="23505",
    )
    account = f"SHARED-{uuid.uuid4()}"
    await db_session.execute(
        text(
            "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
            "VALUES (:id, :user, :account)"
        ),
        {"id": new_id(), "user": await add_user(db_session), "account": account},
    )
    await expect_error(
        db_session,
        "INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:id, :user, :account)",
        {"id": new_id(), "user": await add_user(db_session), "account": account},
        sqlstate="23505",
    )
    token_hash = f"token-{uuid.uuid4()}"
    await db_session.execute(
        text(
            "INSERT INTO delegations (id, user_id, token_hash, scope, max_cap_cents, expires_at) "
            "VALUES (:id, :user, :hash, CAST('{}' AS jsonb), 60000, now())"
        ),
        {"id": new_id(), "user": user_id, "hash": token_hash},
    )
    await expect_error(
        db_session,
        "INSERT INTO delegations (id, user_id, token_hash, scope, max_cap_cents, expires_at) "
        "VALUES (:id, :user, :hash, CAST('{}' AS jsonb), 60000, now())",
        {"id": new_id(), "user": user_id, "hash": token_hash},
        sqlstate="23505",
    )
    await db_session.execute(
        text("INSERT INTO catalog_products (id, product_key, name) VALUES (:id, :key, 'Product')"),
        {"id": new_id(), "key": f"product-{uuid.uuid4()}"},
    )


async def test_vault_token_partial_unique(db_session: AsyncSession):
    pool_id = await add_pool(db_session)
    entry_id = await add_entry(db_session, pool_id)
    user_id = await add_user(db_session)
    insert = (
        "INSERT INTO vault_tokens (id, entry_id, user_id, cap_cents, consent_version, "
        "consent_text_sha256, consented_at) VALUES (:id, :entry, :user, 60000, 'v1', :hash, now())"
    )
    first = new_id()
    await db_session.execute(
        text(insert), {"id": first, "entry": entry_id, "user": user_id, "hash": HEX64}
    )
    await expect_error(
        db_session,
        insert,
        {"id": new_id(), "entry": entry_id, "user": user_id, "hash": HEX64},
        sqlstate="23505",
    )
    await db_session.execute(
        text("UPDATE vault_tokens SET deleted_at = now() WHERE id = :id"), {"id": first}
    )
    await db_session.execute(
        text(insert), {"id": new_id(), "entry": entry_id, "user": user_id, "hash": HEX64}
    )


async def test_pool_entry_and_lot_unique_constraints(db_session: AsyncSession):
    pool_id = await add_pool(db_session)
    user_id = await add_user(db_session)
    account = f"ACCOUNT-{uuid.uuid4()}"
    await add_entry(db_session, pool_id, user_id=user_id, account_key=account)
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, cap_cents, "
        "zone_id, submitted_via) VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, 60000, "
        "'US-EAST', 'human')",
        {
            "id": new_id(),
            "pool": pool_id,
            "user": user_id,
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
        sqlstate="23505",
    )
    await expect_error(
        db_session,
        "INSERT INTO pool_entries (id, pool_id, user_id, paypal_account_key, canonical_request, "
        "request_hash, cap_cents, zone_id, submitted_via) VALUES (:id, :pool, :user, :account, "
        "CAST(:request AS jsonb), :hash, 60000, 'US-EAST', 'human')",
        {
            "id": new_id(),
            "pool": pool_id,
            "user": await add_user(db_session),
            "account": account,
            "request": as_json({"currency": "USD"}),
            "hash": HEX64,
        },
        sqlstate="23505",
    )
    lot_id = await add_lot(db_session, pool_id)
    await expect_error(
        db_session,
        "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
        "bid_open_at, bid_close_at) VALUES (:id, :pool, 'US-EAST', 0, 9, 3, 2, now(), now())",
        {"id": new_id(), "pool": pool_id},
        sqlstate="23505",
    )
    entry_id = await add_entry(db_session, pool_id)
    insert_alloc = (
        "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, lot_id, status) "
        "VALUES (:id, :pool, :entry, 'US-EAST', :rank, :hash, :lot, 'SEATED')"
    )
    await db_session.execute(
        text(insert_alloc),
        {
            "id": new_id(),
            "pool": pool_id,
            "entry": entry_id,
            "rank": 1,
            "hash": HEX64,
            "lot": lot_id,
        },
    )
    await expect_error(
        db_session,
        insert_alloc,
        {
            "id": new_id(),
            "pool": pool_id,
            "entry": entry_id,
            "rank": 2,
            "hash": HEX64,
            "lot": lot_id,
        },
        sqlstate="23505",
    )
    await expect_error(
        db_session,
        insert_alloc,
        {
            "id": new_id(),
            "pool": pool_id,
            "entry": await add_entry(db_session, pool_id),
            "rank": 1,
            "hash": HEX64,
            "lot": lot_id,
        },
        sqlstate="23505",
    )


async def test_auction_unique_constraints(db_session: AsyncSession):
    pool_id = await add_pool(db_session)
    lot_id = await add_lot(db_session, pool_id)
    merchant_id, user_id = await add_merchant(db_session)
    await expect_error(
        db_session,
        "INSERT INTO merchants (id, user_id, display_name) VALUES (:id, :user, 'Dup')",
        {"id": new_id(), "user": user_id},
        sqlstate="23505",
    )
    bid_id = await add_bid(db_session, lot_id, merchant_id)
    await expect_error(
        db_session,
        "INSERT INTO bids (id, lot_id, merchant_id) VALUES (:id, :lot, :merchant)",
        {"id": new_id(), "lot": lot_id, "merchant": merchant_id},
        sqlstate="23505",
    )
    revision_id = await add_bid_revision(db_session, bid_id)
    await expect_error(
        db_session,
        "INSERT INTO bid_revisions (id, bid_id, revision, structured, receipt_hash, receipt_signature) "
        "VALUES (:id, :bid, 1, CAST('{}' AS jsonb), :hash, 'sig')",
        {"id": new_id(), "bid": bid_id, "hash": HEX64},
        sqlstate="23505",
    )
    await add_award(db_session, lot_id, revision_id, merchant_id)
    await expect_error(
        db_session,
        "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, item_cents, moq, "
        "totals, valid_until, rule_version, award_hash) VALUES (:id, :lot, :revision, :merchant, 0, "
        "47000, 2, CAST('{}' AS jsonb), now(), 'ranking_v1', :hash)",
        {
            "id": new_id(),
            "lot": lot_id,
            "revision": revision_id,
            "merchant": merchant_id,
            "hash": HEX64,
        },
        sqlstate="23505",
    )


async def test_checkout_unique_constraints(db_session: AsyncSession):
    pool_id = await add_pool(db_session)
    entry_id = await add_entry(db_session, pool_id)
    lot_id = await add_lot(db_session, pool_id)
    first_order = await add_buyer_order(db_session, lot_id, entry_id, status="OFFERED")
    await expect_error(
        db_session,
        "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, total_cents, "
        "breakdown) VALUES (:id, :lot, :entry, 'OFFERED', now(), 50000, CAST('{}' AS jsonb))",
        {"id": new_id(), "lot": lot_id, "entry": entry_id},
        sqlstate="23505",
    )
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'EXPIRED' WHERE id = :id"), {"id": first_order}
    )
    second_order = await add_buyer_order(db_session, lot_id, entry_id, status="OFFERED")
    paypal_order = await add_paypal_order(db_session, second_order)
    await expect_error(
        db_session,
        "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, intent, "
        "amount_cents, raw) VALUES (:id, :buyer, 1, :paypal, 'COMPLETED', 'AUTHORIZE', 50000, "
        "CAST('{}' AS jsonb))",
        {"id": new_id(), "buyer": second_order, "paypal": paypal_order},
        sqlstate="23505",
    )
    capture_id = await add_capture(db_session, second_order)
    await expect_error(
        db_session,
        "INSERT INTO paypal_captures (id, buyer_order_id, paypal_capture_id, status, amount_cents, "
        "final_capture, raw) VALUES (:id, :buyer, :capture, 'COMPLETED', 50000, true, "
        "CAST('{}' AS jsonb))",
        {"id": new_id(), "buyer": second_order, "capture": capture_id},
        sqlstate="23505",
    )
    await db_session.execute(
        text(
            "INSERT INTO paypal_refunds (id, buyer_order_id, paypal_capture_id, paypal_refund_id, seq, "
            "status, amount_cents, raw) VALUES (:id, :buyer, :capture, :refund, 1, 'COMPLETED', "
            "50000, CAST('{}' AS jsonb))"
        ),
        {
            "id": new_id(),
            "buyer": second_order,
            "capture": capture_id,
            "refund": f"REF-{uuid.uuid4()}",
        },
    )
    await add_ledger(db_session, lot_id, second_order)
    await expect_error(
        db_session,
        "INSERT INTO ledger_entries (id, lot_id, buyer_order_id, kind, amount_cents, paypal_ref, "
        "idempotency_key, source) SELECT :id, :lot, :buyer, 'CAPTURE_COMPLETED', 50000, 'CAP-2', "
        "idempotency_key, 'api' FROM ledger_entries LIMIT 1",
        {"id": new_id(), "lot": lot_id, "buyer": second_order},
        sqlstate="23505",
    )
    event_id = await add_webhook(db_session)
    await expect_error(
        db_session,
        "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body) "
        "VALUES (:id, :event, 'X', '{}')",
        {"id": new_id(), "event": event_id},
        sqlstate="23505",
    )


async def test_platform_unique_constraints(db_session: AsyncSession):
    dedupe = f"dedupe-{uuid.uuid4()}"
    insert_job = (
        "INSERT INTO jobs (id, kind, run_at, payload, dedupe_key) "
        "VALUES (:id, 'pool.open', now(), CAST('{}' AS jsonb), :dedupe)"
    )
    first_job = new_id()
    await db_session.execute(text(insert_job), {"id": first_job, "dedupe": dedupe})
    await expect_error(db_session, insert_job, {"id": new_id(), "dedupe": dedupe}, sqlstate="23505")
    await db_session.execute(
        text("UPDATE jobs SET status = 'DONE' WHERE id = :id"), {"id": first_job}
    )
    await db_session.execute(text(insert_job), {"id": new_id(), "dedupe": dedupe})

    merchant_id, _ = await add_merchant(db_session)
    prefix = f"fp{uuid.uuid4().hex[:6]}"
    insert_key = (
        "INSERT INTO merchant_api_keys (id, merchant_id, name, key_prefix, key_hash, scopes) "
        "VALUES (:id, :merchant, 'key', :prefix, :hash, '{lots:read}'::text[])"
    )
    await db_session.execute(
        text(insert_key), {"id": new_id(), "merchant": merchant_id, "prefix": prefix, "hash": HEX64}
    )
    await expect_error(
        db_session,
        insert_key,
        {"id": new_id(), "merchant": merchant_id, "prefix": prefix, "hash": HEX64},
        sqlstate="23505",
    )


async def test_shipment_rejects_captured_order_from_another_lot(db_session):
    pool = await add_pool(db_session)
    entry = await add_entry(db_session, pool)
    own_lot = await add_lot(db_session, pool, status="FUNDED")
    other_lot = await add_lot(db_session, pool, status="FUNDED", lot_index=1, lot_order=1)
    order = await add_buyer_order(db_session, other_lot, entry, status="CAPTURED")
    merchant, _ = await add_merchant(db_session)
    await expect_error(
        db_session,
        "INSERT INTO shipments (id,lot_id,buyer_order_id,merchant_id,carrier,"
        "tracking_number,shipped_at) "
        "VALUES (:id,:lot,:buyer,:merchant,'UPS','CROSS-LOT',now())",
        {"id": new_id(), "lot": own_lot, "buyer": order, "merchant": merchant},
        sqlstate="23514",
    )
