"""Seed the local demo database with one coherent story per role.

Run against the loopback ``fairpool`` database by default:

    .venv/Scripts/python.exe tools/demo_seed.py
    .venv/Scripts/python.exe tools/demo_seed_check.py    # read-only proof

The local database URL is derived from ``TEST_DATABASE_URL`` with database name
``fairpool``. ``DEMO_SEED_HOSTED=1`` explicitly selects the configured app database
without resetting it. ``DEMO_SEED_PASSWORD`` is the one demo password:
it is read from the environment, never printed and never accepted on the command
line (I14).

What the demo shows:

* the merchant console -- a demand board with two lots still in bidding and a
  waitlisted buyer, an active bid in checkout, a funded lot with shipments and a
  failed lot that ended at net zero;
* the buyer console -- an action-required offer, a captured order and a refunded
  order, plus the same six buyers behind every entry receipt;
* discovery -- six open products, varied participation, published terms and signed
  entries; existing published windows are never extended by a repeat run;
* the simulation -- one SIMULATION pool with 10,000 allocated entries that never
  appears in the public lists.

Every pool is created by the app's own services (create, publish, open, join,
close, seed, allocate, force-award, open-checkout, authorize, capture, void,
refund). No PayPal host is called: the payments router is the offline ``fake``
one and its provider ids are demo-shaped and prefixed ``DEMO-``. Every account
uses ``DEMO_SEED_PASSWORD``.

A second run reuses the pools it already owns (found by title and creator), does
not duplicate entries, offers, captures, ledger facts, bids or shipments, and
only refreshes the interactive windows (bidding close, offer expiry) plus the
account roles, passwords and attestations.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import DateTime, cast, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from fairpool.fakes.payments import FakePayPalGateway  # noqa: E402

#: Fixed namespace: ids derived from a label are stable across runs.
DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "fairpool/demo-seed/v1")

BUYER_EMAILS = [f"demo-buyer-{index}@fairpool.test" for index in range(1, 7)]
MERCHANT_EMAILS = ["demo-merchant@fairpool.test", "demo-merchant-2@fairpool.test"]
ADMIN_EMAIL = "demo-admin@fairpool.test"

#: Demo-shaped provider references: recognisable, and never a PayPal identifier.
DEMO_PROVIDER_PREFIX = "DEMO-"

#: One delivered price per seat (flat_delivered), 2 x 47_000 = 94_000.
ITEM_CENTS = 47_000

SHIPPING = {
    "name": "Demo Buyer",
    "line1": "1 Demo Street",
    "line2": None,
    "city": "New York",
    "region": "NY",
    "postal_code": "10001",
    "country_code": "US",
}

POOL_SPECS: list[dict[str, Any]] = [
    {
        "slug": "monitor",
        "title": "27-inch 4K monitor",
        "product_key": "monitor-27-4k",
        "bundle": ["monitor", "stand", "power cable"],
        "lots": [{"seats": 3, "min_seats": 1}, {"seats": 2, "min_seats": 2}],
        "buyers": [1, 2, 3, 4, 5, 6],
        "bid_window_s": 6 * 3600,
        "offer_window_s": 7200,
        "fund_deadline_s": 6 * 3600,
    },
    {
        "slug": "headphones",
        "title": "Wireless over-ear headphones",
        "product_key": "headphones-over-ear",
        "bundle": ["headphones", "carry case", "usb-c cable"],
        "lots": [{"seats": 2, "min_seats": 2}],
        "buyers": [1, 2],
        "bid_window_s": 900,
        "offer_window_s": 2 * 3600,
        "fund_deadline_s": 6 * 3600,
    },
    {
        "slug": "desk",
        "title": "Walnut standing desk",
        "product_key": "desk-standing-walnut",
        "bundle": ["desk top", "frame", "hardware"],
        "lots": [{"seats": 2, "min_seats": 2}],
        "buyers": [1, 4],
        "bid_window_s": 900,
        "offer_window_s": 2 * 3600,
        "fund_deadline_s": 6 * 3600,
    },
    {
        "slug": "chair",
        "title": "Ergonomic chair",
        "product_key": "chair-ergonomic",
        "bundle": ["chair", "lumbar support", "assembly guide"],
        "lots": [{"seats": 2, "min_seats": 2}],
        "buyers": [2, 3],
        "bid_window_s": 900,
        "offer_window_s": 2 * 3600,
        "fund_deadline_s": 6 * 3600,
    },
]

DISCOVERY_SPECS = [
    (
        "27-inch 4K monitor with adjustable stand",
        "monitor-27-4k",
        "Matte black",
        ["monitor", "adjustable stand", "power cable"],
        4,
        60_000,
    ),
    (
        "Ceramic electric kettle",
        "kettle-ceramic",
        "Chalk white · 1.5 L",
        ["kettle", "power base"],
        2,
        8_000,
    ),
    (
        "Wireless noise-cancelling headphones",
        "headphones-wireless",
        "Graphite · over ear",
        ["headphones", "carry case", "charging cable"],
        5,
        18_000,
    ),
    (
        "Compact mechanical keyboard",
        "keyboard-compact",
        "75% layout · graphite",
        ["keyboard", "usb-c cable", "keycap puller"],
        3,
        12_000,
    ),
    (
        "Adjustable desk lamp",
        "lamp-adjustable",
        "Sand · warm white",
        ["lamp", "power adapter"],
        1,
        7_000,
    ),
    (
        "USB-C desktop dock",
        "dock-usbc",
        "Space grey · 8 ports",
        ["dock", "usb-c cable", "power adapter"],
        0,
        14_000,
    ),
]


def demo_id(label: str) -> UUID:
    """A deterministic id for a demo-owned row (bids, shipments, the sim pool)."""
    return uuid5(DEMO_NAMESPACE, label)


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        raise SystemExit("missing .env at the repository root")
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def loopback_database_url() -> str:
    """The loopback ``fairpool`` URL, built from TEST_DATABASE_URL only.

    The task owns the local demo database; the hosted DATABASE_URL in ``.env`` is
    never used by this tool, so an accidental run cannot write demo rows there.
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        raise SystemExit("TEST_DATABASE_URL is required to locate the loopback database")
    parts = urlsplit(test_url)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("TEST_DATABASE_URL does not point at a loopback host")
    if not parts.username:
        raise SystemExit("TEST_DATABASE_URL carries no user")
    return urlunsplit((parts.scheme, parts.netloc, "/fairpool", parts.query, parts.fragment))


