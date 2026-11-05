"""T03B01: pool join, signed receipts, withdrawal and the public signing key.

Every acceptance bullet from the task row is a named test here (the limiter and
the 200-parallel-joins tests live in their own files). HTTP tests run with
``RATE_LIMIT_ENABLED=false`` so the constraint outcomes, not the limiter, are
what the suite proves (config-and-errors.md §3, CR-3).
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import ConfirmedRequest, EntryReceipt, PoolEntry
from fairpool.db.models.enums import EntryStatus
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import commitment as commitment_hash
from fairpool.domain.hashing import sha256_hex, verify_ed25519
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.idempotency import FakeIdempotencyStore
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import signing_seed
from tests.identity_helpers import provision_buyer
from tests.integration.test_triggers import iso_in, utc_in
from tests.unit.test_settings import make_settings

SEED = base64.urlsafe_b64encode(b"receipt-signing-secret-32bytes!!").decode().rstrip("=")
PASSWORD = "a-secure-password"


def settings_for(**overrides: Any):
    return make_settings(rate_limit_enabled=False, receipt_signing_key=SEED, **overrides)


async def login(client: httpx.AsyncClient, email: str) -> str:
    await provision_buyer(
        client,
        email=email,
        password=PASSWORD,
        display_name="Buyer " + email[:8],
    )
    result = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    return str(result.json()["csrf_token"])


async def open_pool(
    db: AsyncSession,
    *,
    status: str = "OPEN",
    mode: str = "LIVE_SANDBOX",
    close_in: int = 3600,
    require_link: bool = False,
) -> uuid.UUID:
    pool_id = uuid.uuid4()
    admin = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
        ),
        {"id": admin, "email": f"admin-{pool_id}@example.test"},
    )
    template = {
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
    await db.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, created_by) "
            "VALUES (:id, CAST(:mode AS pool_mode), CAST(:status AS pool_status), 'Monitor pool', "
            "CAST(:template AS jsonb), CAST(:lot_plan AS jsonb), CAST(:timeline AS jsonb), "
            ":require_link, 'allocation_v1', :rules_hash, :created_by)"
        ),
        {
            "id": pool_id,
            "mode": mode,
            "status": status,
            "template": json.dumps(template),
            "lot_plan": json.dumps([]),
            "timeline": json.dumps(timeline),
            "require_link": require_link,
            "rules_hash": "a" * 64,
            "created_by": admin,
        },
    )
    return pool_id


async def manual_confirm(
    db: AsyncSession, user_id: uuid.UUID, pool_id: uuid.UUID, **overrides: Any
) -> uuid.UUID:
    payload: dict[str, Any] = {
        "delivery": {"region": "NY"},
        "required_by": "2026-11-30",
        "max_total_cents": 60000,
        "firm": [],
        "preferences": [],
    }
    payload.update(overrides)
    record = await ManualIntakeService(PostgresAuditLog()).confirm(
        db, user_id=user_id, pool_id=pool_id, payload=payload
    )
    return record.id


def join_service(**overrides: Any) -> JoinService:
    return JoinService(
        DbClock(),
        PostgresAuditLog(),
        PostgresIdempotencyStore(),
        signing_seed=signing_seed(SEED),
        dedupe_mode="two_keys",
        **overrides,
    )


@pytest.fixture
async def client(db_session: AsyncSession) -> httpx.AsyncClient:
    app = create_app(settings_for())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as http:
        yield http


def error_code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


async def entry_count(db: AsyncSession, pool_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            text("SELECT count(*) FROM pool_entries WHERE pool_id = :id"), {"id": pool_id}
        )
        or 0
    )


async def wipe_join_data(
    engine: AsyncEngine, pool_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> None:
    """Delete rows a committed service-level test left in the disposable DB.

    Audit rows are append-only by trigger and stay: they are part of the chain
    and reference nothing that must be re-asserted.
    """
    users = list(user_ids) or [uuid.uuid4()]
    user_in = text("DELETE FROM paypal_links WHERE user_id IN :u").bindparams(
        bindparam("u", expanding=True)
    )
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
        if user_ids:
            await conn.execute(user_in, {"u": users})
        await conn.execute(
            text("DELETE FROM idempotency_keys WHERE key LIKE :pattern"),
            {"pattern": f"entries_join:{pool_id}:%"},
        )
        await conn.execute(text("DELETE FROM lots WHERE pool_id = :p"), {"p": pool_id})
        await conn.execute(text("DELETE FROM pools WHERE id = :p"), {"p": pool_id})
        admin_email = f"admin-{pool_id}@example.test"
        await conn.execute(
            text(
                "DELETE FROM sessions WHERE user_id IN :u OR user_id IN "
                "(SELECT id FROM users WHERE email = :email)"
            ).bindparams(bindparam("u", expanding=True)),
            {"u": users, "email": admin_email},
        )
        await conn.execute(
            text("DELETE FROM users WHERE id IN :u OR email = :email").bindparams(
                bindparam("u", expanding=True)
            ),
            {"u": users, "email": admin_email},
        )


async def test_join_returns_201_with_a_verifiable_signed_receipt(
    client: httpx.AsyncClient, db_session: AsyncSession
):
    csrf = await login(client, "join-ok@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)

    response = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "k1", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["already_entered"] is False
    assert body["pool_status"] == "OPEN"
    receipt = body["receipt"]
    assert sorted(receipt) == ["payload", "request_hash", "salt_hex", "signature"]
    assert sorted(receipt["payload"]) == [
        "commitment",
        "entry_id",
        "pool_id",
        "received_at",
        "v",
    ]

    entry_id = uuid.UUID(body["entry_id"])
    entry = await db_session.scalar(select(PoolEntry).where(PoolEntry.id == entry_id))
    assert entry is not None and entry.status == EntryStatus.SUBMITTED
    assert entry.request_hash == receipt["request_hash"]
    assert entry.cap_cents == 60000 and entry.zone_id == "US-EAST"
    assert entry.submitted_via == "human" and entry.synthetic is False
    stored = await db_session.scalar(select(EntryReceipt).where(EntryReceipt.entry_id == entry_id))
    assert stored is not None

    # The buyer-side checks (fairness-and-hashing.md §6): the commitment
    # recomputes from the salt and request hash, and the signature verifies.
    assert receipt["payload"]["commitment"] == commitment_hash(
        str(pool_id), str(entry_id), receipt["request_hash"], receipt["salt_hex"]
    )
    keys = await client.get("/api/v1/public/keys")
    public_key = keys.json()["public_key"]
    assert verify_ed25519(receipt["payload"], receipt["signature"], public_key)
    assert (
        verify_ed25519(
            {**receipt["payload"], "commitment": "0" * 64}, receipt["signature"], public_key
        )
        is False
    )

    # Signed over the stored database timestamp (CR-3): the text in the payload
    # is exactly the stored received_at.
    assert receipt["payload"]["received_at"] == entry.received_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # The confirmed request is consumed exactly once by this join.
    cr = await db_session.scalar(select(ConfirmedRequest).where(ConfirmedRequest.id == cr_id))
    assert cr is not None and cr.consumed_by_entry_id == entry_id and cr.consumed_at is not None
    # The audit row exists for the join.
    actions = (
        (
            await db_session.execute(
                text("SELECT action FROM audit_log WHERE subject_id = :id"), {"id": str(entry_id)}
            )
        )
        .scalars()
        .all()
    )
    assert "entry.join" in actions


async def test_the_entry_read_returns_the_receipt_the_pool_signed(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CR-9: a buyer's own entry read carries the durable proof, not a fresh one.

    The receipt is the signed bytes the join issued. The route must not re-serialise the
    timestamp it signs over, so the read-back is byte-for-byte the join's receipt and
    still verifies against the published key: a buyer who reloads in another browser can
    still keep proof, and a downloaded copy still proves the same thing.
    """
    csrf = await login(client, "receipt-read@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "read-back", "X-CSRF-Token": csrf},
    )
    issued = joined.json()["receipt"]

    mine = await client.get(f"/api/v1/pools/{pool_id}/entries/me")
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["entry_id"] == joined.json()["entry_id"]
    assert body["entry_status"] == "SUBMITTED"
    assert body["receipt"] == issued
    public_key = (await client.get("/api/v1/public/keys")).json()["public_key"]
    assert verify_ed25519(body["receipt"]["payload"], body["receipt"]["signature"], public_key)

    # After a withdraw the proof survives: the row is the record that the entry existed.
    await client.delete(f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": csrf})
    after = (await client.get(f"/api/v1/pools/{pool_id}/entries/me")).json()
    assert after["entry_status"] == "WITHDRAWN" and after["receipt"] == issued

    # A second buyer's read is the same 404 as an unknown pool: no existence leak (I11).
    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        await login(other, "receipt-other@example.test")
        stranger = await other.get(f"/api/v1/pools/{pool_id}/entries/me")
    assert stranger.status_code == 404 and error_code(stranger) == "NOT_FOUND"


async def test_the_entry_read_reports_the_allocation_and_the_live_offer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CR-10: the read used to answer two hardcoded nulls.

    The seat and the offer are written here the way the allocation and open-checkout
    handlers write them; the route must show them through the same view helper the
    agent lane and ``entry_status`` use, or a buyer's own page would deny its own offer.
    """
    csrf = await login(client, "receipt-view@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "read-view", "X-CSRF-Token": csrf},
    )
    entry_id = uuid.UUID(joined.json()["entry_id"])

    lot_id, order_id = uuid.uuid4(), uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, payment_router, payment_mode, bid_open_at, bid_close_at) "
            "VALUES (:id, :pool, 'US-EAST', 0, 1, 2, 2, 'AWARDED'::lot_status, "
            "'fake'::payment_router, 'authorize_capture'::payment_mode, now(), now())"
        ),
        {"id": lot_id, "pool": pool_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, lot_id, "
            "status) VALUES (:id, :pool, :entry, 'US-EAST', 1, :rank_hash, :lot, "
            "'SEATED'::allocation_status)"
        ),
        {
            "id": uuid.uuid4(),
            "pool": pool_id,
            "entry": entry_id,
            "rank_hash": "b" * 64,
            "lot": lot_id,
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, "
            "total_cents, breakdown) VALUES (:id, :lot, :entry, 'OFFERED'::buyer_order_status, "
            "now() + interval '3 minutes', 50000, '{}'::jsonb)"
        ),
        {"id": order_id, "lot": lot_id, "entry": entry_id},
    )

    body = (await client.get(f"/api/v1/pools/{pool_id}/entries/me")).json()

    assert body["allocation"] == {
        "status": "SEATED",
        "zone_id": "US-EAST",
        "rank": 1,
        "lot_id": str(lot_id),
        "waitlist_position": None,
    }
    assert body["offer"]["buyer_order_id"] == str(order_id)
    assert body["offer"]["status"] == "OFFERED"
    assert body["offer"]["offer_expires_at"]
    assert body["receipt"] is not None


async def test_a_missing_receipt_row_reports_absent_rather_than_failing_the_read(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CR-9's one deliberate exception: the status read survives a broken receipt row.

    `receipt_for_entry` calls a missing `entry_receipts` row an integrity break, and for the
    join replay that just wrote it, it is. On a read whose only job is to tell a buyer their
    own state, the same break would blank the whole pool screen - so the receipt is reported
    as absent and never invented, and the state still arrives.
    """
    csrf = await login(client, "receipt-missing@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "missing-row", "X-CSRF-Token": csrf},
    )
    entry_id = joined.json()["entry_id"]

    # Fixture-only direct write: the row a corruption or a partial restore would lack.
    await db_session.execute(
        text("DELETE FROM entry_receipts WHERE entry_id = :id"), {"id": entry_id}
    )
    await db_session.flush()

    mine = await client.get(f"/api/v1/pools/{pool_id}/entries/me")
    assert mine.status_code == 200, mine.text
    body = mine.json()
    assert body["entry_id"] == entry_id
    assert body["entry_status"] == "SUBMITTED"
    assert body["receipt"] is None


async def test_idempotency_key_is_required_and_bounded(client: httpx.AsyncClient, db_session):
    csrf = await login(client, "idem-required@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)

    missing = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"X-CSRF-Token": csrf},
    )
    assert missing.status_code == 400 and error_code(missing) == "IDEMPOTENCY_KEY_REQUIRED"
    empty = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": ""},
    )
    assert empty.status_code == 400
    too_long = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "x" * 129},
    )
    assert too_long.status_code == 422 and error_code(too_long) == "VALIDATION_ERROR"
    assert await entry_count(db_session, pool_id) == 0


