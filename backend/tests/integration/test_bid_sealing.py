"""T05A04: sealed bid revisions, signed receipts, confirmation and late rejection."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.modules.auction.bids import FLAT_DELIVERED_MESSAGE, BidService
from fairpool.modules.pools.receipts import (
    format_received_at,
    public_key_b64url,
    signing_seed,
)
from tests.integration.test_open_checkout import World, build_world

pytestmark = pytest.mark.integration

SEED = signing_seed("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8")


def structured(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "product_key": "monitor-27",
        "condition": "NEW",
        "bundle": ["monitor", "stand", "cable"],
        "tiers": [
            {"min_qty": 3, "item_price_cents": 47000},
            {"min_qty": 6, "item_price_cents": 45000},
        ],
        "tax": {"mode": "INCLUDED"},
        "capacity": 12,
        "delivery_sla_days": 7,
        "returns_days": 30,
        "validity_end": "2026-12-01T00:00:00Z",
    }
    base.update(overrides)
    return base


async def lot_with_deadline(session: AsyncSession, world: World, *, offset_s: int) -> UUID:
    await session.execute(
        text("UPDATE lots SET bid_close_at = :at WHERE id = :lot"),
        {"at": world.now + timedelta(seconds=offset_s), "lot": world.lot_id},
    )
    await session.flush()
    return world.lot_id


def service(flat_delivered: bool = True) -> BidService:
    return BidService(clock=DbClock(), seed=SEED, flat_delivered=flat_delivered)


async def test_a_bid_revision_carries_a_verifiable_receipt(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)

    bid, revision = await service().save(
        db_session, merchant_id=merchant_id, lot_id=lot_id, structured=structured()
    )
    assert str(bid.status) == "PROPOSED"
    assert revision.revision == 1
    recomputed = hashing.bid_receipt_hash(
        str(bid.id), 1, structured(), format_received_at(revision.created_at)
    )
    assert recomputed == revision.receipt_hash
    payload = hashing.bid_receipt_payload(str(bid.id), 1, revision.receipt_hash)
    assert hashing.verify_ed25519(payload, revision.receipt_signature, public_key_b64url(SEED))


async def test_a_second_save_is_a_new_revision(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    first, _ = await service().save(
        db_session, merchant_id=merchant_id, lot_id=lot_id, structured=structured()
    )
    second, revision = await service().save(
        db_session,
        merchant_id=merchant_id,
        lot_id=lot_id,
        structured=structured(capacity=20),
    )
    assert second.id == first.id
    assert revision.revision == 2
    assert second.current_revision == 2


async def test_a_bid_after_close_is_rejected_on_the_database_clock(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=-1)
    bid, _ = await service().save(
        db_session, merchant_id=merchant_id, lot_id=lot_id, structured=structured()
    )
    assert str(bid.status) == "REJECTED"
    assert bid.reject_reason == "R1_LATE"


async def test_confirm_sets_the_confirmation_time(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, revision = await service().save(
        db_session, merchant_id=merchant_id, lot_id=lot_id, structured=structured()
    )
    confirmed = await service().confirm(
        db_session, merchant_id=merchant_id, bid_id=bid.id, revision=revision.revision
    )
    assert str(confirmed.status) == "CONFIRMED"
    row = await db_session.scalar(
        text("SELECT confirmed_at FROM bid_revisions WHERE bid_id = :bid"), {"bid": str(bid.id)}
    )
    assert row is not None


async def test_another_merchants_bid_is_not_found(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    owner = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, _ = await service().save(
        db_session, merchant_id=owner, lot_id=lot_id, structured=structured()
    )
    with pytest.raises(ApplicationError) as caught:
        await service().get(db_session, merchant_id=uuid4(), bid_id=bid.id)
    assert caught.value.code == "NOT_FOUND"


async def test_flat_delivered_rejects_an_itemised_tax_mode(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    with pytest.raises(ApplicationError) as caught:
        await service().save(
            db_session,
            merchant_id=merchant_id,
            lot_id=lot_id,
            structured=structured(tax={"mode": "RATE_TABLE", "rate_bps_by_region": {"US": 875}}),
        )
    assert caught.value.public_message == FLAT_DELIVERED_MESSAGE


async def test_tiers_must_ascend_in_quantity_and_not_rise_in_price(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    merchant_id = world.merchant_id
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    with pytest.raises(ApplicationError):
        await service().save(
            db_session,
            merchant_id=merchant_id,
            lot_id=lot_id,
            structured=structured(
                tiers=[
                    {"min_qty": 3, "item_price_cents": 47000},
                    {"min_qty": 3, "item_price_cents": 46000},
                ]
            ),
        )
    with pytest.raises(ApplicationError):
        await service().save(
            db_session,
            merchant_id=merchant_id,
            lot_id=lot_id,
            structured=structured(
                tiers=[
                    {"min_qty": 3, "item_price_cents": 45000},
                    {"min_qty": 6, "item_price_cents": 46000},
                ]
            ),
        )
