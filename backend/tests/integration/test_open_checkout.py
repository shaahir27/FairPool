"""T04A01 and PT-08: ``lot.open_checkout`` creates offers within seats and refills.

PT-08 is the property that offers in flight plus committed buyers never exceed the
lot's seats: priced-out seats are refilled from the waitlist by the same N12 rule
the read service exposes, and a lot with more seated entries than seats only ever
creates ``seats`` offers.

The helpers in this module build a real Postgres lot world and are imported by the
other Phase 4 checkout tests (the pattern ``tests/integration/test_triggers.py``
established: one builder, no forks).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.payments import Payee
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.idempotency import FakeIdempotencyStore
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.fakes.ledger import FakeLedger
from fairpool.fakes.merchant_directory import FakeMerchantDirectory
from fairpool.fakes.notifier import FakeNotifier
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.infra.clock import DbClock
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.engine import CheckoutEngine
from fairpool.modules.checkout.open_checkout import OpenCheckoutHandler
from fairpool.ports import PayeeRef

pytestmark = pytest.mark.integration

TOTAL_CENTS = 50_000
CAP_CENTS = 60_000
ITEM_CENTS = 47_000
SHIPPING_CENTS = 1_500
TAX_CENTS = 1_500

ZONE_ID = "US-EAST"


@dataclass
class CheckoutPorts:
    clock: FakeClock
    audit: FakeAuditLog
    jobs: FakeJobQueue
    ledger: FakeLedger
    notifier: FakeNotifier
    idempotency: FakeIdempotencyStore
    engine: CheckoutEngine = field(init=False)

    def __post_init__(self) -> None:
        self.engine = CheckoutEngine(
            clock=self.clock,
            audit=self.audit,
            jobs=self.jobs,
            ledger=self.ledger,
            notifier=self.notifier,
            idempotency=self.idempotency,
        )


@dataclass
class FakeRouter:
    """The ``PaymentRouter`` surface checkout uses, over the offline gateway."""

    gateway: FakePayPalGateway
    seller: Payee
    name: str = "fake"

    def payee_for(self, award: Any, payee_ref: PayeeRef) -> Payee:
        return self.seller

    def label(self) -> str | None:
        return None


@dataclass
class World:
    """One pool, one lot, an award, entries, allocations and fake ports."""

    session: AsyncSession
    pool_id: UUID
    lot_id: UUID
    merchant_id: UUID
    merchant_user_id: UUID
    entry_ids: list[UUID]
    user_ids: list[UUID]
    totals: dict[str, dict[str, int]]
    now: datetime
    ports: CheckoutPorts


def make_ports(now: datetime) -> CheckoutPorts:
    clock = FakeClock(now)
    return CheckoutPorts(
        clock=clock,
        audit=FakeAuditLog(clock=lambda: now),
        jobs=FakeJobQueue(clock=clock),
        ledger=FakeLedger(),
        notifier=FakeNotifier(),
        idempotency=FakeIdempotencyStore(),
    )


def make_router(*, outcome: str = "completed", email: str = "seller@example.test") -> FakeRouter:
    return FakeRouter(
        gateway=FakePayPalGateway(outcome=outcome),
        seller=Payee(email=email, merchant_id=None),
    )


def make_directory(merchant_id: UUID) -> FakeMerchantDirectory:
    return FakeMerchantDirectory(
        payees={
            merchant_id: PayeeRef(
                merchant_id=merchant_id,
                display_name="Demo Merchant",
                payee_email="payee@example.test",
                paypal_merchant_id=None,
                onboarding_status="DEMO",
            )
        }
    )


def timeline(
    now: datetime, *, offer_window_s: int = 180, fund_deadline_s: int = 600
) -> dict[str, Any]:
    return {
        "open_at": (now - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "close_at": (now + timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "beacon_delay_s": 10,
        "bid_window_s": 120,
        "offer_window_s": offer_window_s,
        "fund_deadline_s": fund_deadline_s,
        "capture_grace_s": 120,
        "pending_wait_s": 120,
        "max_refill_waves": 1,
        "authorization_age_guard_s": 216000,
    }


async def add_user(session: AsyncSession, *, role: str = "buyer", tag: str = "user") -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', CAST(:role AS user_role), :tag)"
        ),
        {"id": user_id, "email": f"{tag}-{user_id}@example.test", "role": role, "tag": tag},
    )
    return user_id


async def build_world(
    session: AsyncSession,
    *,
    lot_status: str = "AWARDED",
    mode: str = "authorize_capture",
    router_name: str = "single_seller",
    seats: int = 3,
    min_seats: int = 2,
    seated: int = 2,
    waitlisted: int = 1,
    priced_out: int = 0,
    total_cents: int = TOTAL_CENTS,
    cap_cents: int = CAP_CENTS,
    moq: int = 2,
    tier_index: int = 0,
    pool_status: str = "ALLOCATED",
    fund_deadline_at: datetime | None = None,
    offer_window_s: int = 180,
    fund_deadline_s: int = 600,
    award_valid_in: int = 3600,
    with_award: bool = True,
) -> World:
    """Insert one lot with its award and allocations; return the handles tests need."""
    now = await DbClock().db_now(session)
    admin_id = await add_user(session, role="admin", tag="admin")
    merchant_user_id = await add_user(session, tag="merchant")
    merchant_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO merchants (id, user_id, display_name) VALUES (:id, :user, 'Demo Merchant')"
        ),
        {"id": merchant_id, "user": merchant_user_id},
    )
    pool_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', CAST(:status AS pool_status), 'Monitor pool', "
            "CAST(:template AS jsonb), CAST(:plan AS jsonb), CAST(:timeline AS jsonb), false, "
            "'allocation_v1', :rules_hash, :admin)"
        ),
        {
            "id": pool_id,
            "status": "OPEN",
            "template": json.dumps(
                {
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
                    "zones": [
                        {"zone_id": ZONE_ID, "label": "US East", "regions": ["NY", "NJ", "PA"]}
                    ],
                }
            ),
            "plan": json.dumps(
                [{"zone_id": ZONE_ID, "lots": [{"seats": seats, "min_seats": min_seats}]}]
            ),
            "timeline": json.dumps(
                timeline(now, offer_window_s=offer_window_s, fund_deadline_s=fund_deadline_s)
            ),
            "rules_hash": "a" * 64,
            "admin": admin_id,
        },
    )
    lot_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, payment_router, payment_mode, bid_open_at, bid_close_at) "
            "VALUES (:id, :pool, :zone, 0, 1, :seats, :min_seats, CAST(:status AS lot_status), "
            "CAST(:router AS payment_router), CAST(:mode AS payment_mode), :now, :now)"
        ),
        {
            "id": lot_id,
            "pool": pool_id,
            "zone": ZONE_ID,
            "seats": seats,
            "min_seats": min_seats,
            "status": lot_status,
            "router": router_name,
            "mode": mode,
            "now": now,
        },
    )

    entry_ids: list[UUID] = []
    user_ids: list[UUID] = []
    for index in range(seated + waitlisted + priced_out):
        user_id = await add_user(session, tag=f"buyer{index}")
        entry_id = uuid4()
        request = {
            "v": 1,
            "pool_id": str(pool_id),
            "product_key": "monitor-27-4k",
            "variant": "black",
            "condition": "NEW",
            "quantity": 1,
            "currency": "USD",
            "delivery": {"zone_id": ZONE_ID, "region": "NY", "country": "US"},
            "required_by": "2026-11-30",
            "max_total_cents": cap_cents,
            "firm": [],
            "preferences": [],
        }
        await session.execute(
            text(
                "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, "
                "request_hash, cap_cents, zone_id, status, submitted_via) "
                "VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, :cap, :zone, "
                "'ELIGIBLE', 'human')"
            ),
            {
                "id": entry_id,
                "pool": pool_id,
                "user": user_id,
                "request": json.dumps(request),
                "hash": "b" * 64,
                "cap": cap_cents,
                "zone": ZONE_ID,
            },
        )
        entry_ids.append(entry_id)
        user_ids.append(user_id)

    totals = {
        str(entry_id): {
            "item_cents": ITEM_CENTS,
            "shipping_cents": SHIPPING_CENTS,
            "tax_cents": TAX_CENTS,
            "total_cents": total_cents,
        }
        for entry_id in entry_ids
    }
    if with_award:
        award_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, "
                "item_cents, moq, totals, valid_until, rule_version, award_hash) "
                "VALUES (:id, :lot, NULL, :merchant, :tier, :item, :moq, "
                "CAST(:totals AS jsonb), :valid_until, 'ranking_v1', :hash)"
            ),
            {
                "id": award_id,
                "lot": lot_id,
                "merchant": merchant_id,
                "tier": tier_index,
                "item": ITEM_CENTS,
                "moq": moq,
                "totals": json.dumps(totals),
                "valid_until": now + timedelta(seconds=award_valid_in),
                "hash": "0" * 64,
            },
        )
        await session.execute(
            text("UPDATE lots SET award_id = :award WHERE id = :lot"),
            {"award": award_id, "lot": lot_id},
        )

    for index, entry_id in enumerate(entry_ids):
        if index < seated:
            status = "SEATED"
        elif index < seated + priced_out:
            status = "PRICED_OUT"
        else:
            status = "WAITLISTED"
        await session.execute(
            text(
                "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, "
                "lot_id, status) VALUES (:id, :pool, :entry, :zone, :rank, :hash, :lot, "
                "CAST(:status AS allocation_status))"
            ),
            {
                "id": uuid4(),
                "pool": pool_id,
                "entry": entry_id,
                "zone": ZONE_ID,
                "rank": index + 1,
                "hash": "c" * 64,
                "lot": None if status == "WAITLISTED" else lot_id,
                "status": status,
            },
        )
    if fund_deadline_at is not None:
        await session.execute(
            text("UPDATE lots SET fund_deadline_at = :at WHERE id = :lot"),
            {"at": fund_deadline_at, "lot": lot_id},
        )
    # The entry trigger admits rows only into an OPEN pool; the requested status is
    # what the lot's lifecycle would have reached afterwards.
    await session.execute(
        text("UPDATE pools SET status = CAST(:status AS pool_status) WHERE id = :pool"),
        {"status": pool_status, "pool": pool_id},
    )
    return World(
        session=session,
        pool_id=pool_id,
        lot_id=lot_id,
        merchant_id=merchant_id,
        merchant_user_id=merchant_user_id,
        entry_ids=entry_ids,
        user_ids=user_ids,
        totals=totals,
        now=now,
        ports=make_ports(now),
    )


def open_handler(world: World) -> OpenCheckoutHandler:
    return OpenCheckoutHandler(
        clock=world.ports.clock,
        audit=world.ports.audit,
        jobs=world.ports.jobs,
        notifier=world.ports.notifier,
        allocations=PostgresAllocationRead(),
    )


async def order_rows(session: AsyncSession, lot_id: UUID) -> list[tuple[Any, ...]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, entry_id, status, total_cents, offer_expires_at FROM buyer_orders "
                "WHERE lot_id = :lot ORDER BY created_at"
            ),
            {"lot": lot_id},
        )
    ).all()
    return [tuple(row) for row in rows]


async def lot_row(session: AsyncSession, lot_id: UUID) -> Any:
    return (
        await session.execute(
            text(
                "SELECT status, fund_deadline_at, refill_cutoff_at, refill_waves FROM lots "
                "WHERE id = :lot"
            ),
            {"lot": lot_id},
        )
    ).first()


# --------------------------------------------------------------------- PT-08


async def test_pt08_offers_fill_seats_and_refill_the_priced_out_vacancy(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance (PT-08): offers stay within seats and refill a vacancy."""
    world = await build_world(db_session, seats=3, seated=2, priced_out=1, waitlisted=1)
    handler = open_handler(world)

    await handler.open(db_session, {"lot_id": str(world.lot_id)})

    rows = await order_rows(db_session, world.lot_id)
    assert len(rows) == 3
    assert all(str(row[2]) == "OFFERED" for row in rows)
    priced_out_entry = world.entry_ids[2]
    waitlist_entry = world.entry_ids[3]
    # Two seated offers plus the waitlisted entry that took the priced-out seat.
    assert {row[1] for row in rows} == {*world.entry_ids[:2], waitlist_entry}
    assert priced_out_entry not in {row[1] for row in rows}
    # The priced-out seat's entry is replaced by the waitlisted entry (N12).
    assert waitlist_entry in {row[1] for row in rows}
    allocation = await db_session.scalar(
        text("SELECT status FROM allocations WHERE entry_id = :entry"),
        {"entry": waitlist_entry},
    )
    assert str(allocation) == "SEATED"
    assert str((await lot_row(db_session, world.lot_id))[0]) == "CHECKOUT_OPEN"