class DemoGateway(FakePayPalGateway):
    """The offline fake router, with DEMO-prefixed ids and one payer per order.

    A subclass of the fake gateway on purpose: the checkout flow, idempotency keys
    and transitions are the production ones; only the provider is offline. The
    prefix makes every stored reference visibly demo-shaped, and a distinct payer
    per order lets two buyers pass ``DEDUPE_MODE=two_keys``.
    """

    def _id(self, key: str) -> str:
        return DEMO_PROVIDER_PREFIX + demo_id(f"provider:{key}").hex

    async def create_order(self, req: Any) -> Any:
        result = await super().create_order(req)
        payer = DEMO_PROVIDER_PREFIX + "PAYER-" + demo_id(f"payer:{req.buyer_order_id}").hex[:16]
        updated = replace(result, payer_id=payer)
        self.orders[result.id] = updated
        return updated


async def sync_account(
    identity: Any,
    session: Any,
    *,
    email: str,
    display_name: str,
    role: str,
    secret: str,
) -> UUID:
    """Create or reuse one demo account, with this run's password and role."""
    from fairpool.domain.errors import ApplicationError

    try:
        created = await identity.register(
            session, email=email, password=secret, display_name=display_name
        )
        user_id = UUID(str(created["user_id"]))
    except ApplicationError:
        found = await session.scalar(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        )
        if found is None:
            raise
        user_id = UUID(str(found))
    # An earlier run may own this address: only the login secret and role move.
    hashed = await asyncio.to_thread(identity.hasher.hash, secret)
    await session.execute(
        text(
            "UPDATE users SET password_hash = :hash, display_name = :name, "
            "role = CAST(:role AS user_role) WHERE id = :id"
        ),
        {"hash": hashed, "name": display_name, "role": role, "id": user_id},
    )
    await session.flush()
    return user_id


def pool_input(spec: dict[str, Any], *, now: datetime | None = None) -> Any:
    """One closed ``PoolInput``; the demo closes immediately and runs in one zone."""
    from fairpool.domain.pool_config import (
        LotSize,
        PoolInput,
        Template,
        Timeline,
        Zone,
        ZonePlan,
    )

    now = now if now is not None else datetime.now(UTC)
    return PoolInput(
        title=spec["title"],
        template=Template(
            product_key=spec["product_key"],
            variant=None,
            title=spec["title"],
            condition="NEW",
            quantity=1,
            currency="USD",
            bundle_contents=spec["bundle"],
            delivery_sla_days=7,
            fund_by="2026-11-30",
            min_return_days=30,
            zones=[Zone(zone_id="US-EAST", label="US East", regions=["NY", "NJ", "PA"])],
        ),
        lot_plan=[
            ZonePlan(
                zone_id="US-EAST",
                lots=[
                    LotSize(seats=lot["seats"], min_seats=lot["min_seats"]) for lot in spec["lots"]
                ],
            )
        ],
        timeline=Timeline(
            open_at=now + timedelta(minutes=10),
            close_at=now + timedelta(hours=2),
            bid_window_s=spec["bid_window_s"],
            offer_window_s=spec["offer_window_s"],
            fund_deadline_s=spec["fund_deadline_s"],
        ),
        require_paypal_link=False,
    )


async def find_pool(session: Any, *, title: str, admin_id: UUID) -> UUID | None:
    """The demo pool already created by an earlier run, if any; its links stay stable."""
    from fairpool.db.models.catalog import Pool
    from fairpool.db.models.enums import PoolMode

    return await session.scalar(
        select(Pool.id)
        .where(
            Pool.title == title,
            Pool.created_by == admin_id,
            Pool.mode == PoolMode.LIVE_SANDBOX,
        )
        .order_by(Pool.created_at)
        .limit(1)
    )


async def create_pool(session: Any, pools: Any, admin_id: UUID, spec: dict[str, Any]) -> Any:
    pool = await pools.create(session, actor_id=admin_id, payload=pool_input(spec))
    await pools.publish(session, pool.id, actor_id=admin_id)
    return pool


