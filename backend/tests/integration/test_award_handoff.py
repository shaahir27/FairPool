"""T06A06: the lot handlers take a pool from an open window to an awarded checkout.

What ``docs/implementation-plan.md`` asks for and what proves it here:

* handlers per ``domain-ports.md`` section 5 -- ``lot.bid_open``, ``lot.bid_close`` and
  ``lot.award`` run against the real rows on the fake clock, audit, queue and notifier
  every checkout test already uses;
* the award snapshot with ``payment_router`` and ``payment_mode`` stamped (N8) and
  ``lot.open_checkout`` enqueued -- ``test_a_confirmed_bid_wins...``;
* priced-out marking, no-bid cancellation (LS-04) and unconfirmed rejection (BS-11);
* serialized in ``lot_order`` -- ``test_an_award_waits_for_a_lower_lot``, the guard that
  keeps R9 honest. ``domain/auction_rules.py`` owns the capacity arithmetic and its own
  tests cover R9 across lots; this test covers the handler's ordering rule;
* and the rule CR-8 note 3 exists for: a job that arrives after an ops ``force_award``
  returns quietly, because ``tools/demo_seed.py`` force-awards the demo pools that these
  jobs will now also be written for.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Award, Bid
from fairpool.db.models.enums import AllocationStatus, BidStatus, LotStatus
from fairpool.db.models.pools import Lot
from fairpool.domain import hashing
from fairpool.modules.auction.handlers import AWARD_RETRY_S, LotAuctionHandlers
from tests.integration.test_bid_sealing import lot_with_deadline, service, structured
from tests.integration.test_open_checkout import ZONE_ID, World, build_world

pytestmark = pytest.mark.integration

#: The pool template ``build_world`` writes; a bid that names another product fails R3.
PRODUCT_KEY = "monitor-27-4k"
#: Two tiers a two-seat lot can actually fill: ``test_bid_sealing``'s default minimums
#: (3 and 6) are above the fixture's seated count, so no tier would apply (R8).
TIER_TOP = {"min_qty": 1, "item_price_cents": 49_000}
TIER_CHEAP = {"min_qty": 2, "item_price_cents": 47_000}
#: The applicable tier with the lowest item price, which 10.3 makes the chosen one.
CHEAP_ITEM_CENTS = 47_000


def bid_fields(**overrides: Any) -> dict[str, Any]:
    """The contracted bid shape from ``test_bid_sealing``, retargeted at this pool."""
    base = structured(
        product_key=PRODUCT_KEY,
        capacity=12,
        total_capacity=24,
        moq=1,
        target_quantity=2,
        tiers=[TIER_TOP, TIER_CHEAP],
    )
    base.update(overrides)
    return base


def handlers(world: World, **overrides: Any) -> LotAuctionHandlers:
    """The three kinds over the world's fake ports and the shipped configuration."""
    ports = world.ports
    return LotAuctionHandlers(
        clock=ports.clock,
        audit=ports.audit,
        jobs=ports.jobs,
        notifier=ports.notifier,
        payment_router="single_seller",
        payment_mode="vault_charge",
        flat_delivered=True,
        **overrides,
    )


async def open_window(session: AsyncSession, *, lot_status: str = "BIDDING", **build: Any) -> World:
    """A BIDDING lot in a seeded pool with an eligible merchant and no stamps yet.

    ``build_world`` stamps the lot when it writes an award, so the stamps are cleared
    here: the test then proves ``lot.award`` wrote them instead of inheriting them.
    """
    world = await build_world(
        session, pool_status="ALLOCATED", lot_status=lot_status, with_award=False, **build
    )
    await session.execute(
        text("UPDATE pools SET seed_hex = :seed WHERE id = :pool"),
        {"seed": hashing.demo_seed(str(world.pool_id)), "pool": world.pool_id},
    )
    await session.execute(
        text("UPDATE lots SET payment_router = NULL, payment_mode = NULL WHERE id = :lot"),
        {"lot": world.lot_id},
    )
    await session.execute(
        text(
            "UPDATE merchants SET onboarding_status = 'DEMO', "
            "attestations = CAST(:at AS jsonb) WHERE id = :merchant"
        ),
        {
            "at": "{"
            + ",".join(
                f'"{key}": {{"at": "2026-11-01T00:00:00Z", "accepted": true}}'
                for key in (
                    "inventory_reserved",
                    "map_compliance",
                    "delivery_terms_accurate",
                )
            )
            + "}",
            "merchant": world.merchant_id,
        },
    )
    await session.flush()
    return world


async def confirmed_bid(session: AsyncSession, world: World, **fields: Any) -> UUID:
    """Save and confirm one bid on this lot, returning its id."""
    lot_id = await lot_with_deadline(session, world, offset_s=600)
    bid, revision = await service().save(
        session,
        merchant_id=world.merchant_id,
        lot_id=lot_id,
        structured=bid_fields(**fields),
    )
    await service().confirm(
        session, merchant_id=world.merchant_id, bid_id=bid.id, revision=revision.revision
    )
    return bid.id


