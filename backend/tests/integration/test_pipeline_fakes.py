"""IT-4 / T04X01: pool to funded lot, with ``FakeAI`` and the fake payment router.

One test, top to bottom, through the real services and the real wiring:

    create -> publish -> open -> 12 buyers through intake -> close -> demo seed ->
    allocate (two lots, one cancelled, an ordered waitlist) -> force-award ->
    open checkout (offers + refills from the waitlist) -> vault charges ->
    FUNDED -> audit chain verified -> public audit recomputed.

What makes it an integration test rather than a unit test is which objects run:
``wiring.pool_service``, ``wiring.checkout_services`` and ``wiring.worker_handlers``
build the production graph, the job rows in Postgres are claimed by the real
``PostgresJobQueue``, the audit rows are the chained ones ``PostgresAuditLog`` writes,
and the two services the checkout handlers read are the real
``PostgresAllocationRead`` and ``PostgresMerchantDirectory`` -- their ``calls`` lists
are asserted, so a fixture fake could not satisfy this test. Only the provider (the
gateway) and the model are fakes, which is exactly what IG-4 is about (I12, INT-1).

Two setup facts are the test's own arrangement, not a shortcut in the code:

* the deadlines are moved into the past with ``jsonb_set`` so the timers this test
  claims are due; the handlers still re-check them against the database clock (I15);
* the caps of two seated entries are set just below the award total *before* the
  awards, because a cap is only compared to an award when one exists and the seeded
  ranking decides who sits where. ``test_force_award_prices_out_a_seat_below_the_total``
  arranges its input the same way.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain import hashing
from fairpool.domain.pool_config import LotSize, PoolInput, Template, Timeline, Zone, ZonePlan
from fairpool.fakes.ai import FakeAI
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, key_from_config_value
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.intake.pipeline import IntakeService
from fairpool.modules.intake.run_log import PostgresAiRunLogger
from fairpool.modules.merchants.directory import PostgresMerchantDirectory
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import signing_seed
from fairpool.modules.search.service import build_search_service
from fairpool.wiring import (
    CheckoutServices,
    checkout_services,
    pool_service,
    worker_handlers,
)
from tests.integration.test_join_receipts import SEED, login, settings_for
from tests.unit.test_settings import vault_key

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "docs/contracts/vectors/fairness_v1.json").read_text("utf-8"))

ITEM_CENTS = 52_000
LOW_CAP_CENTS = 45_000
HIGH_CAP_CENTS = 60_000
REQUIRED_BY = "2026-12-15"
TOKEN_VALUE = "IT4-PAYMENT-TOKEN-SECRET-1234"
EAST_MESSAGE = (
    "I need the Studio 27-inch 4K monitor in black, delivered to NY by 2026-12-15, budget 600 USD"
)
WEST_MESSAGE = (
    "I need the Studio 27-inch 4K monitor in black, delivered to CA by 2026-12-15, budget 600 USD"
)
PROPOSALS = {
    "NY": {
        "condition": "NEW",
        "quantity": 1,
        "delivery": {"region": "NY"},
        "required_by": REQUIRED_BY,
        "max_total": {"amount": "600.00", "currency": "USD"},
        "firm_requirements": [],
        "preferences": [],
    },
    "CA": {
        "condition": "NEW",
        "quantity": 1,
        "delivery": {"region": "CA"},
        "required_by": REQUIRED_BY,
        "max_total": {"amount": "600.00", "currency": "USD"},
        "firm_requirements": [],
        "preferences": [],
    },
}


def settings():
    return settings_for(
        payment_router="fake",
        payment_mode="vault_charge",
        vault_token_key=vault_key(),
        app_env="test",
        ai_enabled=False,
    )


def cipher() -> AesGcmCipher:
    return AesGcmCipher(key_from_config_value(vault_key()))


async def add_user(session: AsyncSession, tag: str, *, role: str = "buyer") -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', :name, CAST(:role AS user_role))"
        ),
        {
            "id": user_id,
            "email": f"it4-{tag}-{user_id}@example.test",
            "name": f"IT4 {tag}",
            "role": role,
        },
    )
    return user_id


async def move_timeline(session: AsyncSession, pool_id: UUID, *, key: str, seconds: int) -> None:
    """Move one timeline instant by ``seconds`` on the database clock.

    ``timeline`` is an input to ``rules_document``, so shifting it silently invalidates
    the ``rules_hash`` that publish froze: the audit page then recomputes a different
    hash over its own served document and reports the pool as tampered. That is exactly
    how Q-2026-11-06-38 was produced -- the demo seeder shifts its own pools' windows to
    make a fast rehearsal, and every shifted pool went red.

    Rule inputs are only mutable until the close publishes the commitment snapshot, so
    the shift is refused after that point and the hash is re-frozen with the new values
    before it. Re-freezing pre-close is honest because nothing has been committed to the
    old rules yet; after close it would be rewriting the rules buyers already agreed to.
    """
    from sqlalchemy import select

    from fairpool.db.models.catalog import Pool
    from fairpool.domain.hashing import rules_hash
    from fairpool.modules.pools.service import rules_document

    # populate_existing, not a plain select: the identity map can hand back an object
    # whose entries_root predates a close that ran in this same session, and a stale
    # read here would let a post-close window shift through.
    pool = await session.scalar(
        select(Pool)
        .where(Pool.id == pool_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if pool is None:
        raise AssertionError("move_timeline: unknown pool")
    if pool.entries_root is not None:
        raise AssertionError("move_timeline: rule inputs are frozen once the close snapshot exists")
    value = datetime.now(UTC) + timedelta(seconds=seconds)
    await session.execute(
        text(
            "UPDATE pools SET timeline = jsonb_set(timeline, ARRAY[:key], "
            "to_jsonb(CAST(:value AS text))) WHERE id = :id"
        ),
        {"key": key, "value": value.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "id": pool_id},
    )
    await session.flush()
    pool = await session.scalar(
        select(Pool).where(Pool.id == pool_id).execution_options(populate_existing=True)
    )
    pool.rules_hash = rules_hash(rules_document(pool))
    await session.flush()


async def drain(session: AsyncSession, handlers: dict[str, Any], limit: int = 200) -> list[str]:
    """Run every due job the registry owns, in the test's transaction.

    The production loop is ``JobRunner.run_once``; it opens its own sessions, which
    cannot see an uncommitted test transaction. Claiming and completing through the
    real ``PostgresJobQueue`` keeps the same claim, concurrency-key and completion
    rules, so what runs is the registered handler and nothing invented here.
    """
    queue = PostgresJobQueue()
    ran: list[str] = []
    for _step in range(limit):
        claimed = await queue.claim(session, worker_id="it4", limit=1, kinds=tuple(handlers))
        if not claimed:
            return ran
        job = claimed[0]
        await handlers[job.kind](session, job.payload)
        await queue.complete(session, job.id, worker_id="it4", attempt=job.attempts)
        ran.append(job.kind)
    raise AssertionError("the job drain did not settle; is a handler re-enqueueing itself?")


async def seed_pool(session: AsyncSession, config: Any, admin_id: UUID) -> UUID:
    """Create and publish a two-zone pool through the real ``PoolService``."""
    now = datetime.now(UTC)
    payload = PoolInput(
        title="Studio 27-inch 4K monitor",
        template=Template(
            product_key="monitor-27-4k",
            variant="black",
            title="Studio 27-inch 4K monitor",
            condition="NEW",
            quantity=1,
            currency="USD",
            bundle_contents=["monitor", "stand", "power cable"],
            delivery_sla_days=7,
            fund_by="2026-11-30",
            min_return_days=14,
            zones=[
                Zone(zone_id="US-EAST", label="US East", regions=["NY", "NJ", "PA"]),
                Zone(zone_id="US-WEST", label="US West", regions=["CA", "WA"]),
            ],
        ),
        lot_plan=[
            ZonePlan(
                zone_id="US-EAST",
                lots=[LotSize(seats=3, min_seats=2), LotSize(seats=2, min_seats=2)],
            ),
            # Four West buyers cannot reach six seats: the lot is cancelled (LS-12).
            ZonePlan(zone_id="US-WEST", lots=[LotSize(seats=6, min_seats=6)]),
        ],
        timeline=Timeline(
            open_at=now + timedelta(seconds=5), close_at=now + timedelta(seconds=3600)
        ),
        require_paypal_link=False,
    )
    pools = pool_service(config)
    pool = await pools.create(session, actor_id=admin_id, payload=payload)
    await pools.publish(session, pool.id, actor_id=admin_id)
    return pool.id


async def script_intake(session: AsyncSession, intake: IntakeService, *, pool_id: UUID) -> None:
    """Register one scripted proposal per message, keyed by the service's own input."""
    ai = intake.ai
    assert isinstance(ai, FakeAI)
    throwaway = await add_user(session, "script")
    for message, region in ((EAST_MESSAGE, "NY"), (WEST_MESSAGE, "CA")):
        await intake.propose(session, user_id=throwaway, message=message, pool_id_override=pool_id)
        ai.register_hash(
            ai.calls[-1].input_hash,
            {
                "pool_id": str(pool_id),
                "match_confidence": "high",
                "ambiguities": [],
                "clarifying_question": None,
                **PROPOSALS[region],
            },
        )