async def seed_discovery(session: Any, *, pools: Any, joins: Any, admin_id: UUID) -> list[UUID]:
    """T09A03: leave six joinable pools; never extend an existing published window."""
    from fairpool.db.models.catalog import Pool, PoolEntry
    from fairpool.modules.intake.manual import ManualIntakeService

    now = await pools.clock.db_now(session)
    manual = ManualIntakeService(pools.audit)
    result: list[UUID] = []
    for index, (title, key, variant, bundle, buyers, cap) in enumerate(DISCOVERY_SPECS):
        pool = await session.scalar(
            select(Pool)
            .where(
                Pool.created_by == admin_id,
                Pool.title == title,
                Pool.status == "OPEN",
                cast(Pool.timeline["close_at"].astext, DateTime(timezone=True)) > now,
            )
            .order_by(Pool.created_at.desc())
            .limit(1)
        )
        if pool is None:
            payload = pool_input(
                {
                    "title": title,
                    "product_key": key,
                    "bundle": bundle,
                    "lots": [{"seats": 12, "min_seats": 6}, {"seats": 12, "min_seats": 6}],
                    "bid_window_s": 3600,
                    "offer_window_s": 1800,
                    "fund_deadline_s": 21600,
                },
                now=now,
            )
            payload.template.variant = variant
            payload.template.fund_by = (now + timedelta(days=21)).date().isoformat()
            payload.timeline.open_at = now + timedelta(seconds=1)
            payload.timeline.close_at = now + timedelta(days=2 + index)
            pool = await pools.create(session, actor_id=admin_id, payload=payload)
            pool_id = pool.id
            await pools.publish(session, pool_id, actor_id=admin_id)
            # I15: wait for the published DB deadline; open rechecks it under lock.
            wall_now = await pools.clock.db_wall_now(session)
            if wall_now < payload.timeline.open_at:
                await asyncio.sleep((payload.timeline.open_at - wall_now).total_seconds())
            await pools.open(session, {"pool_id": str(pool_id)})
        pool_id = pool.id
        result.append(pool_id)
        for email in BUYER_EMAILS[:buyers]:
            buyer_id = await user_id_of(session, email)
            if await session.scalar(
                select(PoolEntry.id).where(
                    PoolEntry.pool_id == pool_id, PoolEntry.user_id == buyer_id
                )
            ):
                continue
            request = await manual.confirm(
                session,
                user_id=buyer_id,
                pool_id=pool_id,
                payload={
                    "delivery": {"region": "NY"},
                    "required_by": (now + timedelta(days=30)).date().isoformat(),
                    "max_total_cents": cap,
                    "firm": [],
                    "preferences": [],
                },
            )
            outcome = await joins.join(
                session,
                pool_id=pool_id,
                user_id=buyer_id,
                confirmed_request_id=request.id,
                idempotency_key=f"demo:discover:{pool_id}:{buyer_id}",
            )
            if outcome.status_code != 201:
                raise SystemExit("discovery demo join refused")
    return result


async def settle_pool(session: Any, handlers: dict[str, Any], pool_id: UUID) -> None:
    """Run the three declared follow-ups in order, without touching other lots.

    The job queue is shared with every earlier run and test in this database, so a
    global ``drain`` would execute an unrelated live authorization against the demo
    gateway. The demo calls the same handlers the worker would, for its own pool only;
    the queued rows stay harmless because each handler is idempotent.
    """
    await handlers["pool.seed"](session, {"pool_id": str(pool_id)})
    await handlers["pool.allocate"](session, {"pool_id": str(pool_id)})
    for row in await lot_ids(session, pool_id):
        if row.status == "PLANNED":
            await handlers["lot.bid_open"](session, {"lot_id": str(row.id)})
    try:
        await handlers["search.index"](
            session,
            {"pool_id": str(pool_id), "doc_kind": "pool", "doc_id": str(pool_id)},
        )
    except Exception:  # noqa: BLE001 - retrieval is advisory (rule 23), never a gate
        pass


async def register_proposal(
    session: Any, intake: Any, ai: Any, *, pool_id: UUID, user_id: UUID
) -> None:
    """Teach ``FakeAI`` the one proposal this pool's message maps to."""
    from tests.integration.test_pipeline_fakes import EAST_MESSAGE, PROPOSALS

    await intake.propose(session, user_id=user_id, message=EAST_MESSAGE, pool_id_override=pool_id)
    ai.register_hash(
        ai.calls[-1].input_hash,
        {
            "pool_id": str(pool_id),
            "match_confidence": "high",
            "ambiguities": [],
            "clarifying_question": None,
            **PROPOSALS["NY"],
        },
    )


async def join_buyer(
    session: Any,
    *,
    intake: Any,
    joins: Any,
    ai: Any,
    pool_id: UUID,
    user_id: UUID,
    label: str,
) -> UUID:
    """One buyer from a message to a signed entry receipt through the real services."""
    from tests.integration.test_pipeline_fakes import EAST_MESSAGE

    answer = await intake.propose(
        session, user_id=user_id, message=EAST_MESSAGE, pool_id_override=pool_id
    )
    if answer["status"] != "READY_TO_CONFIRM":
        ai.register_hash(
            ai.calls[-1].input_hash,
            {
                "pool_id": str(pool_id),
                "match_confidence": "high",
                "ambiguities": [],
                "clarifying_question": None,
                "condition": "NEW",
                "quantity": 1,
                "delivery": {"region": "NY"},
                "required_by": "2026-12-15",
                "max_total": {"amount": "600.00", "currency": "USD"},
                "firm_requirements": [],
                "preferences": [],
            },
        )
        answer = await intake.propose(
            session, user_id=user_id, message=EAST_MESSAGE, pool_id_override=pool_id
        )
    if answer["status"] != "READY_TO_CONFIRM":
        raise SystemExit(f"intake did not produce a confirmation card for {label}")
    card = answer["confirmation_card"]
    record = await intake.confirm(
        session, user_id=user_id, proposal_id=UUID(str(card["proposal_id"]))
    )
    outcome = await joins.join(
        session,
        pool_id=pool_id,
        user_id=user_id,
        confirmed_request_id=record.id,
        idempotency_key=f"demo:{label}",
    )
    if outcome.status_code != 201:
        raise SystemExit(f"join failed for {label}: {outcome.body}")
    return UUID(str(outcome.body["entry_id"]))