async def lot_status(session: AsyncSession, lot_id: UUID) -> str:
    lot = await session.get(Lot, lot_id)
    assert lot is not None
    return str(lot.status)


async def close_and_award(session: AsyncSession, world: World) -> LotAuctionHandlers:
    """Run the window close and the award, returning the handler that did both.

    The bid was saved inside the window, so the fake clock moves past ``bid_close_at``
    here the way production time would: the stored ``submitted_at`` and the frozen
    deadline stay consistent, so R1_LATE is not provoked by the test itself (I15).
    """
    world.ports.clock.advance(900)
    auction = handlers(world)
    await auction.bid_close(session, {"lot_id": str(world.lot_id)})
    assert await lot_status(session, world.lot_id) == "BID_CLOSED"
    await auction.award(session, {"lot_id": str(world.lot_id)})
    return auction


async def test_a_confirmed_bid_wins_and_checkout_is_scheduled(db_session: AsyncSession) -> None:
    """LS-03 with its snapshot, its stamps (N8), its notify and its ``lot.open_checkout``."""
    world = await open_window(db_session, seats=3, min_seats=2, seated=2, waitlisted=1)
    bid_id = await confirmed_bid(db_session, world)
    await close_and_award(db_session, world)

    lot = await db_session.get(Lot, world.lot_id)
    assert lot is not None and str(lot.status) == str(LotStatus.AWARDED)
    assert str(lot.payment_router) == "single_seller"
    assert str(lot.payment_mode) == "vault_charge"

    award = await db_session.scalar(select(Award).where(Award.lot_id == world.lot_id))
    assert award is not None
    assert str(award.merchant_id) == str(world.merchant_id)
    # The applicable tier with the lowest item price wins (fairness-and-hashing 10.3);
    # two seats at min_qty 3 is not met by two seated entries, so tier 0 is the tier.
    assert int(award.item_cents) == CHEAP_ITEM_CENTS
    assert int(award.tier_index) == 1
    assert int(award.moq) == 2
    assert award.rule_version == "ranking_v1"
    assert len(str(award.award_hash)) == 64

    # flat_delivered: one delivered price, so shipping and tax are zero and the buyer's
    # total is the item price (flat-delivered-bids.md section 2).
    totals: dict[str, dict[str, int]] = dict(award.totals or {})
    assert set(totals) == {str(entry) for entry in world.entry_ids}
    for row in totals.values():
        assert row == {
            "item_cents": CHEAP_ITEM_CENTS,
            "shipping_cents": 0,
            "tax_cents": 0,
            "total_cents": CHEAP_ITEM_CENTS,
        }

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None and str(bid.status) == str(BidStatus.AWARDED)

    assert "lot.open_checkout" in [job.kind for job in world.ports.jobs.jobs]
    assert "lot.awarded" in [call.kind for call in world.ports.notifier.calls]