async def test_same_key_same_body_replays_the_original_response(
    client: httpx.AsyncClient, db_session: AsyncSession
):
    csrf = await login(client, "idem-replay@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)

    first = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "same", "X-CSRF-Token": csrf},
    )
    assert first.status_code == 201
    replay = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "same", "X-CSRF-Token": csrf},
    )
    # A replay returns the original response (api.md section 1), not a new entry.
    assert replay.status_code == 201 and replay.json() == first.json()
    assert await entry_count(db_session, pool_id) == 1


async def test_same_key_different_body_is_a_conflict(client, db_session):
    csrf = await login(client, "idem-conflict@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_a = await manual_confirm(db_session, user_id, pool_id)
    cr_b = await manual_confirm(db_session, user_id, pool_id, max_total_cents=55000)

    assert (
        await client.post(
            f"/api/v1/pools/{pool_id}/entries",
            json={"confirmed_request_id": str(cr_a)},
            headers={"Idempotency-Key": "dup", "X-CSRF-Token": csrf},
        )
    ).status_code == 201
    conflict = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_b)},
        headers={"Idempotency-Key": "dup", "X-CSRF-Token": csrf},
    )
    assert conflict.status_code == 409 and error_code(conflict) == "IDEMPOTENCY_CONFLICT"
    assert await entry_count(db_session, pool_id) == 1