def bid_structured(spec: dict[str, Any], *, price_cents: int, capacity: int) -> dict[str, Any]:
    """A complete flat-delivered bid body; only used for demo rows."""
    return {
        "v": 1,
        "product_key": spec["product_key"],
        "condition": "NEW",
        "bundle_contents": spec["bundle"],
        "capacity": capacity,
        "target_quantity": 2,
        "moq": 1,
        "tiers": [{"min_qty": 1, "item_price_cents": price_cents}],
        "shipping_cents_by_zone": {},
        "tax": {"mode": "INCLUDED"},
        "delivery": {"sla_days": 7},
        "returns": {"days": 30},
        "valid_until": "2026-12-31T00:00:00Z",
        "total_capacity": capacity,
        "evidence": {"note": "demo units reserved", "url": None},
    }


async def _insert_decided_bid(
    session: Any,
    *,
    lot_id: UUID,
    merchant_id: UUID,
    spec: dict[str, Any],
    signing_seed_bytes: bytes,
    now: datetime,
    status: Any,
    price_cents: int,
    capacity: int,
) -> UUID:
    """A decided bid with a signed receipt, deliberately demo-shaped."""
    from fairpool.db.models.auction import Bid, BidRevision
    from fairpool.domain import hashing
    from fairpool.modules.pools.receipts import format_received_at

    existing = await session.scalar(
        text("SELECT id FROM bids WHERE lot_id = :lot AND merchant_id = :merchant"),
        {"lot": lot_id, "merchant": merchant_id},
    )
    if existing is not None:
        return UUID(str(existing))

    bid_id = demo_id(f"bid:{lot_id}:{merchant_id}")
    structured = bid_structured(spec, price_cents=price_cents, capacity=capacity)
    received = format_received_at(now)
    receipt_hash = hashing.bid_receipt_hash(str(bid_id), 1, structured, received)
    signature = hashing.sign_ed25519(
        hashing.bid_receipt_payload(str(bid_id), 1, receipt_hash), signing_seed_bytes
    )
    session.add(
        Bid(
            id=bid_id,
            lot_id=lot_id,
            merchant_id=merchant_id,
            status=status,
            current_revision=1,
        )
    )
    session.add(
        BidRevision(
            id=demo_id(f"bid-revision:{bid_id}"),
            bid_id=bid_id,
            revision=1,
            structured=structured,
            quote_text="Demo quote for the demo dataset.",
            notes=None,
            confirmed_at=now,
            receipt_hash=receipt_hash,
            receipt_signature=signature,
        )
    )
    await session.flush()
    return bid_id


async def insert_lost_bid(
    session: Any,
    *,
    lot_id: UUID,
    merchant_id: UUID,
    spec: dict[str, Any],
    signing_seed_bytes: bytes,
    now: datetime,
) -> UUID:
    from fairpool.db.models.enums import BidStatus

    return await _insert_decided_bid(
        session,
        lot_id=lot_id,
        merchant_id=merchant_id,
        spec=spec,
        signing_seed_bytes=signing_seed_bytes,
        now=now,
        status=BidStatus.LOST,
        price_cents=49_000,
        capacity=2,
    )


async def insert_awarded_bid(
    session: Any,
    *,
    lot_id: UUID,
    merchant_id: UUID,
    spec: dict[str, Any],
    signing_seed_bytes: bytes,
    now: datetime,
) -> UUID:
    """The bid the merchant console reads for a forced award (which writes none)."""
    from fairpool.db.models.enums import BidStatus

    return await _insert_decided_bid(
        session,
        lot_id=lot_id,
        merchant_id=merchant_id,
        spec=spec,
        signing_seed_bytes=signing_seed_bytes,
        now=now,
        status=BidStatus.AWARDED,
        price_cents=ITEM_CENTS,
        capacity=2,
    )


async def lot_ids(session: Any, pool_id: UUID) -> list[Any]:
    return (
        await session.execute(
            text(
                "SELECT id, lot_order, status::text AS status FROM lots WHERE pool_id = :pool "
                "ORDER BY lot_order"
            ),
            {"pool": pool_id},
        )
    ).all()


async def force_award(
    client: Any,
    csrf: str,
    *,
    lot_id: UUID,
    merchant_id: UUID,
    moq: int,
    item_cents: int,
) -> None:
    response = await client.post(
        f"/api/v1/admin/lots/{lot_id}/force-award",
        json={
            "merchant_id": str(merchant_id),
            "item_cents": item_cents,
            "tier_index": 0,
            "moq": moq,
            "valid_minutes": 720,
        },
        headers={"X-CSRF-Token": csrf},
    )
    if response.status_code != 201:
        raise SystemExit(f"force-award failed: {response.status_code} {response.text[:160]}")


async def orders_of(session: Any, lot_id: UUID) -> list[Any]:
    return (
        await session.execute(
            text(
                "SELECT bo.id, bo.status::text AS status, bo.total_cents, bo.entry_id, "
                "u.email AS email FROM buyer_orders bo "
                "JOIN pool_entries pe ON pe.id = bo.entry_id JOIN users u ON u.id = pe.user_id "
                "WHERE bo.lot_id = :lot ORDER BY bo.created_at, bo.id"
            ),
            {"lot": lot_id},
        )
    ).all()