async def join_buyer(
    session: AsyncSession,
    *,
    intake: IntakeService,
    joins: JoinService,
    pool_id: UUID,
    tag: str,
    region: str,
) -> UUID:
    """One buyer from a message to a real entry, through propose, confirm and join."""
    user_id = await add_user(session, tag)
    message = EAST_MESSAGE if region == "NY" else WEST_MESSAGE
    answer = await intake.propose(
        session, user_id=user_id, message=message, pool_id_override=pool_id
    )
    assert answer["status"] == "READY_TO_CONFIRM", answer
    card = answer["confirmation_card"]
    assert card["max_total_cents"] == HIGH_CAP_CENTS
    record = await intake.confirm(session, user_id=user_id, proposal_id=UUID(card["proposal_id"]))
    outcome = await joins.join(
        session,
        pool_id=pool_id,
        user_id=user_id,
        confirmed_request_id=record.id,
        idempotency_key=f"it4-{tag}",
    )
    assert outcome.status_code == 201
    return UUID(str(outcome.body["entry_id"]))


async def add_vault_token(session: AsyncSession, *, entry_id: UUID, user_id: UUID) -> None:
    sealed = cipher().seal(TOKEN_VALUE)
    await session.execute(
        text(
            "INSERT INTO vault_tokens (id, entry_id, user_id, status, token_ciphertext, "
            "token_nonce, token_label, cap_cents, consent_version, consent_text_sha256, "
            "consented_at) VALUES (:id, :entry, :user, 'ACTIVE', :cipher, :nonce, '1234', "
            ":cap, 'v1', :hash, now())"
        ),
        {
            "id": uuid4(),
            "entry": entry_id,
            "user": user_id,
            "cipher": sealed[1],
            "nonce": sealed[0],
            "cap": HIGH_CAP_CENTS,
            "hash": "0" * 64,
        },
    )