async def test_inflight_key_without_a_stored_response_is_a_conflict(client, db_session):
    csrf = await login(client, "idem-inflight@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    # A previous attempt persisted the key but crashed before writing the
    # response: the store must answer IdemConflict (CR-3), never a second entry.
    await db_session.execute(
        text("INSERT INTO idempotency_keys (key, scope, request_hash) VALUES (:k, :s, :h)"),
        {
            "k": f"entries_join:{pool_id}:{user_id}:inflight",
            "s": f"entries_join:{pool_id}",
            "h": sha256_hex(f"confirmed_request:{cr_id}"),
        },
    )
    conflict = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "inflight", "X-CSRF-Token": csrf},
    )
    assert conflict.status_code == 409 and error_code(conflict) == "IDEMPOTENCY_CONFLICT"
    assert await entry_count(db_session, pool_id) == 0
    # A rejected attempt burns nothing: a fresh key still joins.
    ok = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "fresh", "X-CSRF-Token": csrf},
    )
    assert ok.status_code == 201


async def test_another_buyers_request_and_an_unknown_id_answer_alike(client, db_session):
    await login(client, "owner@example.test")
    victim_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, victim_id, pool_id)

    async with httpx.AsyncClient(
        transport=client._transport, base_url="https://api.test"
    ) as other_client:
        csrf = await login(other_client, "attacker@example.test")
        stolen = await other_client.post(
            f"/api/v1/pools/{pool_id}/entries",
            json={"confirmed_request_id": str(cr_id)},
            headers={"Idempotency-Key": "steal", "X-CSRF-Token": csrf},
        )
        unknown = await other_client.post(
            f"/api/v1/pools/{pool_id}/entries",
            json={"confirmed_request_id": str(uuid.uuid4())},
            headers={"Idempotency-Key": "unknown", "X-CSRF-Token": csrf},
        )
    assert stolen.status_code == 404 and unknown.status_code == 404
    # No existence hint: the bodies are identical except the request id.
    assert stolen.json()["error"]["code"] == unknown.json()["error"]["code"] == "NOT_FOUND"
    assert stolen.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert stolen.json()["error"]["details"] == unknown.json()["error"]["details"]
    assert await entry_count(db_session, pool_id) == 0


