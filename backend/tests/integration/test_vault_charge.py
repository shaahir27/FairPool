"""T04A02/T04A03 vault mode: BO-23 to BO-27 with a saved permission.

The precheck, the single charge, the three outcomes (COMPLETED, PENDING,
definitive decline) and the concurrency limit are each a named test. The saved
token value is encrypted with the real AES-GCM cipher, and one test asserts it
never appears in an audit row, a job payload or a notification (rule 27).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.infra.crypto import AesGcmCipher, key_from_config_value
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.vault_charge import VaultChargeHandler, _slot_key
from tests.integration.test_open_checkout import (
    FakeRouter,
    World,
    build_world,
    make_directory,
    make_router,
    open_handler,
)
from tests.unit.test_settings import vault_key

pytestmark = pytest.mark.integration

TOKEN_VALUE = "PAYMENT-TOKEN-SECRET-1234"


def cipher() -> AesGcmCipher:
    return AesGcmCipher(key_from_config_value(vault_key()))


async def add_token(
    session: AsyncSession,
    *,
    entry_id: UUID,
    user_id: UUID,
    cap_cents: int,
    status: str = "ACTIVE",
) -> UUID:
    sealed = cipher().seal(TOKEN_VALUE)
    token_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO vault_tokens (id, entry_id, user_id, status, token_ciphertext, "
            "token_nonce, token_label, cap_cents, consent_version, consent_text_sha256, "
            "consented_at) VALUES (:id, :entry, :user, CAST(:status AS vault_status), "
            ":cipher, :nonce, '1234', :cap, 'v1', :hash, now())"
        ),
        {
            "id": token_id,
            "entry": entry_id,
            "user": user_id,
            "status": status,
            "cipher": sealed[1],
            "nonce": sealed[0],
            "cap": cap_cents,
            "hash": "0" * 64,
        },
    )
    return token_id


async def vault_world(
    session: AsyncSession,
    *,
    seats: int = 1,
    cap_cents: int = 60_000,
    token_status: str = "ACTIVE",
    outcome: str = "completed",
    concurrency: int = 5,
) -> tuple[World, UUID, FakeRouter, VaultChargeHandler]:
    world = await build_world(session, seats=seats, seated=seats, waitlisted=0, mode="vault_charge")
    for index in range(seats):
        await add_token(
            session,
            entry_id=world.entry_ids[index],
            user_id=world.user_ids[index],
            cap_cents=cap_cents,
            status=token_status,
        )
    await open_handler(world).open(session, {"lot_id": str(world.lot_id)})
    router = make_router(outcome=outcome)
    handler = VaultChargeHandler(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router,
        cipher=cipher(),
        concurrency=concurrency,
    )
    return world, world.entry_ids[0], router, handler


async def first_order(session: AsyncSession, world: World) -> UUID:
    value = await session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY created_at LIMIT 1"),
        {"lot": world.lot_id},
    )
    assert value is not None
    return UUID(str(value))


async def order_status(session: AsyncSession, buyer_order_id: UUID) -> str:
    return str(
        await session.scalar(
            text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": buyer_order_id}
        )
    )


async def test_vault_charge_completes_and_records_the_ledger(
    db_session: AsyncSession,
) -> None:
    """T04A02 acceptance: BO-23 then BO-24 on COMPLETED, amount equal to the award."""
    world, _, router, handler = await vault_world(db_session, seats=1)
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURED"
    assert [row.kind for row in world.ports.ledger.entries] == ["CAPTURE_COMPLETED"]
    assert (
        world.ports.ledger.entries[0].amount_cents
        == world.totals[str(world.entry_ids[0])]["total_cents"]
    )
    capture_status = await db_session.scalar(
        text("SELECT status FROM paypal_captures WHERE buyer_order_id = :id"), {"id": order_id}
    )
    assert str(capture_status) == "COMPLETED"
    assert router.gateway.captures  # the fake produced one capture resource
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.try_fund") == 1


async def test_a_total_above_the_cap_rejects_the_seat_before_any_charge(
    db_session: AsyncSession,
) -> None:
    """BO-27: the precheck compares integer cents against the entry cap."""
    world = await build_world(
        db_session, seats=1, seated=1, waitlisted=0, mode="vault_charge", cap_cents=40_000
    )
    await add_token(
        db_session,
        entry_id=world.entry_ids[0],
        user_id=world.user_ids[0],
        cap_cents=60_000,
    )
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    router = make_router()
    handler = VaultChargeHandler(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router,
        cipher=cipher(),
        concurrency=5,
    )
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "REJECTED"
    assert router.gateway.captures == {}
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") >= 1
    assert world.ports.ledger.entries == []


async def test_a_token_that_is_not_active_rejects_the_seat(
    db_session: AsyncSession,
) -> None:
    """BO-27: a missing or non-ACTIVE permission never reaches a charge."""
    world, _, router, handler = await vault_world(db_session, seats=1, token_status="SETUP_PENDING")
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "REJECTED"
    assert router.gateway.captures == {}


async def test_a_pending_capture_is_not_paid_until_polled(db_session: AsyncSession) -> None:
    """BO-25 (P3): PENDING records the ledger fact, schedules a poll and is unpaid."""
    world, _, _, handler = await vault_world(db_session, seats=1, outcome="pending")
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURE_PENDING"
    assert [row.kind for row in world.ports.ledger.entries] == ["CAPTURE_PENDING"]
    assert [job.kind for job in world.ports.jobs.jobs].count("capture.poll") == 1


async def test_a_definitive_decline_frees_the_seat_and_deletes_the_token(
    db_session: AsyncSession,
) -> None:
    """BO-26 (vault-charge.md section 7): INSTRUMENT_DECLINED is definitive."""
    world, entry_id, _, handler = await vault_world(db_session, seats=1, outcome="declined")
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURE_FAILED"
    status = await db_session.scalar(
        text("SELECT status FROM vault_tokens WHERE entry_id = :entry"), {"entry": entry_id}
    )
    assert str(status) == "DELETED"
    assert world.ports.ledger.entries == []
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") >= 1


async def test_an_unknown_outcome_stays_capturing(db_session: AsyncSession) -> None:
    """vault-charge.md section 7: 5xx, timeout and unknown stay CAPTURING."""
    world, _, _, handler = await vault_world(db_session, seats=1, outcome="timeout_after_send")
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURING"
    assert world.ports.ledger.entries == []
    assert not [job for job in world.ports.jobs.jobs if job.kind == "lot.refill"]


class PermissionDeniedGateway(FakePayPalGateway):
    """The created order could not be captured (the real adapter's ChargeResult)."""

    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Any
    ) -> Any:
        from fairpool.domain.payments import ChargeResult

        return ChargeResult(f"ORDER-{buyer_order_id}", None, None, "PERMISSION_DENIED")