async def authorize_and_approve(session: Any, surface: Any, order_id: UUID, shipping: Any) -> None:
    from fairpool.db.models.checkout import BuyerOrder

    await surface.authorize.continue_order(
        session, buyer_order_id=order_id, shipping=dict(shipping)
    )
    await surface.authorize.approved(session, buyer_order_id=order_id)
    await surface.authorize.authorize(session, {"buyer_order_id": str(order_id)})
    order = await session.get(BuyerOrder, order_id)
    if order is None or str(order.status) != "AUTHORIZED":
        raise SystemExit("authorize did not settle the demo seat")


async def refresh_windows(session: Any, *, pool_id: UUID, spec: dict[str, Any]) -> None:
    """Move the interactive deadlines forward on a reused pool.

    Pools keep their rows and, therefore, their links. Only the two windows a demo
    watches are rewritten: bidding close for the demand board, and offer expiry for
    the checkout story. Terminal pools (funded, failed) are left alone.
    """
    now = datetime.now(UTC)
    if spec["slug"] == "monitor":
        await session.execute(
            text(
                "UPDATE lots SET bid_open_at = :open, bid_close_at = :close WHERE pool_id = :pool"
            ),
            {
                "open": now - timedelta(minutes=5),
                "close": now + timedelta(seconds=spec["bid_window_s"]),
                "pool": pool_id,
            },
        )
        await session.execute(
            text(
                "UPDATE jobs SET run_at = :close WHERE status = 'PENDING' "
                "AND kind = 'lot.bid_close' AND payload->>'lot_id' IN ("
                "SELECT id::text FROM lots WHERE pool_id = :pool)"
            ),
            {"close": now + timedelta(seconds=spec["bid_window_s"]), "pool": pool_id},
        )
    elif spec["slug"] == "headphones":
        deadline = now + timedelta(seconds=spec["offer_window_s"])
        await session.execute(
            text(
                "UPDATE lots SET fund_deadline_at = :deadline, refill_cutoff_at = :deadline "
                "WHERE pool_id = :pool"
            ),
            {"deadline": now + timedelta(seconds=spec["fund_deadline_s"]), "pool": pool_id},
        )
        await session.execute(
            text(
                "UPDATE buyer_orders SET offer_expires_at = :deadline "
                "WHERE status = 'OFFERED' AND lot_id IN ("
                "SELECT id FROM lots WHERE pool_id = :pool)"
            ),
            {"deadline": deadline, "pool": pool_id},
        )
        await session.execute(
            text(
                "UPDATE jobs SET run_at = :deadline WHERE status = 'PENDING' "
                "AND kind = 'offer.expire' AND payload->>'buyer_order_id' IN ("
                "SELECT id::text FROM buyer_orders WHERE status = 'OFFERED' "
                "AND lot_id IN (SELECT id FROM lots WHERE pool_id = :pool))"
            ),
            {"deadline": deadline, "pool": pool_id},
        )
    await session.flush()