async def test_rules_hash_mismatch_is_409(client, db_session):
    csrf = await login(client, "rules@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    await db_session.execute(
        text("UPDATE pools SET rules_hash = :h WHERE id = :id"), {"h": "b" * 64, "id": pool_id}
    )
    mismatch = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "k", "X-CSRF-Token": csrf},
    )
    assert mismatch.status_code == 409 and error_code(mismatch) == "RULES_MISMATCH"
    assert await entry_count(db_session, pool_id) == 0


async def test_corrupted_canonical_bytes_are_an_integrity_error(client, db_session):
    csrf = await login(client, "integrity@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    # Simulate a stored record whose canonical bytes no longer match their hash.
    await db_session.execute(
        text(
            "UPDATE confirmed_requests SET canonical_request = "
            "jsonb_set(canonical_request, '{max_total_cents}', '59000') WHERE id = :id"
        ),
        {"id": cr_id},
    )
    response = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "k", "X-CSRF-Token": csrf},
    )
    assert response.status_code == 500 and error_code(response) == "INTEGRITY_ERROR"
    assert await entry_count(db_session, pool_id) == 0


async def test_pool_must_be_open_and_inside_the_window(client, db_session):
    csrf = await login(client, "window@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])

    published = await open_pool(db_session, status="PUBLISHED")
    cr_published = await manual_confirm(db_session, user_id, published)
    not_open = await client.post(
        f"/api/v1/pools/{published}/entries",
        json={"confirmed_request_id": str(cr_published)},
        headers={"Idempotency-Key": "k1", "X-CSRF-Token": csrf},
    )
    assert not_open.status_code == 409 and error_code(not_open) == "POOL_NOT_OPEN"

    expired = await open_pool(db_session, close_in=-60)
    cr_expired = await manual_confirm(db_session, user_id, expired)
    closed = await client.post(
        f"/api/v1/pools/{expired}/entries",
        json={"confirmed_request_id": str(cr_expired)},
        headers={"Idempotency-Key": "k2", "X-CSRF-Token": csrf},
    )
    assert closed.status_code == 409 and error_code(closed) == "POOL_CLOSED"
    assert await entry_count(db_session, published) == 0
    assert await entry_count(db_session, expired) == 0


async def test_cutoff_reads_the_wall_clock_after_the_lock(db_session: AsyncSession):
    """CR-3: a stale transaction-start now() must not admit a late join."""

    class SplitClock:
        def __init__(self, transaction_now: datetime, wall_now: datetime) -> None:
            self.transaction_now, self.wall_now = transaction_now, wall_now

        async def db_now(self, session: AsyncSession) -> datetime:
            return self.transaction_now

        async def db_wall_now(self, session: AsyncSession) -> datetime:
            return self.wall_now

    user = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'hash', 'Person')"
        ),
        {"id": user, "email": f"wall-{user}@example.test"},
    )
    pool_id = await open_pool(db_session, close_in=60)
    cr_id = await manual_confirm(db_session, user, pool_id)

    # The transaction started an hour before close; the wall clock read after
    # the pool lock is two hours past it. Admission is decided on the wall read.
    service_late = JoinService(
        SplitClock(transaction_now=utc_in(-3600), wall_now=utc_in(7200)),
        FakeAuditLog(),
        FakeIdempotencyStore(),
        signing_seed=signing_seed(SEED),
        dedupe_mode="two_keys",
    )
    with pytest.raises(ApplicationError) as refused:
        await service_late.join(
            db_session,
            pool_id=pool_id,
            user_id=user,
            confirmed_request_id=cr_id,
            idempotency_key="late-wall",
        )
    assert refused.value.code == "POOL_CLOSED"
    assert await entry_count(db_session, pool_id) == 0

    # The receipt signs the stored (transaction) timestamp, not the wall read.
    stored_now = utc_in(-5)
    service_ok = JoinService(
        SplitClock(transaction_now=stored_now, wall_now=utc_in(0)),
        FakeAuditLog(),
        FakeIdempotencyStore(),
        signing_seed=signing_seed(SEED),
        dedupe_mode="two_keys",
    )
    outcome = await service_ok.join(
        db_session,
        pool_id=pool_id,
        user_id=user,
        confirmed_request_id=cr_id,
        idempotency_key="stable-timestamp",
    )
    assert outcome.status_code == 201
    assert outcome.body["receipt"]["payload"]["received_at"] == stored_now.strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    entry = await db_session.scalar(
        select(PoolEntry).where(PoolEntry.id == uuid.UUID(outcome.body["entry_id"]))
    )
    assert entry is not None and entry.received_at == stored_now