async def force_award(
    client: httpx.AsyncClient,
    csrf: str,
    *,
    lot_id: UUID,
    merchant_id: UUID,
    moq: int,
) -> None:
    response = await client.post(
        f"/api/v1/admin/lots/{lot_id}/force-award",
        json={
            "merchant_id": str(merchant_id),
            "item_cents": ITEM_CENTS,
            "tier_index": 0,
            "moq": moq,
            "valid_minutes": 60,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text


async def status_of(session: AsyncSession, table: str, row_id: UUID) -> str:
    value = await session.scalar(text(f"SELECT status FROM {table} WHERE id = :id"), {"id": row_id})
    return str(value)


async def scalar(
    session: AsyncSession, statement: str, params: dict[str, Any] | None = None
) -> int:
    value = await session.scalar(text(statement), params or {})
    return int(value or 0)


async def entry_user(session: AsyncSession, entry_id: UUID) -> UUID:
    value = await session.scalar(
        text("SELECT user_id FROM pool_entries WHERE id = :id"), {"id": entry_id}
    )
    assert value is not None
    return UUID(str(value))


async def public_audit(client: httpx.AsyncClient, pool_id: UUID) -> dict[str, Any]:
    response = await client.get(f"/api/v1/public/pools/{pool_id}/audit")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_it4_pool_to_funded_lot_with_the_real_services(db_session: AsyncSession) -> None:
    """IT-4: the whole Phase 4 pipeline, asserted end to end."""
    config = settings()
    admin_id = await add_user(db_session, "admin", role="admin")
    merchant_user = await add_user(db_session, "merchant")
    merchant_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO merchants (id, user_id, display_name, onboarding_status) "
            "VALUES (:id, :user, 'Demo Merchant Co', 'DEMO')"
        ),
        {"id": merchant_id, "user": merchant_user},
    )

    # The one checkout graph: the HTTP routes and the worker handlers share it.
    surface: CheckoutServices = checkout_services(config)
    assert type(surface.allocations) is PostgresAllocationRead
    assert type(surface.directory) is PostgresMerchantDirectory
    handlers = worker_handlers(config, surface)

    app = create_app(config)
    app.state.checkout_services = surface

    async def session_override() -> Any:
        yield db_session

    app.dependency_overrides[database_session] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        # ---------------------------------------------------------- create, publish
        pool_id = await seed_pool(db_session, config, admin_id)
        csrf = await login(client, "it4-admin@example.test")
        await db_session.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"),
            {"email": "it4-admin@example.test"},
        )
        await move_timeline(db_session, pool_id, key="open_at", seconds=-60)
        await handlers["pool.open"](db_session, {"pool_id": str(pool_id)})
        assert await status_of(db_session, "pools", pool_id) == "OPEN"

        # ------------------------------------------------ 12 buyers through intake
        ai = FakeAI()
        intake = IntakeService(
            search=build_search_service(config),
            ai=ai,
            audit=PostgresAuditLog(),
            clock=DbClock(),
            run_logger=PostgresAiRunLogger(),
            model="fake-model",
        )
        await script_intake(db_session, intake, pool_id=pool_id)
        joins = JoinService(
            DbClock(),
            PostgresAuditLog(),
            PostgresIdempotencyStore(),
            signing_seed=signing_seed(SEED),
            dedupe_mode=config.dedupe_mode,
        )
        runs_before = await scalar(db_session, "SELECT count(*) FROM ai_runs")
        users: dict[UUID, UUID] = {}
        for index in range(8):
            entry_id = await join_buyer(
                db_session,
                intake=intake,
                joins=joins,
                pool_id=pool_id,
                tag=f"east{index}",
                region="NY",
            )
            users[entry_id] = await entry_user(db_session, entry_id)
        for index in range(4):
            entry_id = await join_buyer(
                db_session,
                intake=intake,
                joins=joins,
                pool_id=pool_id,
                tag=f"west{index}",
                region="CA",
            )
            users[entry_id] = await entry_user(db_session, entry_id)
        assert len(users) == 12
        for entry_id, user_id in users.items():
            await add_vault_token(db_session, entry_id=entry_id, user_id=user_id)
        # One attempt row per call: two scripted turns plus one per buyer.
        assert await scalar(db_session, "SELECT count(*) FROM ai_runs") - runs_before >= 12

        # ------------------------------------------------------ close, seed, allocate
        await move_timeline(db_session, pool_id, key="close_at", seconds=-60)
        await handlers["pool.close"](db_session, {"pool_id": str(pool_id)})
        closed = (
            await db_session.execute(
                text("SELECT status, entries_count, entries_root FROM pools WHERE id = :id"),
                {"id": pool_id},
            )
        ).one()
        assert str(closed.status) == "CLOSED"
        assert closed.entries_count == 12 and closed.entries_root

        ran = await drain(db_session, handlers)
        assert "pool.seed" in ran and "pool.allocate" in ran
        seeded = (
            await db_session.execute(
                text("SELECT status, seed_hex, seed_is_demo FROM pools WHERE id = :id"),
                {"id": pool_id},
            )
        ).one()
        assert str(seeded.status) == "RUNNING"
        assert seeded.seed_hex == hashing.demo_seed(str(pool_id)) and seeded.seed_is_demo

        lots = (
            await db_session.execute(
                text(
                    "SELECT id, zone_id, lot_order, seats, status::text AS status "
                    "FROM lots WHERE pool_id = :pool ORDER BY lot_order"
                ),
                {"pool": pool_id},
            )
        ).all()
        # PS-05 now carries its declared effect: ``pool.allocate`` enqueues
        # ``lot.bid_open`` for every lot it leaves PLANNED, the drain runs it, and the
        # first one to enter BIDDING moves the pool ALLOCATED to RUNNING (PS-06). The
        # third lot was cancelled at allocation (LS-12) and never opens a window.
        assert [(row.zone_id, row.lot_order, row.seats, row.status) for row in lots] == [
            ("US-EAST", 1, 3, "BIDDING"),
            ("US-EAST", 2, 2, "BIDDING"),
            ("US-WEST", 3, 6, "CANCELLED"),
        ]
        closing = (
            await db_session.execute(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = 'lot.bid_close' "
                    "AND status = 'PENDING' AND run_at > now()"
                )
            )
        ).scalar_one()
        assert int(closing) == 2
        east_lots = [row for row in lots if row.zone_id == "US-EAST"]
        waitlisted = (
            await db_session.execute(
                text(
                    "SELECT entry_id, zone_id, rank, status::text AS status FROM allocations "
                    "WHERE pool_id = :pool AND status = 'WAITLISTED' ORDER BY zone_id, rank"
                ),
                {"pool": pool_id},
            )
        ).all()
        assert [row.zone_id for row in waitlisted] == ["US-EAST", "US-EAST", "US-EAST"] + [
            "US-WEST"
        ] * 4
        assert [row.rank for row in waitlisted] == [6, 7, 8, 1, 2, 3, 4]

        # ------------------------------------------- caps, awards (priced-out seats)
        priced_out = (
            (
                await db_session.execute(
                    text(
                        "SELECT entry_id FROM allocations WHERE pool_id = :pool "
                        "AND status = 'SEATED' AND zone_id = 'US-EAST' ORDER BY rank LIMIT 2"
                    ),
                    {"pool": pool_id},
                )
            )
            .scalars()
            .all()
        )
        assert len(priced_out) == 2
        await db_session.execute(
            text("UPDATE pool_entries SET cap_cents = :cap WHERE id = ANY(:ids)"),
            {"cap": LOW_CAP_CENTS, "ids": list(priced_out)},
        )
        # The seeded ranking owns who sits where, so the two seats the award will
        # price out are chosen from the seated rows; a cap is only compared to an
        # award when one exists (the same arrangement test_force_award uses).
        for row in east_lots:
            await force_award(client, csrf, lot_id=row.id, merchant_id=merchant_id, moq=row.seats)

        # ------------------------------------- checkout open, refills, charges, FUNDED
        ran = await drain(db_session, handlers)
        assert "lot.open_checkout" in ran
        assert "order.vault_charge" in ran
        # ``domain-ports.md`` section 5 coalesces every ``lot.try_fund`` enqueue under
        # ``try_fund:{lot_id}`` while one is pending, and ``lot.open_checkout`` already
        # scheduled the deadline timer. That timer is still in the future and the lot's
        # stored deadline is never rewritten here: each completed charge enqueues the
        # same key and ``infra/jobs.enqueue`` keeps the earlier ``run_at``, so the
        # funding decision runs on the capture event instead of on the deadline.
        assert "lot.try_fund" in ran, "a capture event pulled the deadline timer forward"
        assert (
            await scalar(
                db_session,
                "SELECT count(*) FROM lots WHERE id = ANY(:lots) AND fund_deadline_at > now()",
                {"lots": [row.id for row in east_lots]},
            )
            == 2
        )

        orders = (
            await db_session.execute(
                text(
                    "SELECT bo.id, bo.status::text AS status, bo.total_cents, bo.lot_id, "
                    "pe.cap_cents FROM buyer_orders bo JOIN pool_entries pe "
                    "ON pe.id = bo.entry_id WHERE bo.lot_id = ANY(:lots)"
                ),
                {"lots": [row.id for row in east_lots]},
            )
        ).all()
        # One order per seat of the two EAST lots, refilled from the waitlist.
        assert len(orders) == sum(int(row.seats) for row in east_lots)
        assert {row.status for row in orders} == {"CAPTURED"}
        assert {int(row.total_cents) for row in orders} == {ITEM_CENTS}
        # Every offer was for a seat whose cap covers the total; the two priced-out
        # entries were released and had no order.
        assert all(int(row.cap_cents) >= ITEM_CENTS for row in orders)
        assert (
            await scalar(
                db_session,
                "SELECT count(*) FROM buyer_orders WHERE lot_id = ANY(:lots) "
                "AND entry_id = ANY(:entries)",
                {"lots": [row.id for row in east_lots], "entries": list(priced_out)},
            )
            == 0
        )

        # The refill moved the priced-out seats to waitlisted entries (N12).
        refilled = await scalar(
            db_session,
            "SELECT count(*) FROM allocations WHERE pool_id = :pool AND status = 'SEATED' "
            "AND entry_id = ANY(:entries)",
            {"pool": pool_id, "entries": [row.entry_id for row in waitlisted]},
        )
        assert refilled == 2

        captures = (
            await db_session.execute(
                text(
                    "SELECT pc.paypal_capture_id, pc.status FROM paypal_captures pc "
                    "JOIN buyer_orders bo ON bo.id = pc.buyer_order_id "
                    "WHERE bo.lot_id = ANY(:lots)"
                ),
                {"lots": [row.id for row in east_lots]},
            )
        ).all()
        assert len(captures) == sum(int(row.seats) for row in east_lots)
        # The fake gateway's ids are the only provider ids in this run (I12).
        assert all(str(row.paypal_capture_id).startswith("FAKE-") for row in captures)
        assert {str(row.status) for row in captures} == {"COMPLETED"}

        ledger = (
            await db_session.execute(
                text(
                    "SELECT lot_id, count(*) FROM ledger_entries WHERE kind = 'CAPTURE_COMPLETED' "
                    "AND lot_id = ANY(:lots) GROUP BY lot_id"
                ),
                {"lots": [row.id for row in east_lots]},
            )
        ).all()
        assert {str(row[0]): int(row[1]) for row in ledger} == {
            str(row.id): int(row.seats) for row in east_lots
        }

        for row in east_lots:
            assert await status_of(db_session, "lots", row.id) == "FUNDED"

        # ------------------------------------------- the audit chain and its payload
        assert await PostgresAuditLog().verify_chain(db_session) is True

        audit = await public_audit(client, pool_id)
        # The pool is RUNNING, not COMPLETED: PS-07 needs ``system.lots_terminal``,
        # which is not a job kind in domain-ports.md section 5 and so nothing emits it.
        # Recorded as Q-2026-11-03-26 rather than worked around by inventing a kind.
        assert audit["pool_status"] == "RUNNING"
        assert audit["seed_is_demo"] is True and audit["seed_hex"] == hashing.demo_seed(
            str(pool_id)
        )
        assert audit["beacon"] == {"source": "demo"}
        assert [lot["status"] for lot in audit["lots"]] == ["FUNDED", "FUNDED", "CANCELLED"]
        for lot in audit["lots"][:2]:
            assert lot["award"]["merchant_display_name"] == "Demo Merchant Co"
            assert lot["award"]["item_cents"] == ITEM_CENTS
        for lot in audit["lots"]:
            span = lot["rank_range"]
            assert len(span) in (0, 2)
            if span:
                assert span[0] <= span[1]

        # The commitments and the root, recomputed with the formula the vectors pin.
        vector = VECTORS["entries"][0]
        assert (
            hashing.commitment(
                vector["canonical_request"]["pool_id"],
                vector["entry_id"],
                vector["request_hash"],
                vector["salt_hex"],
            )
            == vector["commitment"]
        )
        rows = (
            await db_session.execute(
                text(
                    "SELECT pe.id, pe.request_hash, pe.canonical_request, er.salt "
                    "FROM pool_entries pe JOIN entry_receipts er ON er.entry_id = pe.id "
                    "WHERE pe.pool_id = :pool AND pe.status = 'ELIGIBLE'"
                ),
                {"pool": pool_id},
            )
        ).all()
        recomputed = sorted(
            hashing.commitment(str(pool_id), str(row.id), str(row.request_hash), str(row.salt))
            for row in rows
        )
        assert len(recomputed) == 12
        assert audit["commitments"] == recomputed
        assert audit["entries_root"] == hashing.merkle_root(recomputed)

        # ----------------------------------------- the real services were the ones run
        assert "next_candidates" in surface.allocations.calls
        assert surface.allocations.calls.count("get_award") >= 2
        assert "list_seated" in surface.allocations.calls
        assert surface.directory.calls, "the real merchant directory served the payees"
        assert all(call.merchant_id == merchant_id for call in surface.directory.calls), (
            "every payee lookup was the awarded merchant"
        )