async def test_a_permission_denied_charge_is_definitive_and_frees_the_seat(
    db_session: AsyncSession,
) -> None:
    """vault-charge.md section 7: 403 PERMISSION_DENIED is definitive and deletes."""
    world, _, _, _ = await vault_world(db_session, seats=1)
    order_id = await first_order(db_session, world)
    router = FakeRouter(
        gateway=PermissionDeniedGateway(),
        seller=Payee(email="seller@example.test", merchant_id=None),
    )
    handler = VaultChargeHandler(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router,
        cipher=cipher(),
        concurrency=5,
    )

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURE_FAILED"
    status = await db_session.scalar(
        text("SELECT status FROM vault_tokens WHERE entry_id = :entry"),
        {"entry": world.entry_ids[0]},
    )
    assert str(status) == "DELETED"
    assert [job.kind for job in world.ports.jobs.jobs].count("lot.refill") >= 1


async def test_a_revoked_permission_at_create_deletes_the_token_and_waits(
    db_session: AsyncSession,
) -> None:
    """A definitive raise with no provider resource marks the token and stays put.

    The engine accepts only a PayPal resource this buyer order owns as BO-26
    evidence, so a create-time 403 cannot free the seat without inventing one; the
    order stays CAPTURING and the reconciler owns it (reported as a contract gap).
    """
    world, entry_id, _, handler = await vault_world(db_session, seats=1, outcome="revoked")
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    assert await order_status(db_session, order_id) == "CAPTURING"
    status = await db_session.scalar(
        text("SELECT status FROM vault_tokens WHERE entry_id = :entry"), {"entry": entry_id}
    )
    assert str(status) == "DELETED"


async def test_no_charge_slot_requeues_instead_of_blocking(
    db_session: AsyncSession, db_engine: Any
) -> None:
    """T04A02 acceptance: at most VAULT_CHARGE_CONCURRENCY charges run at once."""
    world, _, router, handler = await vault_world(db_session, seats=1, concurrency=1)
    order_id = await first_order(db_session, world)
    async with db_engine.connect() as other:
        transaction = await other.begin()
        held = await other.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _slot_key(0)}
        )
        assert held
        try:
            await handler.charge(db_session, {"buyer_order_id": str(order_id)})
        finally:
            await transaction.rollback()

    assert await order_status(db_session, order_id) == "OFFERED"
    assert router.gateway.captures == {}
    requeued = [job for job in world.ports.jobs.jobs if job.kind == "order.vault_charge"]
    assert len(requeued) == 2  # the one from open_checkout plus this retry
    assert requeued[-1].run_at == world.ports.clock.now + timedelta(seconds=5)


async def test_the_saved_token_never_reaches_an_audit_row_or_a_job(
    db_session: AsyncSession,
) -> None:
    """Rule 27: the decrypted permission is a credential and stays out of records."""
    world, _, _, handler = await vault_world(db_session, seats=1)
    order_id = await first_order(db_session, world)

    await handler.charge(db_session, {"buyer_order_id": str(order_id)})

    audit_text = json.dumps(world.ports.audit.rows)
    job_text = json.dumps([job.payload for job in world.ports.jobs.jobs])
    notify_text = json.dumps([call.payload for call in world.ports.notifier.calls])
    for blob in (audit_text, job_text, notify_text):
        assert TOKEN_VALUE not in blob
    stored = await db_session.scalar(
        text(
            "SELECT token_ciphertext FROM vault_tokens WHERE entry_id = :entry "
            "AND deleted_at IS NULL"
        ),
        {"entry": world.entry_ids[0]},
    )
    assert stored is not None and TOKEN_VALUE.encode() not in bytes(stored)


def test_the_slot_keys_are_stable_and_distinct() -> None:
    """The concurrency permits are stable signed bigints, one per slot."""
    assert _slot_key(0) == _slot_key(0)
    assert _slot_key(0) != _slot_key(1)
    assert -(1 << 63) <= _slot_key(4) < (1 << 63)