async def scenario(
    session: Any,
    *,
    client: Any,
    csrf: str,
    admin_id: UUID,
    merchants: dict[str, UUID],
    handlers: dict[str, Any],
    surface: Any,
    intake: Any,
    joins: Any,
    ai: Any,
    pools: Any,
    config: Any,
) -> dict[str, Any]:
    """Create (or reuse) the five demo pools and drive their stories."""
    from fairpool.modules.sim.run import run_sim
    from tests.integration.test_pipeline_fakes import move_timeline

    created: dict[str, Any] = {}
    for spec in POOL_SPECS:
        pool_id = await find_pool(session, title=spec["title"], admin_id=admin_id)
        if pool_id is not None:
            await refresh_windows(session, pool_id=pool_id, spec=spec)
            created[spec["slug"]] = {"id": pool_id, "reused": True}
            continue

        pool = await create_pool(session, pools, admin_id, spec)
        pool_id = pool.id
        await move_timeline(session, pool_id, key="open_at", seconds=-120)
        # The row is in this session's identity map with the future window, so the
        # handler would read a stale timeline without this (I15).
        session.expire_all()
        await handlers["pool.open"](session, {"pool_id": str(pool_id)})
        await register_proposal(session, intake, ai, pool_id=pool_id, user_id=UUID(str(admin_id)))
        for slot in spec["buyers"]:
            await join_buyer(
                session,
                intake=intake,
                joins=joins,
                ai=ai,
                pool_id=pool_id,
                user_id=await user_id_of(session, BUYER_EMAILS[slot - 1]),
                label=f"{spec['slug']}:{BUYER_EMAILS[slot - 1]}",
            )
        await move_timeline(session, pool_id, key="close_at", seconds=-60)
        session.expire_all()
        await handlers["pool.close"](session, {"pool_id": str(pool_id)})
        await settle_pool(session, handlers, pool_id)
        created[spec["slug"]] = {"id": pool_id, "reused": False}

    monitor = created["monitor"]["id"]
    headphones = created["headphones"]["id"]
    desk = created["desk"]["id"]
    chair = created["chair"]["id"]

    now = await session.scalar(text("SELECT now()"))
    if not isinstance(now, datetime):
        raise SystemExit("database clock returned a non-datetime value")
    signing = signing_seed_bytes(config)

    # ---------------------------------------------------------- pool 1: bidding
    monitor_lots = await lot_ids(session, monitor)
    if len(monitor_lots) != 2 or any(row.status != "BIDDING" for row in monitor_lots):
        raise SystemExit(f"pool 1 did not form two BIDDING lots: {monitor_lots}")

    # --------------------------------- headphone lot: award, offers, a LOST bid
    if not created["headphones"]["reused"]:
        headphones_lot = (await lot_ids(session, headphones))[0]
        await insert_lost_bid(
            session,
            lot_id=headphones_lot.id,
            merchant_id=merchants["beta"],
            spec=POOL_SPECS[1],
            signing_seed_bytes=signing,
            now=now,
        )
        await force_award(
            client,
            csrf,
            lot_id=headphones_lot.id,
            merchant_id=merchants["alpha"],
            moq=2,
            item_cents=ITEM_CENTS,
        )
        await handlers["lot.open_checkout"](session, {"lot_id": str(headphones_lot.id)})

    # ------------------------------------------ desk lot: capture to a funded lot
    if not created["desk"]["reused"]:
        desk_lot = (await lot_ids(session, desk))[0]
        await force_award(
            client,
            csrf,
            lot_id=desk_lot.id,
            merchant_id=merchants["alpha"],
            moq=2,
            item_cents=ITEM_CENTS,
        )
        await handlers["lot.open_checkout"](session, {"lot_id": str(desk_lot.id)})
        desk_orders = await orders_of(session, desk_lot.id)
        if len(desk_orders) != 2:
            raise SystemExit("the desk lot did not produce two offers")
        for order in desk_orders:
            await authorize_and_approve(session, surface, order.id, SHIPPING)
        await surface.funding.try_fund(session, {"lot_id": str(desk_lot.id)})
        for order in desk_orders:
            await surface.funding.capture(session, {"buyer_order_id": str(order.id)})
        await surface.funding.try_fund(session, {"lot_id": str(desk_lot.id)})
        await insert_shipments(session, lot_id=desk_lot.id, merchant_id=merchants["alpha"], now=now)

    # ---------------------------------------- chair lot: void, refund, net zero
    if not created["chair"]["reused"]:
        chair_lot = (await lot_ids(session, chair))[0]
        await insert_lost_bid(
            session,
            lot_id=chair_lot.id,
            merchant_id=merchants["alpha"],
            spec=POOL_SPECS[3],
            signing_seed_bytes=signing,
            now=now,
        )
        await force_award(
            client,
            csrf,
            lot_id=chair_lot.id,
            merchant_id=merchants["beta"],
            moq=2,
            item_cents=ITEM_CENTS,
        )
        await handlers["lot.open_checkout"](session, {"lot_id": str(chair_lot.id)})
        chair_orders = await orders_of(session, chair_lot.id)
        if len(chair_orders) != 2:
            raise SystemExit("the chair lot did not produce two offers")
        # Buyer 2 owns the captured-then-refunded seat; the other buyer's
        # authorization is the one voided (I4: both end at net zero).
        refunded = next((row for row in chair_orders if row.email == BUYER_EMAILS[1]), None)
        if refunded is None:
            raise SystemExit("buyer 2 is not on the chair lot")
        voided = next(row for row in chair_orders if row.id != refunded.id)
        for order in chair_orders:
            await authorize_and_approve(session, surface, order.id, SHIPPING)
        await surface.funding.try_fund(session, {"lot_id": str(chair_lot.id)})
        await surface.funding.capture(session, {"buyer_order_id": str(refunded.id)})
        await session.execute(
            text("UPDATE lots SET fund_deadline_at = now() - interval '1 second' WHERE id = :id"),
            {"id": chair_lot.id},
        )
        await session.flush()
        await surface.funding.try_fund(session, {"lot_id": str(chair_lot.id)})
        await surface.failure.finalize_fail(session, {"lot_id": str(chair_lot.id)})
        await surface.failure.run_void(
            session, {"buyer_order_id": str(voided.id), "void_source": "lot_failing"}
        )
        await surface.failure.run_refund(session, {"buyer_order_id": str(refunded.id)})
        await surface.failure.finalize_fail(session, {"lot_id": str(chair_lot.id)})

    # A forced award writes no bid row, but the merchant console lists awarded
    # bids; give each awarded merchant the bid it reads, on reused pools too.
    for pool, merchant_key, spec_index in (
        (headphones, "alpha", 1),
        (desk, "alpha", 2),
        (chair, "beta", 3),
    ):
        awarded_lot = (await lot_ids(session, pool))[0]
        await insert_awarded_bid(
            session,
            lot_id=awarded_lot.id,
            merchant_id=merchants[merchant_key],
            spec=POOL_SPECS[spec_index],
            signing_seed_bytes=signing,
            now=now,
        )

    # ---------------------------------------------------- simulation pool (10k)
    sim_pool_id = demo_id("pool:simulation-4k-monitor")
    await run_sim(
        session,
        {"entries": 10_000, "merchants": 40, "seed": 7},
        pool_id=sim_pool_id,
    )

    return {
        "monitor": monitor,
        "headphones": headphones,
        "desk": desk,
        "chair": chair,
        "sim": sim_pool_id,
    }


def signing_seed_bytes(config: Any) -> bytes:
    from fairpool.modules.pools.receipts import signing_seed

    return signing_seed(config.receipt_signing_key.get_secret_value())


async def user_id_of(session: Any, email: str) -> UUID:
    value = await session.scalar(
        text("SELECT id FROM users WHERE email = :email"), {"email": email}
    )
    if value is None:
        raise SystemExit("demo account disappeared between steps")
    return UUID(str(value))