async def test_consumed_request_replays_after_the_cutoff_and_never_reactivates(
    client: httpx.AsyncClient, db_session: AsyncSession
):
    csrf = await login(client, "replay@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "k", "X-CSRF-Token": csrf},
    )
    assert joined.status_code == 201
    entry_id = uuid.UUID(joined.json()["entry_id"])

    # Withdraw, then pass the cutoff: the replay still answers with the original
    # receipt and never reactivates the withdrawn entry or rewrites anything.
    withdrawn = await client.delete(
        f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": csrf}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["entry_status"] == "WITHDRAWN"
    await db_session.execute(
        text(
            "UPDATE pools SET status = 'CLOSED', timeline = jsonb_set(timeline, "
            "'{close_at}', to_jsonb(CAST(:past AS text))) WHERE id = :id"
        ),
        {"id": pool_id, "past": iso_in(-10)},
    )

    replay = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "after-close", "X-CSRF-Token": csrf},
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["entry_id"] == str(entry_id)
    assert body["already_entered"] is True
    assert body["receipt"] == joined.json()["receipt"]
    assert await entry_count(db_session, pool_id) == 1
    entry = await db_session.scalar(select(PoolEntry).where(PoolEntry.id == entry_id))
    assert entry is not None and entry.status == EntryStatus.WITHDRAWN
    assert entry.cap_cents == 60000