async def test_the_window_opening_schedules_its_own_close(db_session: AsyncSession) -> None:
    """LS-01 on time moves the pool to RUNNING (PS-06) and writes LS-02's timer."""
    world = await open_window(db_session, lot_status="PLANNED")
    auction = handlers(world)
    await auction.bid_open(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "BIDDING"
    pool_status = await db_session.scalar(
        text("SELECT status::text FROM pools WHERE id = :p"), {"p": world.pool_id}
    )
    assert str(pool_status) == "RUNNING", "PS-06: the first lot into BIDDING starts the pool"
    closing = [job for job in world.ports.jobs.jobs if job.kind == "lot.bid_close"]
    assert [str(job.concurrency_key) for job in closing] == [f"lot:{world.lot_id}"]


async def test_a_window_that_has_not_opened_yet_is_rescheduled(db_session: AsyncSession) -> None:
    """I15: a handler that runs early re-arms its own timer instead of forcing the edge."""
    world = await open_window(db_session, lot_status="PLANNED")
    later = world.now + timedelta(seconds=60)
    await db_session.execute(
        text("UPDATE lots SET bid_open_at = :at WHERE id = :lot"),
        {"at": later, "lot": world.lot_id},
    )
    await db_session.flush()
    before = len(world.ports.audit.rows)

    auction = handlers(world)
    await auction.bid_open(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "PLANNED"
    assert len(world.ports.audit.rows) == before, "no transition, so no audit row"
    assert [job.kind for job in world.ports.jobs.jobs if job.kind == "lot.bid_open"] == [
        "lot.bid_open"
    ]


async def test_a_bid_open_that_arrives_after_an_ops_award_does_nothing(
    db_session: AsyncSession,
) -> None:
    """CR-8 note 3, and the demo's reality.

    ``tools/demo_seed.py`` force-awards, so once ``pool.allocate`` emits the PS-05
    effect every seeded lot will receive these three jobs while already ``AWARDED``.
    Returning quietly is the requirement: an ``assert_transition`` here would alert on
    every demo pool and burn the job's retries.
    """
    world = await open_window(db_session, lot_status="AWARDED")
    auction = handlers(world)

    await auction.bid_open(db_session, {"lot_id": str(world.lot_id)})
    await auction.bid_close(db_session, {"lot_id": str(world.lot_id)})
    await auction.award(db_session, {"lot_id": str(world.lot_id)})

    assert await lot_status(db_session, world.lot_id) == "AWARDED"
    assert world.ports.audit.rows == []
    assert world.ports.jobs.jobs == []
    assert world.ports.notifier.calls == []


async def test_a_lot_without_a_bid_is_cancelled_not_awarded(db_session: AsyncSession) -> None:
    """LS-04: no feasible bid and no money exists, so the lot closes CANCELLED."""
    world = await open_window(db_session)
    await lot_with_deadline(db_session, world, offset_s=-1)
    await close_and_award(db_session, world)

    assert await lot_status(db_session, world.lot_id) == "CANCELLED"
    assert await db_session.scalar(select(Award).where(Award.lot_id == world.lot_id)) is None
    assert "lot.open_checkout" not in [job.kind for job in world.ports.jobs.jobs]


async def test_a_seat_that_cannot_cover_the_award_is_priced_out(db_session: AsyncSession) -> None:
    """SEATED to PRICED_OUT happens only inside ``lot.award``, and it releases the seat."""
    world = await open_window(db_session, seats=3, min_seats=1, seated=2, waitlisted=1)
    victim = world.entry_ids[0]
    await db_session.execute(
        text("UPDATE pool_entries SET cap_cents = :cap WHERE id = :entry"),
        {"cap": CHEAP_ITEM_CENTS - 1, "entry": victim},
    )
    await db_session.flush()
    bid_id = await confirmed_bid(db_session, world)
    await close_and_award(db_session, world)

    assert await lot_status(db_session, world.lot_id) == "AWARDED"
    rows = (
        await db_session.execute(
            text("SELECT entry_id, status::text, lot_id FROM allocations WHERE pool_id = :p"),
            {"p": world.pool_id},
        )
    ).all()
    by_entry = {str(entry): (str(status), lot) for entry, status, lot in rows}
    assert by_entry[str(victim)][0] == str(AllocationStatus.PRICED_OUT)
    assert by_entry[str(victim)][1] is None, "a priced-out seat is released, not held (N12)"
    # The other seated entry keeps its lot.
    kept = [entry for entry in world.entry_ids if str(entry) != str(victim)]
    assert by_entry[str(kept[0])][1] is not None
    bid = await db_session.get(Bid, bid_id)
    assert bid is not None and str(bid.status) == str(BidStatus.AWARDED)


async def test_an_unconfirmed_revision_never_reaches_the_auction(
    db_session: AsyncSession,
) -> None:
    """R1 and BS-11: a draft is rejected at award and the lot has no winner."""
    world = await open_window(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    bid, _ = await service().save(
        db_session,
        merchant_id=world.merchant_id,
        lot_id=lot_id,
        structured=bid_fields(),
    )
    await close_and_award(db_session, world)

    row = await db_session.get(Bid, bid.id)
    assert row is not None and str(row.status) == str(BidStatus.REJECTED)
    assert str(row.reject_reason) == "R1_UNCONFIRMED"
    assert await lot_status(db_session, world.lot_id) == "CANCELLED"


async def test_an_award_waits_for_a_lower_lot_to_be_decided(db_session: AsyncSession) -> None:
    """``lot_order`` serialization: this lot requeues instead of outrunning lot 1.

    R9 shrinks a merchant's capacity lot by lot, so deciding lot 2 while lot 1 is still
    open could award the same capacity twice. The requeue carries the pool's
    ``award:{pool_id}`` key and lands two seconds later.
    """
    world = await open_window(db_session, seats=3, min_seats=1, seated=2, waitlisted=0)
    second = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, :zone, 1, 2, 3, 1, "
            "'BID_CLOSED'::lot_status, :now, :now)"
        ),
        {"id": second, "pool": world.pool_id, "zone": ZONE_ID, "now": world.now},
    )
    await db_session.flush()
    auction = handlers(world)

    await auction.award(db_session, {"lot_id": str(second)})

    assert await lot_status(db_session, second) == "BID_CLOSED"
    waiting = [job for job in world.ports.jobs.jobs if job.kind == "lot.award"]
    assert [str(job.concurrency_key) for job in waiting] == [f"award:{world.pool_id}"]
    assert waiting[0].run_at >= world.now.replace(microsecond=0)
    assert AWARD_RETRY_S == 2, "domain-ports.md section 5 fixes the requeue delay"

    # Decide the earlier lot, and this one can be awarded: no bid either way, so both
    # end CANCELLED (LS-04) and the second only after the first was reached.
    world.ports.clock.advance(900)
    await auction.bid_close(db_session, {"lot_id": str(world.lot_id)})
    await auction.award(db_session, {"lot_id": str(world.lot_id)})
    assert await lot_status(db_session, world.lot_id) == "CANCELLED"
    await auction.award(db_session, {"lot_id": str(second)})
    assert await lot_status(db_session, second) == "CANCELLED"