async def insert_shipments(session: Any, *, lot_id: UUID, merchant_id: UUID, now: datetime) -> None:
    """Two shipment rows on the funded lot: one tracker submitted, one pending."""
    rows = (
        await session.execute(
            text(
                "SELECT bo.id FROM buyer_orders bo WHERE bo.lot_id = :lot "
                "AND bo.status = 'CAPTURED' ORDER BY bo.created_at, bo.id"
            ),
            {"lot": lot_id},
        )
    ).all()
    for index, row in enumerate(rows):
        await session.execute(
            text(
                "INSERT INTO shipments (id, lot_id, buyer_order_id, merchant_id, carrier, "
                "tracking_number, shipped_at, paypal_tracker_status) "
                "VALUES (:id, :lot, :order, :merchant, :carrier, :tracking, :shipped, :tracker) "
                "ON CONFLICT (buyer_order_id) DO NOTHING"
            ),
            {
                "id": demo_id(f"shipment:{row.id}"),
                "lot": lot_id,
                "order": row.id,
                "merchant": merchant_id,
                "carrier": ["Demo Freight", "Demo Parcel"][index % 2],
                "tracking": f"DEMO-TRK-{1000 + index}",
                "shipped": now,
                "tracker": None,
            },
        )
    await session.flush()


async def summary(session: Any, pools: dict[str, Any]) -> list[dict[str, Any]]:
    """The state table the report prints; ids are shortened, never provider ids."""
    rows = (
        await session.execute(
            text(
                "SELECT p.title, l.id AS lot_id, l.lot_order, l.seats, "
                "l.status::text AS lot_status, "
                "COALESCE((SELECT string_agg(bo.status::text, ',' ORDER BY bo.created_at) "
                "FROM buyer_orders bo WHERE bo.lot_id = l.id), '-') AS orders, "
                "COALESCE((SELECT count(*) FROM paypal_captures pc JOIN buyer_orders bo "
                "ON bo.id = pc.buyer_order_id WHERE bo.lot_id = l.id), 0) AS captures, "
                "COALESCE((SELECT sum(CASE WHEN le.kind = 'CAPTURE_COMPLETED' THEN le.amount_cents "
                "WHEN le.kind = 'REFUND_COMPLETED' THEN -le.amount_cents ELSE 0 END) "
                "FROM ledger_entries le WHERE le.lot_id = l.id), 0) AS net "
                "FROM lots l JOIN pools p ON p.id = l.pool_id WHERE p.id = ANY(:pools) "
                "ORDER BY p.title, l.lot_order"
            ),
            {"pools": list(pools.values())},
        )
    ).all()
    return [dict(row._mapping) for row in rows]