async def test_open_checkout_never_offers_more_than_the_seats(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance (I8): three seated entries on two seats create two offers."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    assert len(await order_rows(db_session, world.lot_id)) == 2


async def test_open_checkout_sets_the_deadlines_from_the_timeline(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance: ``fund_deadline_at`` and ``refill_cutoff_at`` are stored."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})

    status, fund_deadline_at, refill_cutoff_at, _ = await lot_row(db_session, world.lot_id)
    assert fund_deadline_at == world.now + timedelta(seconds=600)
    assert refill_cutoff_at == fund_deadline_at
    rows = await order_rows(db_session, world.lot_id)
    assert all(row[4] == world.now + timedelta(seconds=180) for row in rows)


async def test_open_checkout_schedules_offer_expiry_per_order_and_one_try_fund(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance: ``offer.expire`` per order, one deadline ``lot.try_fund``."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})

    jobs = world.ports.jobs.jobs
    expires = [job for job in jobs if job.kind == "offer.expire"]
    try_fund = [job for job in jobs if job.kind == "lot.try_fund"]
    assert len(expires) == 3
    assert all(job.run_at == world.now + timedelta(seconds=180) for job in expires)
    assert len(try_fund) == 1
    assert try_fund[0].run_at == world.now + timedelta(seconds=600)
    assert try_fund[0].dedupe_key == f"try_fund:{world.lot_id}"


async def test_open_checkout_writes_ls05_audit_and_notifies_each_buyer(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance: LS-05 runs through the whitelist with audit and notify."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})

    actions = [row["row"]["action"] for row in world.ports.audit.rows]
    assert actions == ["lot.checkout_open"]
    assert world.ports.audit.rows[0]["row"]["payload"]["transition_id"] == "LS-05"
    assert {call.user_id for call in world.ports.notifier.calls} == set(world.user_ids[:3])
    assert [call.kind for call in world.ports.notifier.calls] == ["buyer_order.offered"] * 3


async def test_vault_mode_enqueues_the_charge_instead_of_an_offer_timer(
    db_session: AsyncSession,
) -> None:
    """T04A01 acceptance (vault-charge.md section 3): vault mode has no offer window."""
    world = await build_world(db_session, seats=2, seated=2, waitlisted=0, mode="vault_charge")
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})

    kinds = [job.kind for job in world.ports.jobs.jobs]
    assert kinds.count("order.vault_charge") == 2
    assert "offer.expire" not in kinds
    rows = await order_rows(db_session, world.lot_id)
    assert all(row[4] == world.now + timedelta(seconds=600) for row in rows)


async def test_open_checkout_is_silent_on_a_replay(db_session: AsyncSession) -> None:
    """T04A01 acceptance: a replay writes no order, job, audit row or notification."""
    world = await build_world(db_session, seats=3, seated=2, waitlisted=1)
    handler = open_handler(world)
    await handler.open(db_session, {"lot_id": str(world.lot_id)})
    jobs = len(world.ports.jobs.jobs)
    audits = len(world.ports.audit.rows)
    notified = len(world.ports.notifier.calls)
    orders = len(await order_rows(db_session, world.lot_id))

    await handler.open(db_session, {"lot_id": str(world.lot_id)})

    assert len(world.ports.jobs.jobs) == jobs
    assert len(world.ports.audit.rows) == audits
    assert len(world.ports.notifier.calls) == notified
    assert len(await order_rows(db_session, world.lot_id)) == orders


async def test_a_lot_that_is_not_awarded_is_left_alone(db_session: AsyncSession) -> None:
    """T04A01: only the AWARDED to CHECKOUT_OPEN edge exists for this trigger."""
    world = await build_world(db_session, lot_status="CHECKOUT_OPEN")
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    assert world.ports.jobs.jobs == []
    assert world.ports.audit.rows == []