async def test_withdraw_is_owner_only_inside_the_open_window(client, db_session):
    owner_csrf = await login(client, "withdraw-owner@example.test")
    owner_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_id = await manual_confirm(db_session, owner_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "w", "X-CSRF-Token": owner_csrf},
    )
    entry_id = joined.json()["entry_id"]

    # Owner read before withdrawing.
    mine = await client.get(f"/api/v1/pools/{pool_id}/entries/me")
    assert mine.status_code == 200
    assert mine.json()["entry_id"] == entry_id and mine.json()["entry_status"] == "SUBMITTED"

    # A different user cannot withdraw someone else's entry.
    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        other_csrf = await login(other, "withdraw-other@example.test")
        stranger = await other.delete(
            f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": other_csrf}
        )
        assert stranger.status_code == 404 and error_code(stranger) == "NOT_FOUND"

    first = await client.delete(
        f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": owner_csrf}
    )
    assert first.status_code == 200
    assert first.json() == {"entry_id": entry_id, "entry_status": "WITHDRAWN"}
    # ES-03 happened exactly once; a repeat is a stable 200, not a new transition.
    again = await client.delete(
        f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": owner_csrf}
    )
    assert again.status_code == 200 and again.json()["entry_status"] == "WITHDRAWN"
    withdraw_rows = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE action='entry.withdraw' AND subject_id = :id"
            ),
            {"id": entry_id},
        )
    ).scalar()
    assert withdraw_rows == 1

    # Past the cutoff a withdrawal is refused (serialised like the close).
    reopened = await open_pool(db_session)
    cr_reopen = await manual_confirm(db_session, owner_id, reopened)
    reopen_join = await client.post(
        f"/api/v1/pools/{reopened}/entries",
        json={"confirmed_request_id": str(cr_reopen)},
        headers={"Idempotency-Key": "late-withdraw", "X-CSRF-Token": owner_csrf},
    )
    assert reopen_join.status_code == 201
    await db_session.execute(
        text(
            "UPDATE pools SET timeline = jsonb_set(timeline, '{close_at}', "
            "to_jsonb(CAST(:past AS text))) WHERE id = :id"
        ),
        {"id": reopened, "past": iso_in(-5)},
    )
    late = await client.delete(
        f"/api/v1/pools/{reopened}/entries/me", headers={"X-CSRF-Token": owner_csrf}
    )
    assert late.status_code == 409 and error_code(late) == "POOL_CLOSED"


