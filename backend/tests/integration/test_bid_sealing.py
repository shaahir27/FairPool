"""T05A04: sealed bid revisions, signed receipts, confirmation and the bid deadline.

Every status write here is a ``bid`` whitelist edge (I10), so the tests read the
audit rows as well as the ``bids`` row: a save revives nothing, a revise clears the
confirmation, and a deadline that has passed accepts nothing.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Bid
from fairpool.db.models.enums import BidStatus
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.audit import FakeAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.auction.bids import FLAT_DELIVERED_MESSAGE, BidService
from fairpool.modules.pools.receipts import (
    format_received_at,
    public_key_b64url,
    signing_seed,
)
from tests.integration.test_open_checkout import World, build_world

pytestmark = pytest.mark.integration

SEED = signing_seed(base64.b64encode(b"fairpool-test-bid-receipt-seed32").decode())


def structured(**overrides: Any) -> dict[str, Any]:
    """The contracted ``bid_revisions.structured`` shape (``db-schema.md``, FR-AU-02)."""
    base: dict[str, Any] = {
        "v": 1,
        "product_key": "monitor-27",
        "condition": "NEW",
        "bundle_contents": ["monitor", "stand", "power cable"],
        "capacity": 12,
        "target_quantity": 12,
        "moq": 3,
        "tiers": [
            {"min_qty": 3, "item_price_cents": 47000},
            {"min_qty": 6, "item_price_cents": 45000},
        ],
        "shipping_cents_by_zone": {},
        "tax": {"mode": "INCLUDED"},
        "delivery": {"sla_days": 7},
        "returns": {"days": 30},
        "valid_until": "2026-12-01T00:00:00Z",
        "total_capacity": 24,
        "evidence": {"note": "units reserved in warehouse A", "url": None},
    }
    base.update(overrides)
    return base


async def bidding_world(session: AsyncSession) -> World:
    """A lot in BIDDING with no award: the only state a merchant may bid into."""
    return await build_world(
        session, seats=2, seated=2, waitlisted=0, lot_status="BIDDING", with_award=False
    )


async def lot_with_deadline(session: AsyncSession, world: World, *, offset_s: int) -> UUID:
    await session.execute(
        text("UPDATE lots SET bid_close_at = :at WHERE id = :lot"),
        {"at": world.now + timedelta(seconds=offset_s), "lot": world.lot_id},
    )
    await session.flush()
    return world.lot_id


async def set_bid_status(session: AsyncSession, bid_id: UUID, status: str) -> None:
    """Fixture-only direct write of what ``lot.award`` will decide from T06A06 onwards."""
    bid = await session.get(Bid, bid_id)
    assert bid is not None
    bid.status = BidStatus(status)
    await session.flush()


def service(audit: FakeAuditLog | None = None, flat_delivered: bool = True) -> BidService:
    return BidService(
        clock=DbClock(), audit=audit or FakeAuditLog(), seed=SEED, flat_delivered=flat_delivered
    )


def transition_ids(audit: FakeAuditLog) -> list[str]:
    return [str(entry["row"]["payload"]["transition_id"]) for entry in audit.rows]


async def test_a_bid_revision_carries_a_verifiable_receipt(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)

    bid, revision = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    assert str(bid.status) == "DRAFT"
    assert revision.revision == 1
    recomputed = hashing.bid_receipt_hash(
        str(bid.id), 1, structured(), format_received_at(revision.created_at)
    )
    assert recomputed == revision.receipt_hash
    payload = hashing.bid_receipt_payload(str(bid.id), 1, revision.receipt_hash)
    assert hashing.verify_ed25519(payload, revision.receipt_signature, public_key_b64url(SEED))


async def test_a_second_save_is_a_new_revision(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    first, _ = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    second, revision = await service().save(
        db_session,
        merchant_id=world.merchant_id,
        lot_id=lot_id,
        structured=structured(capacity=20),
    )
    assert second.id == first.id
    assert revision.revision == 2
    assert second.current_revision == 2


async def test_confirmation_is_a_whitelisted_edge_with_an_audit_row(
    db_session: AsyncSession,
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    audit = FakeAuditLog()
    bid, revision = await service(audit).save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    confirmed = await service(audit).confirm(
        db_session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
    )
    assert str(confirmed.status) == "CONFIRMED"
    row = await db_session.scalar(
        text("SELECT confirmed_at FROM bid_revisions WHERE bid_id = :bid"), {"bid": str(bid.id)}
    )
    assert row is not None
    assert transition_ids(audit) == ["BS-02"]
    entry = audit.rows[-1]["row"]
    assert entry["action"] == "bid.confirmed"
    assert entry["subject_type"] == "bid"
    assert entry["payload"]["trigger"] == "merchant.confirm"


async def test_revising_a_confirmed_bid_returns_it_to_draft(db_session: AsyncSession) -> None:
    """BS-12: a saved revision is unconfirmed again, so it can never rank as it was."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    audit = FakeAuditLog()
    bid, revision = await service(audit).save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    await service(audit).confirm(
        db_session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
    )
    _, second = await service(audit).save(
        db_session,
        merchant_id=world.merchant_id,
        lot_id=lot_id,
        structured=structured(capacity=20),
    )
    assert str(bid.status) == "DRAFT"
    assert second.revision == 2
    assert transition_ids(audit) == ["BS-02", "BS-12"]


