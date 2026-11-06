"""F6: the award path tells everyone an outcome, not only the merchants.

``state-machines.md`` declares ``notify`` on BS-08 and BS-09, and LS-04's cancellation
already reaches buyers on the ops abort path (``checkout/ops.py::_notify_seated``). The
award path issued neither, so a seated buyer in a lot that produced no feasible bid
heard nothing at all and a losing merchant learned only by polling.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_award_handoff import (
    bid_fields,
    close_and_award,
    confirmed_bid,
    lot_status,
    lot_with_deadline,
    open_window,
    service,
)
from tests.integration.test_open_checkout import World

pytestmark = pytest.mark.integration


async def seated_user_ids(session: AsyncSession, lot_id: UUID) -> set[UUID]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT pe.user_id FROM allocations a "
                    "JOIN pool_entries pe ON pe.id = a.entry_id "
                    "WHERE a.lot_id = :lot AND a.status = 'SEATED'"
                ),
                {"lot": lot_id},
            )
        )
        .scalars()
        .all()
    )
    return {UUID(str(value)) for value in rows}


def notices(world: World, kind: str) -> list[dict[str, Any]]:
    return [
        {"user_id": UUID(str(call.user_id)), "payload": dict(call.payload)}
        for call in world.ports.notifier.calls
        if str(call.kind) == kind
    ]


async def test_ls_04_notifies_every_seated_buyer(db_session: AsyncSession) -> None:
    # T09B04 acceptance 1: buyers told they held a seat hear that the lot found no bid.
    world = await open_window(db_session, seats=3, min_seats=1, seated=2, waitlisted=1)
    await lot_with_deadline(db_session, world, offset_s=-1)
    await close_and_award(db_session, world)
    assert await lot_status(db_session, world.lot_id) == "CANCELLED"

    told = {notice["user_id"] for notice in notices(world, "lot.cancelled")}
    seated = await seated_user_ids(db_session, world.lot_id)
    assert seated, "the world must seat someone for this to mean anything"
    assert seated <= told, "every seated buyer is notified, not only the merchants"
    for notice in notices(world, "lot.cancelled"):
        if notice["user_id"] in seated:
            assert notice["payload"]["lot_id"] == str(world.lot_id)


async def add_second_merchant(session: AsyncSession) -> tuple[UUID, UUID]:
    """A bidding rival: one user, one merchant profile, no other wiring needed."""
    user_id, merchant_id = uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Rival', 'merchant')"
        ),
        {"id": user_id, "email": f"rival-{merchant_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO merchants (id, user_id, display_name) "
            "VALUES (:id, :user, 'Rival Merchant')"
        ),
        {"id": merchant_id, "user": user_id},
    )
    # R2 requires the same attestation set open_window grants the seeded merchant, or
    # the rival is REJECTED as ineligible and never reaches the ranking at all.
    await session.execute(
        text(
            "UPDATE merchants SET onboarding_status = 'DEMO', "
            "attestations = CAST(:at AS jsonb) WHERE id = :merchant"
        ),
        {
            "at": "{"
            + ",".join(
                f'"{key}": {{"at": "2026-11-01T00:00:00Z", "accepted": true}}'
                for key in ("inventory_reserved", "map_compliance", "delivery_terms_accurate")
            )
            + "}",
            "merchant": merchant_id,
        },
    )
    await session.flush()
    return user_id, merchant_id


async def test_bs_09_notifies_the_loser_and_the_winner_keeps_its_award_notice(
    db_session: AsyncSession,
) -> None:
    """BS-09 declared notify and the award issued none; the winner's notice is BS-08's."""
    world = await open_window(db_session, seats=3, min_seats=1, seated=2, waitlisted=1)
    await confirmed_bid(
        db_session, world, tiers=[{"min_qty": 1, "item_price_cents": 47_000}], moq=1
    )
    rival_user, rival = await add_second_merchant(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bids = service()
    bid, revision = await bids.save(
        db_session,
        merchant_id=rival,
        lot_id=lot_id,
        structured=bid_fields(tiers=[{"min_qty": 1, "item_price_cents": 52_000}]),
    )
    await bids.confirm(db_session, merchant_id=rival, bid_id=bid.id, revision=revision.revision)

    await close_and_award(db_session, world)

    lost = notices(world, "bid.lost")
    assert [notice["user_id"] for notice in lost] == [rival_user]
    assert lost[0]["payload"]["bid_id"] == str(bid.id)
    awarded = notices(world, "lot.awarded")
    assert awarded and awarded[0]["user_id"] == world.merchant_user_id
    # The rival is LOST, not REJECTED: it passed every rule and simply cost more.
    from fairpool.db.models.auction import Bid

    assert str((await db_session.get(Bid, bid.id)).status) == "LOST"