async def main() -> int:
    load_env()
    # Local by default; DEMO_SEED_HOSTED=1 is the explicit opt-in for the hosted demo
    # database, and it still refuses to touch anything but the configured URL.
    # The seeding process always runs in local mode (the admin demo helper is gated on
    # it); only the database target changes with the explicit hosted opt-in.
    os.environ["APP_ENV"] = "local"
    if os.environ.get("DEMO_SEED_HOSTED") != "1":
        os.environ["DATABASE_URL"] = loopback_database_url()
    os.environ["PAYMENT_ROUTER"] = "fake"
    os.environ["PAYMENT_MODE"] = "authorize_capture"
    os.environ["DEDUPE_MODE"] = "two_keys"
    os.environ["AI_ENABLED"] = "false"
    secret = os.environ.get("DEMO_SEED_PASSWORD")
    if not secret:
        raise SystemExit("no demo password: set DEMO_SEED_PASSWORD in .env")

    import httpx
    from fairpool.api.app import create_app
    from fairpool.api.deps import database_session
    from fairpool.config import Settings
    from fairpool.db.session import create_engine as build_engine
    from fairpool.domain.errors import ApplicationError
    from fairpool.fakes.ai import FakeAI
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.idempotency import PostgresIdempotencyStore
    from fairpool.modules.identity.service import IdentityService
    from fairpool.modules.intake.pipeline import IntakeService
    from fairpool.modules.intake.run_log import PostgresAiRunLogger
    from fairpool.modules.merchants.profile import MerchantProfileService
    from fairpool.modules.pools.join import JoinService
    from fairpool.modules.search.service import build_search_service
    from fairpool.wiring import checkout_services, pool_service, worker_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker

    config: Settings = Settings()
    engine = build_engine(config)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        identity = IdentityService(config.secret_key.get_secret_value(), DbClock())
        admin_id = await sync_account(
            identity,
            session,
            email=ADMIN_EMAIL,
            display_name="Demo Admin",
            role="admin",
            secret=secret,
        )
        for index, email in enumerate(MERCHANT_EMAILS):
            await sync_account(
                identity,
                session,
                email=email,
                display_name=f"Demo Merchant {'Alpha' if index == 0 else 'Beta'}",
                role="merchant",
                secret=secret,
            )
        for index, email in enumerate(BUYER_EMAILS):
            await sync_account(
                identity,
                session,
                email=email,
                display_name=f"Demo Buyer {index + 1}",
                role="buyer",
                secret=secret,
            )

        profile = MerchantProfileService(clock=DbClock(), demo=True)
        merchant_ids: dict[str, UUID] = {}
        for key, email, name in (
            ("alpha", MERCHANT_EMAILS[0], "Demo Merchant Alpha"),
            ("beta", MERCHANT_EMAILS[1], "Demo Merchant Beta"),
        ):
            merchant = await profile.upsert(
                session,
                user_id=await user_id_of(session, email),
                display_name=name,
                payee_email=None,
                paypal_merchant_id=None,
                attestations={
                    key: {"accepted": True}
                    for key in (
                        "inventory_reserved",
                        "map_compliance",
                        "delivery_terms_accurate",
                    )
                },
            )
            merchant_ids[key] = merchant.id

        surface = checkout_services(config)
        # The composition root builds the offline fake when PAYMENT_ROUTER=fake; the
        # demo wrapper only changes the id prefix and gives each order its own payer.
        demo_gateway = DemoGateway()
        surface.router.gateway = demo_gateway
        surface.funding.gateway = demo_gateway
        surface.failure.gateway = demo_gateway
        handlers = worker_handlers(config, surface)

        app = create_app(config)
        app.state.checkout_services = surface

        async def session_override() -> Any:
            yield session

        app.dependency_overrides[database_session] = session_override

        ai = FakeAI()
        search = build_search_service(config)
        intake = IntakeService(
            search=search,
            ai=ai,
            audit=PostgresAuditLog(),
            clock=DbClock(),
            run_logger=PostgresAiRunLogger(),
            model="fake-model",
        )
        joins = JoinService(
            DbClock(),
            PostgresAuditLog(),
            PostgresIdempotencyStore(),
            signing_seed=signing_seed_bytes(config),
            dedupe_mode=config.dedupe_mode,
        )

        # https because the session cookie is __Host- and always Secure; the ASGI
        # transport never leaves the process.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://localhost:8000"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": secret}
            )
            if response.status_code != 200:
                raise SystemExit(f"admin login failed: {response.status_code}")
            csrf = str(response.json()["csrf_token"])
            try:
                demo = await scenario(
                    session,
                    client=client,
                    csrf=csrf,
                    admin_id=admin_id,
                    merchants=merchant_ids,
                    handlers=handlers,
                    surface=surface,
                    intake=intake,
                    joins=joins,
                    ai=ai,
                    pools=pool_service(config),
                    config=config,
                )
                discovery = await seed_discovery(
                    session, pools=pool_service(config), joins=joins, admin_id=admin_id
                )
            except ApplicationError as error:
                raise SystemExit(f"demo seed refused a transition: {error.code}") from None
            await session.commit()

            rows = await summary(
                session,
                {
                    "monitor": demo["monitor"],
                    "headphones": demo["headphones"],
                    "desk": demo["desk"],
                    "chair": demo["chair"],
                },
            )
            links = await buyer_links(session, demo, base=config.frontend_base_url)

    if search.elastic is not None:
        await search.elastic.close()
    await engine.dispose()

    base = config.frontend_base_url.rstrip("/")
    target = "configured app database" if os.environ.get("DEMO_SEED_HOSTED") == "1" else "loopback"
    print(f"FairPool demo data ({target}, offline payments)")
    print("logins (password: DEMO_SEED_PASSWORD from .env):")
    for email in BUYER_EMAILS:
        print(f"  buyer      {email}")
    for email in MERCHANT_EMAILS:
        print(f"  merchant   {email}")
    print(f"  admin      {ADMIN_EMAIL}")
    print("merchant console:")
    for path in (
        "/merchant/demand",
        "/merchant/bids",
        "/merchant/fulfillment",
        "/merchant/profile",
    ):
        print(f"  {base}{path}")
    print("buyer links:")
    for label, url in links:
        print(f"  {label:<12} {url}")
    print("state:")
    print(f"  discovery: {len(discovery)} open pools with published terms and signed entries")
    for row in rows:
        net = int(row["net"])
        print(
            f"  {row['title']:<30} lot {row['lot_order']} "
            f"({str(row['lot_id'])[:8]}) {row['lot_status']:<14} "
            f"orders={row['orders']} captures={row['captures']} net={net}"
        )
    sim_entries = 10_000
    print("  simulation pool (10,000 entries, seed 7): SIMULATION only, not listed publicly")
    print(
        f"\n{len(rows)} demo lots across {len({r['title'] for r in rows})} pools, sim={sim_entries}"
    )
    return 0


async def buyer_links(session: Any, demo: dict[str, Any], *, base: str) -> list[tuple[str, str]]:
    """The two buyer stories: an action-required offer and the settled orders."""
    base = base.rstrip("/")
    links: list[tuple[str, str]] = []
    for label, email, pool_key, prefer in (
        ("buyer 1 offer", BUYER_EMAILS[0], "headphones", "OFFERED"),
        ("buyer 1 order", BUYER_EMAILS[0], "desk", "CAPTURED"),
        ("buyer 2 offer", BUYER_EMAILS[1], "headphones", "OFFERED"),
        ("buyer 2 order", BUYER_EMAILS[1], "chair", "REFUNDED"),
    ):
        order_id = await session.scalar(
            text(
                "SELECT bo.id FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
                "JOIN users u ON u.id = pe.user_id JOIN lots l ON l.id = bo.lot_id "
                "WHERE u.email = :email AND l.pool_id = :pool AND bo.status = :status "
                "ORDER BY bo.created_at LIMIT 1"
            ),
            {"email": email, "pool": demo[pool_key], "status": prefer},
        )
        if order_id is None:
            continue
        path = "offers" if prefer == "OFFERED" else "orders"
        links.append((label, f"{base}/{path}/{order_id}"))
    return links


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
