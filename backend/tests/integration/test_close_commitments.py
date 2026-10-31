"""T03B04: ``pool.close`` - the eligibility sweep, commitments and the immutable snapshot.

Every acceptance bullet in the task row is a named test here. The Merkle outcome is
proved against ``docs/contracts/vectors/fairness_v1.json`` (the entries of that file
become real entries of a real pool), never against an expectation recomputed by hand.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import EntryReceipt, Pool
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import EMPTY_MERKLE_ROOT
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.fakes.notifier import FakeNotifier
from fairpool.fakes.vault import FakePaymentVaultProvider
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, key_from_config_value
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.pools.close import PoolCloseService
from fairpool.modules.pools.vault import VaultService
from tests.integration.test_join_receipts import (
    join_service,
    login,
    manual_confirm,
    settings_for,
)
from tests.integration.test_triggers import iso_in, utc_in
from tests.unit.test_settings import vault_key

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "docs/contracts/vectors/fairness_v1.json").read_text("utf-8"))

TEMPLATE: dict[str, Any] = {
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
TIMELINE: dict[str, Any] = {
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


async def insert_pool(
    db: AsyncSession,
    *,
    pool_id: uuid.UUID | None = None,
    status: str = "OPEN",
    close_in: int = 3600,
    require_link: bool = False,
    template: dict[str, Any] | None = None,
) -> uuid.UUID:
    pool_id = pool_id or uuid.uuid4()
    admin = uuid.uuid4()
    timeline = {**TIMELINE, "close_at": iso_in(close_in)}
    await db.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
        ),
        {"id": admin, "email": f"admin-{pool_id}@example.test"},
    )
    await db.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', CAST(:status AS pool_status), 'Monitor pool', "
            "CAST(:template AS jsonb), '[]'::jsonb, CAST(:timeline AS jsonb), "
            ":require_link, 'allocation_v1', :rules_hash, :created_by)"
        ),
        {
            "id": pool_id,
            "status": status,
            "template": json.dumps(template or TEMPLATE),
            "timeline": json.dumps(timeline),
            "require_link": require_link,
            # A DRAFT pool has no frozen rules document yet: publish sets it.
            "rules_hash": None if status == "DRAFT" else "a" * 64,
            "created_by": admin,
        },
    )
    return pool_id


async def add_buyer(db: AsyncSession, tag: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'hash', :name)"
        ),
        {"id": user_id, "email": f"{tag}-{user_id}@example.test", "name": f"Buyer {tag}"},
    )
    return user_id


async def joined_entry(
    db: AsyncSession, pool_id: uuid.UUID, *, tag: str, cap: int = 60000, link: bool = False
) -> uuid.UUID:
    """A real SUBMITTED entry with a real signed receipt, through the join lane."""
    user_id = await add_buyer(db, tag)
    if link:
        await db.execute(
            text("INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:id, :u, :k)"),
            {"id": uuid.uuid4(), "u": user_id, "k": f"ACCOUNT-{user_id}"},
        )
    confirmed = await manual_confirm(db, user_id, pool_id, max_total_cents=cap)
    outcome = await join_service().join(
        db,
        pool_id=pool_id,
        user_id=user_id,
        confirmed_request_id=confirmed,
        idempotency_key=f"join-{tag}",
    )
    return uuid.UUID(str(outcome.body["entry_id"]))


def vault_service(provider: FakePaymentVaultProvider | None = None) -> VaultService:
    """The fake-provider vault: the only way an ACTIVE permission exists in Phase 3."""
    return VaultService(
        DbClock(),
        FakeAuditLog(),
        AesGcmCipher(key_from_config_value(vault_key())),
        provider or FakePaymentVaultProvider(),
        consent_version="v1",
        setup_ttl_s=900,
        # DEP-5: the real save path is off; the injected fake is what tests use.
        real_save_enabled=True,
    )


async def make_active(db: AsyncSession, entry_id: uuid.UUID) -> None:
    service = vault_service()
    redirect = await service.start(db, entry_id=entry_id)
    await service.complete(db, entry_id=entry_id, setup_token_id=redirect.setup_token_id)


def close_service(
    db: AsyncSession,
    *,
    payment_mode: str = "authorize_capture",
    jobs: FakeJobQueue | None = None,
    audit: FakeAuditLog | None = None,
    notifier: FakeNotifier | None = None,
) -> tuple[PoolCloseService, FakeJobQueue, FakeAuditLog, FakeNotifier]:
    queue = jobs or FakeJobQueue()
    chain = audit or FakeAuditLog()
    sender = notifier or FakeNotifier()
    return (
        PoolCloseService(DbClock(), chain, queue, sender, payment_mode=payment_mode),
        queue,
        chain,
        sender,
    )


async def run_close(db: AsyncSession, pool_id: uuid.UUID, **kwargs: Any) -> tuple[Any, ...]:
    service, queue, chain, sender = close_service(db, **kwargs)
    await service.close(db, {"pool_id": str(pool_id)})
    return service, queue, chain, sender


async def set_close_in_the_past(db: AsyncSession, pool_id: uuid.UUID) -> None:
    await db.execute(
        text(
            "UPDATE pools SET timeline = jsonb_set(timeline, '{close_at}', "
            "to_jsonb(CAST(:t AS text))) WHERE id = :id"
        ),
        {"id": pool_id, "t": iso_in(-5)},
    )


async def snapshot_of(db: AsyncSession, pool_id: uuid.UUID) -> tuple[Any, ...]:
    row = (
        await db.execute(
            text("SELECT entries_root, entries_count, closed_at FROM pools WHERE id = :i"),
            {"i": pool_id},
        )
    ).first()
    return (str(row[0]) if row[0] is not None else None, row[1], row[2])


async def state_of(db: AsyncSession, pool_id: uuid.UUID) -> tuple[Any, ...]:
    row = (
        await db.execute(
            text("SELECT status, entries_root, entries_count, closed_at FROM pools WHERE id = :i"),
            {"i": pool_id},
        )
    ).first()
    return (str(row[0]), str(row[1]) if row[1] is not None else None, row[2], row[3])


async def entry_status(db: AsyncSession, entry_id: uuid.UUID) -> tuple[str, str | None]:
    row = (
        await db.execute(
            text("SELECT status, reject_reason FROM pool_entries WHERE id = :id"), {"id": entry_id}
        )
    ).first()
    return str(row[0]), row[1]


# --------------------------------------------------------------------- vectors


async def test_close_builds_the_vector_merkle_root_over_the_vector_entries(
    db_session: AsyncSession,
) -> None:
    """The published root is ``fairness_v1.json``'s Merkle root, byte for byte."""
    pool_id = uuid.UUID(VECTORS["entries"][0]["canonical_request"]["pool_id"])
    await insert_pool(db_session, pool_id=pool_id)
    for item in VECTORS["entries"]:
        entry_id = uuid.UUID(item["entry_id"])
        request = item["canonical_request"]
        await db_session.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:id, :e, 'h', 'n')"
            ),
            {"id": entry_id, "e": f"vector-{entry_id}@example.test"},
        )
        await db_session.execute(
            text(
                "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, "
                "cap_cents, zone_id, status, submitted_via) VALUES (:id, :pool, :user, "
                "CAST(:request AS jsonb), :hash, :cap, 'US-EAST', 'SUBMITTED', 'human')"
            ),
            {
                "id": entry_id,
                "pool": pool_id,
                "user": entry_id,
                "request": json.dumps(request),
                "hash": item["request_hash"],
                "cap": request["max_total_cents"],
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO entry_receipts (entry_id, commitment, salt, signature, signed_at) "
                "VALUES (:entry, :commitment, :salt, 'signature', now())"
            ),
            {
                "entry": entry_id,
                "commitment": item["commitment"],
                "salt": item["salt_hex"],
            },
        )
    await set_close_in_the_past(db_session, pool_id)

    _, _, _, _ = await run_close(db_session, pool_id)

    pool = await db_session.scalar(select(Pool).where(Pool.id == pool_id))
    assert pool is not None
    assert pool.entries_root == VECTORS["merkle_root"]
    assert pool.entries_count == len(VECTORS["entries"])
    assert str(pool.status) == "CLOSED"

    published = sorted(
        str(row)
        for row in (
            await db_session.execute(
                select(EntryReceipt.commitment).where(
                    EntryReceipt.entry_id.in_(
                        [uuid.UUID(e["entry_id"]) for e in VECTORS["entries"]]
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert published == VECTORS["sorted_commitments"]
    assert await db_session.scalar(
        text("SELECT count(*) FROM pool_entries WHERE status = 'ELIGIBLE' AND pool_id = :p"),
        {"p": pool_id},
    ) == len(VECTORS["entries"])


async def test_empty_pool_closes_to_the_empty_root(db_session: AsyncSession) -> None:
    pool_id = await insert_pool(db_session)
    await set_close_in_the_past(db_session, pool_id)
    await run_close(db_session, pool_id)
    pool = await db_session.scalar(select(Pool).where(Pool.id == pool_id))
    assert pool is not None
    assert pool.entries_root == EMPTY_MERKLE_ROOT
    assert pool.entries_count == 0


# ------------------------------------------------------------------ the sweep


async def test_vault_charge_requires_an_active_permission_else_vault_missing(
    db_session: AsyncSession,
) -> None:
    """CR-3 note 3: consent plus ACTIVE at close, never a present-but-unsaved entry."""
    pool_id = await insert_pool(db_session)
    saved = await joined_entry(db_session, pool_id, tag="saved")
    unsaved = await joined_entry(db_session, pool_id, tag="unsaved")
    await make_active(db_session, saved)
    await set_close_in_the_past(db_session, pool_id)

    _, _, _, sender = await run_close(db_session, pool_id, payment_mode="vault_charge")

    assert await entry_status(db_session, saved) == ("ELIGIBLE", None)
    assert await entry_status(db_session, unsaved) == ("REJECTED", "VAULT_MISSING")
    # ES-02 carries notify; ES-01 does not (state-machines.md).
    rejected_user = await db_session.scalar(
        text("SELECT user_id FROM pool_entries WHERE id = :i"), {"i": unsaved}
    )
    assert [call.user_id for call in sender.calls] == [rejected_user]
    assert [call.kind for call in sender.calls] == ["entry.rejected"]
    assert sender.calls[0].payload["reason"] == "VAULT_MISSING"


async def test_a_permission_that_is_not_active_or_mismatched_cap_is_vault_missing(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    pending = await joined_entry(db_session, pool_id, tag="pending")
    deleted = await joined_entry(db_session, pool_id, tag="deleted")
    await make_active(db_session, pending)
    await make_active(db_session, deleted)
    await db_session.execute(
        text(
            "UPDATE vault_tokens SET status = 'DELETED'::vault_status, deleted_at = now(), "
            "token_ciphertext = NULL, token_nonce = NULL WHERE entry_id = :e"
        ),
        {"e": deleted},
    )
    await db_session.execute(
        text("UPDATE vault_tokens SET status = 'SETUP_PENDING'::vault_status WHERE entry_id = :e"),
        {"e": pending},
    )
    await set_close_in_the_past(db_session, pool_id)

    await run_close(db_session, pool_id, payment_mode="vault_charge")

    assert await entry_status(db_session, pending) == ("REJECTED", "VAULT_MISSING")
    assert await entry_status(db_session, deleted) == ("REJECTED", "VAULT_MISSING")


async def test_authorize_capture_mode_needs_no_permission(db_session: AsyncSession) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="fallback")
    await set_close_in_the_past(db_session, pool_id)
    await run_close(db_session, pool_id, payment_mode="authorize_capture")
    assert await entry_status(db_session, entry_id) == ("ELIGIBLE", None)


async def test_revoked_link_rejects_link_inactive(db_session: AsyncSession) -> None:
    pool_id = await insert_pool(db_session, require_link=True)
    kept = await joined_entry(db_session, pool_id, tag="kept", link=True)
    revoked = await joined_entry(db_session, pool_id, tag="revoked", link=True)
    await db_session.execute(
        text(
            "UPDATE paypal_links SET revoked_at = now() WHERE user_id = ("
            "SELECT user_id FROM pool_entries WHERE id = :e)"
        ),
        {"e": revoked},
    )
    await set_close_in_the_past(db_session, pool_id)

    await run_close(db_session, pool_id)

    assert await entry_status(db_session, kept) == ("ELIGIBLE", None)
    assert await entry_status(db_session, revoked) == ("REJECTED", "LINK_INACTIVE")


async def test_a_request_the_frozen_rules_no_longer_admit_rejects_request_invalid(
    db_session: AsyncSession,
) -> None:
    """ES-02 "request still valid": the bytes still hash, the rules moved under them."""
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="region")
    await db_session.execute(
        text(
            "UPDATE pools SET template = jsonb_set(template, '{zones,0,regions}', "
            "CAST(:regions AS jsonb)) WHERE id = :id"
        ),
        {"id": pool_id, "regions": json.dumps(["NJ", "PA"])},
    )
    await set_close_in_the_past(db_session, pool_id)

    await run_close(db_session, pool_id)

    assert await entry_status(db_session, entry_id) == ("REJECTED", "REQUEST_INVALID")


async def test_withdrawn_entries_stay_withdrawn_and_get_no_commitment(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    staying = await joined_entry(db_session, pool_id, tag="staying")
    gone = await joined_entry(db_session, pool_id, tag="gone")
    user_id = await db_session.scalar(
        text("SELECT user_id FROM pool_entries WHERE id = :i"), {"i": gone}
    )
    await join_service().withdraw(db_session, pool_id=pool_id, user_id=user_id)
    await set_close_in_the_past(db_session, pool_id)

    _, _, chain, _ = await run_close(db_session, pool_id)

    assert await entry_status(db_session, gone) == ("WITHDRAWN", None)
    assert await entry_status(db_session, staying) == ("ELIGIBLE", None)
    # Withdrawn rows never reach ES-01 or ES-02: the sweep touched one entry only.
    assert [row["row"]["action"] for row in chain.rows].count("entry.eligible") == 1
    assert "entry.withdrawn" not in [row["row"]["action"] for row in chain.rows]
    pool = await db_session.scalar(select(Pool).where(Pool.id == pool_id))
    assert pool is not None and pool.entries_count == 1


# ------------------------------------------------------------- integrity stops


async def expect_close_error(
    db: AsyncSession, pool_id: uuid.UUID, code: str, **kwargs: Any
) -> None:
    service, _, _, _ = close_service(db, **kwargs)
    before = await state_of(db, pool_id)
    with pytest.raises(ApplicationError) as raised:
        async with db.begin_nested():
            await service.close(db, {"pool_id": str(pool_id)})
    assert raised.value.code == code
    after = await state_of(db, pool_id)
    # One transaction, so the savepoint rollback leaves no partial close behind.
    assert after == before


async def test_a_missing_receipt_is_an_integrity_error_never_an_omission(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="noreceipt")
    await db_session.execute(
        text("DELETE FROM entry_receipts WHERE entry_id = :e"), {"e": entry_id}
    )
    await set_close_in_the_past(db_session, pool_id)

    await expect_close_error(db_session, pool_id, "INTEGRITY_ERROR")
    assert await entry_status(db_session, entry_id) == ("SUBMITTED", None)


async def test_a_stored_commitment_that_no_longer_matches_is_integrity_error(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="tampered")
    await db_session.execute(
        text("UPDATE entry_receipts SET commitment = :h WHERE entry_id = :e"),
        {"e": entry_id, "h": "0" * 64},
    )
    await set_close_in_the_past(db_session, pool_id)

    await expect_close_error(db_session, pool_id, "INTEGRITY_ERROR")


async def test_canonical_bytes_that_no_longer_match_their_hash_are_integrity_error(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="rewritten")
    await db_session.execute(
        text(
            "UPDATE pool_entries SET canonical_request = jsonb_set(canonical_request, "
            "'{max_total_cents}', '59000') WHERE id = :e"
        ),
        {"e": entry_id},
    )
    await set_close_in_the_past(db_session, pool_id)

    await expect_close_error(db_session, pool_id, "INTEGRITY_ERROR")
    assert await entry_status(db_session, entry_id) == ("SUBMITTED", None)


# ------------------------------------------------- deadlines, catch-up, replay


async def test_overdue_published_pool_catches_up_through_ps02_then_ps03(
    db_session: AsyncSession,
) -> None:
    """CR-3 note 2: the whitelist in order, never a direct status write."""
    pool_id = await insert_pool(db_session, status="PUBLISHED")
    await set_close_in_the_past(db_session, pool_id)

    _, _, chain, _ = await run_close(db_session, pool_id)

    status = await db_session.scalar(text("SELECT status FROM pools WHERE id = :i"), {"i": pool_id})
    assert str(status) == "CLOSED"
    assert [row["row"]["action"] for row in chain.rows][:2] == ["pool.open", "pool.closed"]
    assert chain.rows[0]["row"]["payload"] == {
        "from": "PUBLISHED",
        "to": "OPEN",
        "rules_hash": "a" * 64,
    }


class SplitClock:
    """A transaction that started before the deadline and waited on the lock."""

    def __init__(self, transaction_now: datetime, wall_now: datetime) -> None:
        self.transaction_now, self.wall_now = transaction_now, wall_now

    async def db_now(self, session: AsyncSession) -> datetime:
        return self.transaction_now

    async def db_wall_now(self, session: AsyncSession) -> datetime:
        return self.wall_now


async def test_close_decides_on_the_wall_clock_read_after_the_lock(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session, close_in=60)
    service, _, chain, _ = close_service(db_session)
    service.clock = SplitClock(transaction_now=utc_in(7200), wall_now=utc_in(-30))
    await service.close(db_session, {"pool_id": str(pool_id)})
    # The stale transaction clock is past close_at; the wall read is not, so PS-03
    # has no guard and nothing is written (CR-3 note 1).
    pool = await db_session.scalar(select(Pool).where(Pool.id == pool_id))
    assert pool is not None and pool.entries_root is None and str(pool.status) == "OPEN"
    assert chain.rows == []

    # Now the same job with a wall clock past the deadline closes it.
    service.clock = SplitClock(transaction_now=utc_in(-7200), wall_now=utc_in(120))
    await service.close(db_session, {"pool_id": str(pool_id)})
    pool = await db_session.scalar(select(Pool).where(Pool.id == pool_id))
    assert pool is not None and str(pool.status) == "CLOSED"
    assert pool.entries_root is not None


async def test_replay_returns_the_same_snapshot_and_duplicates_no_effect(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    kept = await joined_entry(db_session, pool_id, tag="kept")
    second = await joined_entry(db_session, pool_id, tag="second")
    await set_close_in_the_past(db_session, pool_id)

    service, queue, chain, sender = close_service(db_session)
    await service.close(db_session, {"pool_id": str(pool_id)})
    first = await snapshot_of(db_session, pool_id)
    audit_rows = len(chain.rows)
    notified = len(sender.calls)
    seeds = queue.calls.count("enqueue:pool.seed")
    assert first[0] is not None and seeds == 1
    assert audit_rows > 0 and notified == 0

    await service.close(db_session, {"pool_id": str(pool_id)})

    again = await snapshot_of(db_session, pool_id)
    assert again == first
    assert len(chain.rows) == audit_rows
    assert len(sender.calls) == notified
    assert queue.calls.count("enqueue:pool.seed") == 1
    assert await entry_status(db_session, kept) == ("ELIGIBLE", None)
    assert await entry_status(db_session, second) == ("ELIGIBLE", None)


async def test_seed_is_enqueued_once_with_the_pool_concurrency_key(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    await set_close_in_the_past(db_session, pool_id)
    _, queue, _, _ = await run_close(db_session, pool_id)
    seeds = [job for job in queue.jobs if job.kind == "pool.seed"]
    assert len(seeds) == 1
    assert seeds[0].payload == {"pool_id": str(pool_id)}
    assert seeds[0].concurrency_key == f"pool:{pool_id}"


# ------------------------------------------------------------------- late join


@pytest.fixture
async def client(db_session: AsyncSession) -> httpx.AsyncClient:
    app = create_app(settings_for())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.test") as http:
        yield http


async def test_a_late_join_cannot_follow_a_late_close(client: httpx.AsyncClient, db_session):
    """Even when the job runs late, the window is closed twice over: the status,
    the wall-clock guard and the ``pool_entries`` insert trigger."""
    csrf = await login(client, "late-close@example.test")
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await insert_pool(db_session)
    confirmed = await manual_confirm(db_session, user_id, pool_id)
    await set_close_in_the_past(db_session, pool_id)
    await run_close(db_session, pool_id)

    late = await client.post(
        f"/api/v1/pools/{pool_id}/entries",
        json={"confirmed_request_id": str(confirmed)},
        headers={"Idempotency-Key": "late", "X-CSRF-Token": csrf},
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] in {"POOL_NOT_OPEN", "POOL_CLOSED"}

    # The trigger is the last word even for a writer that bypasses the API.
    with pytest.raises(Exception) as refused:
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, "
                    "request_hash, cap_cents, zone_id, submitted_via) "
                    "VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, 60000, "
                    "'US-EAST', 'human')"
                ),
                {
                    "id": uuid.uuid4(),
                    "pool": pool_id,
                    "user": user_id,
                    "request": json.dumps(
                        {
                            "v": 1,
                            "pool_id": str(pool_id),
                            "product_key": "monitor-27-4k",
                            "variant": "black",
                            "condition": "NEW",
                            "quantity": 1,
                            "currency": "USD",
                            "delivery": {"zone_id": "US-EAST", "region": "NY", "country": "US"},
                            "required_by": "2026-11-30",
                            "max_total_cents": 60000,
                            "firm": [],
                            "preferences": [],
                        }
                    ),
                    "hash": "b" * 64,
                },
            )
    assert "POOL_CLOSED" in str(refused.value) or "POOL_NOT_OPEN" in str(refused.value)


# ------------------------------------------------------------- public snapshot


async def test_public_audit_publishes_the_close_subset_and_nothing_personal(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    pool_id = await insert_pool(db_session)
    kept = await joined_entry(db_session, pool_id, tag="pub")
    gone = await joined_entry(db_session, pool_id, tag="gone2")
    await set_close_in_the_past(db_session, pool_id)
    # The Postgres audit chain is what the checkpoint list publishes.
    pg_service = PoolCloseService(
        DbClock(),
        PostgresAuditLog(),
        PostgresJobQueue(),
        FakeNotifier(),
        payment_mode="authorize_capture",
    )
    await pg_service.close(db_session, {"pool_id": str(pool_id)})

    response = await client.get(f"/api/v1/public/pools/{pool_id}/audit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body) == sorted(
        [
            "rules_hash",
            "rules_document",
            "pool_status",
            "entries_root",
            "entries_count",
            "commitments",
            "audit_checkpoints",
            "beacon",
            "seed_hex",
            "seed_is_demo",
            "lots",
        ]
    )
    assert body["rules_hash"] == "a" * 64
    assert body["pool_status"] == "CLOSED"
    assert body["entries_count"] == 2
    assert body["entries_root"] == response.json()["entries_root"]
    assert body["commitments"] == sorted(body["commitments"])
    assert len(body["commitments"]) == 2
    receipt = await db_session.scalar(select(EntryReceipt).where(EntryReceipt.entry_id == kept))
    assert receipt is not None and str(receipt.commitment) in body["commitments"]
    # Phase 4 fields are absent, never fabricated (api.md "Public audit").
    assert body["beacon"] is None
    assert body["seed_hex"] is None
    assert body["seed_is_demo"] is False
    assert body["lots"] == []
    actions = [row["action"] for row in body["audit_checkpoints"]]
    assert "pool.closed" in actions and "pool.close.snapshot" in actions
    for checkpoint in body["audit_checkpoints"]:
        assert checkpoint["hash"] != "" and set(checkpoint["hash"]) <= set("0123456789abcdef")

    # No personal data, no salts, no caps on this public surface (FR-SL-06, I13).
    salts = (
        (
            await db_session.execute(
                text(
                    "SELECT salt FROM entry_receipts r JOIN pool_entries e ON e.id = r.entry_id "
                    "WHERE e.pool_id = :p"
                ),
                {"p": pool_id},
            )
        )
        .scalars()
        .all()
    )
    assert len(salts) == 2
    for salt in salts:
        assert str(salt) not in response.text
    assert "60000" not in response.text
    assert "max_total_cents" not in response.text
    for user in (kept, gone):
        assert str(user) not in response.text
    emails = (
        (
            await db_session.execute(
                text(
                    "SELECT email FROM users WHERE id IN (SELECT user_id FROM pool_entries "
                    "WHERE pool_id = :p)"
                ),
                {"p": pool_id},
            )
        )
        .scalars()
        .all()
    )
    for email in emails:
        assert str(email) not in response.text


async def test_public_audit_withholds_the_list_until_the_pool_closes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    pool_id = await insert_pool(db_session)
    await joined_entry(db_session, pool_id, tag="openpool")
    body = (await client.get(f"/api/v1/public/pools/{pool_id}/audit")).json()
    assert body["pool_status"] == "OPEN"
    assert body["entries_root"] is None
    assert body["commitments"] == []
    assert body["entries_count"] is None


async def test_public_audit_answers_404_for_unknown_and_draft_pools(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    draft = await insert_pool(db_session, status="DRAFT")
    assert (await client.get(f"/api/v1/public/pools/{draft}/audit")).status_code == 404
    assert (await client.get(f"/api/v1/public/pools/{uuid.uuid4()}/audit")).status_code == 404