async def test_withdraw_waits_behind_the_pool_lock_held_by_a_close(db_engine: AsyncEngine):
    """Withdraw serialises against pool.close under the same pool lock."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    user = uuid.uuid4()
    async with maker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :email, 'hash', 'Person')"
            ),
            {"id": user, "email": f"lock-{user}@example.test"},
        )
        pool_id = await open_pool(session)
        cr_id = await manual_confirm(session, user, pool_id)
    service = join_service()
    async with maker() as session, session.begin():
        outcome = await service.join(
            session,
            pool_id=pool_id,
            user_id=user,
            confirmed_request_id=cr_id,
            idempotency_key="p",
        )
    assert outcome.status_code == 201

    # The blocker stands in for pool.close, which takes the same pool row lock.
    blocker_conn = await db_engine.connect()
    blocker_tx = await blocker_conn.begin()
    await blocker_conn.execute(
        text("SELECT id FROM pools WHERE id = :id FOR UPDATE"), {"id": pool_id}
    )
    worker = maker()
    try:
        task = asyncio.create_task(service.withdraw(worker, pool_id=pool_id, user_id=user))
        await asyncio.sleep(0.5)
        assert not task.done()  # blocked behind the pool lock, as pool.close holds it
        await blocker_tx.commit()
        result = await task
    finally:
        await worker.commit()
        await worker.close()
        if blocker_tx.is_active:
            await blocker_tx.rollback()
        await blocker_conn.close()
    assert result.body["entry_status"] == "WITHDRAWN"
    async with maker() as session:
        status = await session.scalar(
            text("SELECT status FROM pool_entries WHERE pool_id = :p"), {"p": pool_id}
        )
    assert str(status) == "WITHDRAWN"
    await wipe_join_data(db_engine, pool_id, [user])


async def test_paypal_link_requirements_and_account_dedupe(client, db_session):
    csrf = await login(client, "linked@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session, require_link=True)
    cr_id = await manual_confirm(db_session, user_id, pool_id)

    denied = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "nolog", "X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403 and error_code(denied) == "PAYPAL_LINK_REQUIRED"

    account = f"ACCOUNT-{uuid.uuid4()}"
    await db_session.execute(
        text(
            "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
            "VALUES (:id, :user, :account)"
        ),
        {"id": uuid.uuid4(), "user": user_id, "account": account},
    )
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "yeslog", "X-CSRF-Token": csrf},
    )
    assert joined.status_code == 201
    entry = await db_session.scalar(
        select(PoolEntry).where(PoolEntry.id == uuid.UUID(joined.json()["entry_id"]))
    )
    assert entry is not None and entry.paypal_account_key == account

    # FR-ID-03: a second buyer on the same linked account gets the winner's
    # receipt (200), not a second entry (the constraint is the last word).
    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as twin:
        twin_csrf = await login(twin, "twin@example.test")
        twin_id = uuid.UUID((await twin.get("/api/v1/me")).json()["user_id"])
        await db_session.execute(
            text("UPDATE paypal_links SET revoked_at = now() WHERE user_id = :u"), {"u": user_id}
        )
        await db_session.execute(
            text(
                "INSERT INTO paypal_links (id, user_id, paypal_account_key) "
                "VALUES (:id, :user, :account)"
            ),
            {"id": uuid.uuid4(), "user": twin_id, "account": account},
        )
        twin_cr = await manual_confirm(db_session, twin_id, pool_id)
        second = await twin.post(
            f"/api/v1/pools/{pool_id}/entries",
            json={"confirmed_request_id": str(twin_cr)},
            headers={"Idempotency-Key": "twin", "X-CSRF-Token": twin_csrf},
        )
        assert second.status_code == 200 and second.json()["already_entered"] is True
        assert second.json()["receipt"] == joined.json()["receipt"]
    assert await entry_count(db_session, pool_id) == 1


async def test_second_request_maps_the_swallowed_constraint_violation_to_the_winner(
    client: httpx.AsyncClient, db_session: AsyncSession
):
    """The duplicate-key violation is swallowed via a savepoint and the rest of
    the transaction stays usable (config-and-errors.md §3)."""
    csrf = await login(client, "swallow@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session)
    cr_one = await manual_confirm(db_session, user_id, pool_id)
    first = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_one)},
        headers={"Idempotency-Key": "one", "X-CSRF-Token": csrf},
    )
    assert first.status_code == 201

    cr_two = await manual_confirm(db_session, user_id, pool_id, max_total_cents=55000)
    second = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_two)},
        headers={"Idempotency-Key": "two", "X-CSRF-Token": csrf},
    )
    assert second.status_code == 200 and second.json()["already_entered"] is True
    assert second.json()["receipt"] == first.json()["receipt"]
    assert await entry_count(db_session, pool_id) == 1

    # The transaction stayed usable after the swallowed violation: the new key
    # completed, so a replay of it returns this stored response...
    replay = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_two)},
        headers={"Idempotency-Key": "two", "X-CSRF-Token": csrf},
    )
    assert replay.status_code == 200 and replay.json() == second.json()
    # ...and the cap and request of the winning entry are untouched.
    entry = await db_session.scalar(
        select(PoolEntry).where(PoolEntry.id == uuid.UUID(first.json()["entry_id"]))
    )
    assert entry is not None and entry.cap_cents == 60000
    assert entry.canonical_request["max_total_cents"] == 60000


async def test_synthetic_is_derived_from_the_pool_mode_not_the_client(
    client: httpx.AsyncClient, db_session: AsyncSession
):
    csrf = await login(client, "simmode@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await open_pool(db_session, mode="SIMULATION")
    cr_id = await manual_confirm(db_session, user_id, pool_id)
    joined = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(cr_id)},
        headers={"Idempotency-Key": "sim", "X-CSRF-Token": csrf},
    )
    assert joined.status_code == 201
    entry = await db_session.scalar(
        select(PoolEntry).where(PoolEntry.id == uuid.UUID(joined.json()["entry_id"]))
    )
    assert entry is not None and entry.synthetic is True


async def test_session_and_csrf_are_enforced(client: httpx.AsyncClient, db_session):
    pool_id = await open_pool(db_session)
    anonymous = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(uuid.uuid4())},
        headers={"Idempotency-Key": "k"},
    )
    assert anonymous.status_code == 401
    csrf = await login(client, "csrf@example.test")
    no_csrf = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(uuid.uuid4())},
        headers={"Idempotency-Key": "k"},
    )
    assert no_csrf.status_code == 403
    assert await entry_count(db_session, pool_id) == 0
    assert csrf


async def test_public_keys_exposes_only_the_derived_public_key(client: httpx.AsyncClient):
    response = await client.get("/api/v1/public/keys")
    assert response.status_code == 200
    body = response.json()
    assert sorted(body) == ["algorithm", "public_key"]
    assert body["algorithm"] == "ed25519"
    raw = base64.urlsafe_b64decode(body["public_key"] + "=" * (-len(body["public_key"]) % 4))
    assert len(raw) == 32
    assert body["public_key"] == base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    # The private seed never appears in the payload (I14).
    assert SEED not in response.text
    assert signing_seed(SEED).hex() not in response.text


async def test_manual_confirmation_binds_user_pool_and_frozen_rules_hash(
    db_session: AsyncSession,
):
    user = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'hash', 'Person')"
        ),
        {"id": user, "email": f"manual-{user}@example.test"},
    )
    pool_id = await open_pool(db_session)
    record = await ManualIntakeService(PostgresAuditLog()).confirm(
        db_session,
        user_id=user,
        pool_id=pool_id,
        payload={
            "delivery": {"region": "NJ"},
            "required_by": "2026-12-01",
            "max_total_cents": 45000,
            "firm": [],
            "preferences": [],
        },
    )
    assert record.user_id == user
    assert record.pool_id == pool_id
    assert record.rules_hash == "a" * 64
    assert record.cap_cents == 45000
    assert record.zone_id == "US-EAST"
    assert record.consumed_at is None and record.consumed_by_entry_id is None
    stored = await db_session.scalar(
        select(func.count()).select_from(ConfirmedRequest).where(ConfirmedRequest.user_id == user)
    )
    assert stored == 1