async def test_a_bid_saved_after_the_deadline_is_refused_on_the_database_clock(
    db_session: AsyncSession,
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, revision = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    await service().confirm(
        db_session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
    )
    await lot_with_deadline(db_session, world, offset_s=-1)
    with pytest.raises(ApplicationError) as caught:
        await service().save(
            db_session,
            merchant_id=world.merchant_id,
            lot_id=lot_id,
            structured=structured(capacity=1),
        )
    assert caught.value.code == "BID_WINDOW_CLOSED"
    # The confirmed bid stands untouched: a late write neither revised nor unranked it.
    assert str(bid.status) == "CONFIRMED"
    assert int(bid.current_revision) == 1


async def test_a_bid_on_a_lot_that_is_not_bidding_is_refused(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    with pytest.raises(ApplicationError) as caught:
        await service().save(
            db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
        )
    assert caught.value.code == "LOT_NOT_BIDDING"


async def test_a_decided_bid_can_never_be_confirmed(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, revision = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    await set_bid_status(db_session, bid.id, "REJECTED")
    with pytest.raises(ApplicationError) as caught:
        await service().confirm(
            db_session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
        )
    assert caught.value.code == "LOT_NOT_BIDDING"


async def test_a_bid_missing_a_contracted_field_is_refused(db_session: AsyncSession) -> None:
    """BS-02's "complete and valid" guard is enforced at the write, not at the award."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    for missing in ("evidence", "target_quantity", "valid_until", "returns"):
        payload = structured()
        del payload[missing]
        with pytest.raises(ApplicationError) as caught:
            await service().save(
                db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=payload
            )
        assert caught.value.code == "VALIDATION_ERROR"


async def test_a_confirm_after_the_window_closes_is_refused(db_session: AsyncSession) -> None:
    """I15: the deadline is re-read when the handler runs, so a stale tab cannot bid."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, revision = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    await lot_with_deadline(db_session, world, offset_s=-1)
    with pytest.raises(ApplicationError) as caught:
        await service().confirm(
            db_session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
        )
    assert caught.value.code == "BID_WINDOW_CLOSED"
    assert str(bid.status) == "DRAFT"
    row = await db_session.scalar(
        text("SELECT confirmed_at FROM bid_revisions WHERE bid_id = :bid"), {"bid": str(bid.id)}
    )
    assert row is None


async def test_a_capacity_below_the_lot_seats_is_refused(db_session: AsyncSession) -> None:
    """R4 needs seat coverage: one bid must be able to fill the lot it bids for."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    with pytest.raises(ApplicationError) as caught:
        await service().save(
            db_session,
            merchant_id=world.merchant_id,
            lot_id=lot_id,
            structured=structured(capacity=1),
        )
    assert caught.value.code == "VALIDATION_ERROR"


async def test_another_merchants_bid_is_not_found(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, _ = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=lot_id, structured=structured()
    )
    with pytest.raises(ApplicationError) as caught:
        await service().get(db_session, merchant_id=uuid4(), bid_id=bid.id)
    assert caught.value.code == "NOT_FOUND"


async def test_flat_delivered_rejects_an_itemised_tax_mode(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    with pytest.raises(ApplicationError) as caught:
        await service().save(
            db_session,
            merchant_id=world.merchant_id,
            lot_id=lot_id,
            structured=structured(tax={"mode": "RATE_TABLE", "rate_bps_by_region": {"US": 875}}),
        )
    assert caught.value.public_message == FLAT_DELIVERED_MESSAGE


async def test_tiers_must_ascend_in_quantity_and_not_rise_in_price(
    db_session: AsyncSession,
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    with pytest.raises(ApplicationError):
        await service().save(
            db_session,
            merchant_id=world.merchant_id,
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
            merchant_id=world.merchant_id,
            lot_id=lot_id,
            structured=structured(
                tiers=[
                    {"min_qty": 3, "item_price_cents": 45000},
                    {"min_qty": 6, "item_price_cents": 46000},
                ]
            ),
        )
