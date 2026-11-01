"""F5: an approval that arrives after the seat expired never authorizes (I1, I7).

The offer window ends first: ``offer.expire`` moves the order to EXPIRED through
BO-17, the edge the contract names for exactly this fault (state-machines.md,
"not AUTHORIZING (N4, F5)"), and the seat becomes one claimable vacancy. Everything
that can still arrive afterwards is tried here -- a late approval notification, a
late ``buyer.return``, a replayed authorization attempt carrying a real ``CREATED``
authorization, and a redelivered ``offer.expire`` -- and none of it may move the row,
authorize it, or write a second effect. Legality is the whitelist's, and the
whitelist has no edge out of EXPIRED (I10), so the money path can only be reached by
a row the contract still holds open.

The first test runs the engine on the port fakes, so every refusal shows up as a
missing call; the second runs it on the real Postgres audit, ledger and job queue,
because "no ledger row" and "no duplicate ``lot.refill``" are database claims.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import IllegalTransition
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from fairpool.modules.checkout.expiry import EXPIRED_STATE, OfferExpiry
from tests.unit.test_checkout_engine import (
    Scene,
    insert_authorization,
    insert_paypal_order,
    make_scene,
    stored_status,
    trigger_for,
)
from tests.unit.test_checkout_engine_effects import counts, real_engine

pytestmark = pytest.mark.faults

ENGINE_LOGGER = "fairpool.checkout.engine"


def expiry_handler(scene: Scene, *, engine: CheckoutEngine | None = None) -> OfferExpiry:
    """The handler a worker would run, on the ports this test is exercising."""
    return OfferExpiry(
        engine=engine or scene.ports.engine,
        jobs=PostgresJobQueue() if engine is not None else scene.ports.jobs,
    )


def late_events(
    scene: Scene, paypal_order_id: str, auth_id: str
) -> list[tuple[str, TransitionRequest]]:
    """Every attempt a late worker or a redelivered job can make against the seat.

    The authorize pair is the whole ``order.authorize`` job: BO-03 takes the seat
    lock, BO-04 reports the adapter's CREATED authorization and is the step that
    would put a ``ledger:AUTH_CREATED`` fact on a seat the lot has re-offered.
    """
    return [
        (
            "late approval notification",
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="APPROVED",
                trigger=trigger_for("BO-02"),
                actor="test.f05",
                observation=Observation(
                    "approval", "APPROVED", paypal_order_id, amount_cents=50_000, currency="USD"
                ),
            ),
        ),
        (
            "late buyer.return",
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="ORDER_CREATED",
                trigger=trigger_for("BO-01"),
                actor="test.f05",
            ),
        ),
        (
            "late authorize step",
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="AUTHORIZING",
                trigger="job:order.authorize",
                actor="test.f05",
                seat_locked_until=scene.now,
            ),
        ),
        (
            "replayed authorization with evidence",
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="AUTHORIZED",
                trigger="job:order.authorize",
                actor="test.f05",
                observation=Observation("authorization", "CREATED", auth_id, amount_cents=50_000),
            ),
        ),
    ]


def error_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == ENGINE_LOGGER and record.levelname == "ERROR"
    ]


async def tally(session: AsyncSession, scene: Scene) -> dict[str, int]:
    """What each port recorded and what the database holds for this one order."""
    return {
        "audit": len(scene.ports.audit.rows),
        "ledger": len(scene.ports.ledger.entries),
        "jobs": len(scene.ports.jobs.jobs),
        "notify": len(scene.ports.notifier.calls),
        "db_ledger": (await counts(session, scene))["ledger"],
    }


async def test_f05_approval_after_seat_expired_never_authorizes(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """F5 (I1, I7): after expiry no late approval, return, authorize or replay moves it."""
    scene = await make_scene(db_session, status="APPROVED", offer_in=-1)
    paypal_order_id = await insert_paypal_order(db_session, scene.order_id)
    auth_id = await insert_authorization(
        db_session, scene.order_id, paypal_order_id=paypal_order_id
    )
    handler = expiry_handler(scene)
    payload = {"buyer_order_id": str(scene.order_id)}

    await handler.expire(db_session, payload)
    assert await stored_status(db_session, scene.order_id) == EXPIRED_STATE
    assert await handler.claimable_vacancies(db_session, scene.lot_id) == 1
    assert [job.dedupe_key for job in scene.ports.jobs.jobs] == [f"refill:{scene.lot_id}"]
    settled = await tally(db_session, scene)
    assert settled["ledger"] == 0, "an expired offer is not a money fact (I4)"

    for name, request in late_events(scene, paypal_order_id, auth_id):
        caplog.clear()
        with pytest.raises(IllegalTransition):
            await scene.ports.engine.apply(db_session, request)
        await _unchanged(db_session, scene, handler, settled, name, caplog)

    # The redelivered timer is the fifth event: it alerts and writes nothing (I9).
    caplog.clear()
    await handler.expire(db_session, payload)
    await _unchanged(db_session, scene, handler, settled, "replayed offer.expire", caplog)

    # Positive control: the two authorize requests are accepted while a seat is still
    # held, so the refusals above are the expiry's doing and not a broken fixture.
    live = await make_scene(db_session, status="APPROVED")
    live_order = await insert_paypal_order(db_session, live.order_id)
    live_auth = await insert_authorization(db_session, live.order_id, paypal_order_id=live_order)
    events = late_events(live, live_order, live_auth)
    lock_step = await live.ports.engine.apply(db_session, events[2][1])
    assert lock_step.transition_id == "BO-03"
    money_step = await live.ports.engine.apply(db_session, events[3][1])
    assert money_step.transition_id == "BO-04"
    assert len(live.ports.ledger.entries) == 1, "the live seat does record AUTH_CREATED"


async def _unchanged(
    session: AsyncSession,
    scene: Scene,
    handler: OfferExpiry,
    settled: dict[str, int],
    name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The state, every port and the vacancy count are exactly as the expiry left them."""
    assert await stored_status(session, scene.order_id) == EXPIRED_STATE, name
    assert await tally(session, scene) == settled, f"{name} wrote an effect"
    assert await handler.claimable_vacancies(session, scene.lot_id) == 1, name
    assert [job.kind for job in scene.ports.jobs.jobs] == ["lot.refill"], name
    # CR-3 note 5: a refusal is alerted, never silently swallowed.
    assert error_records(caplog), f"{name} must alert"


async def test_f05_on_the_real_ports_a_late_approval_writes_nothing(
    db_session: AsyncSession,
) -> None:
    """F5 (I1, I7, I9): on the Postgres ports a late approval adds no row anywhere."""
    scene = await make_scene(db_session, status="APPROVED", offer_in=-1)
    paypal_order_id = await insert_paypal_order(db_session, scene.order_id)
    auth_id = await insert_authorization(
        db_session, scene.order_id, paypal_order_id=paypal_order_id
    )
    engine = real_engine()
    handler = expiry_handler(scene, engine=engine)
    payload = {"buyer_order_id": str(scene.order_id)}

    async with db_session.begin_nested():
        await handler.expire(db_session, payload)
    assert await stored_status(db_session, scene.order_id) == EXPIRED_STATE
    settled = await counts(db_session, scene)
    assert settled == {"audit": 1, "ledger": 0, "jobs": 1}, settled
    assert await _refill_rows(db_session, scene) == [f"refill:{scene.lot_id}"]

    for name, request in late_events(scene, paypal_order_id, auth_id):
        async with db_session.begin_nested():
            with pytest.raises(IllegalTransition):
                await engine.apply(db_session, request)
        assert await stored_status(db_session, scene.order_id) == EXPIRED_STATE, name

    async with db_session.begin_nested():
        await handler.expire(db_session, payload)

    assert await counts(db_session, scene) == settled
    assert await _refill_rows(db_session, scene) == [f"refill:{scene.lot_id}"]
    assert await _ledger_kinds(db_session, scene) == []
    assert await handler.claimable_vacancies(db_session, scene.lot_id) == 1
    assert await stored_status(db_session, scene.order_id) == EXPIRED_STATE


async def _refill_rows(session: AsyncSession, scene: Scene) -> list[str]:
    rows = await session.execute(
        text("SELECT dedupe_key FROM jobs WHERE kind = 'lot.refill' AND payload->>'lot_id' = :lot"),
        {"lot": str(scene.lot_id)},
    )
    return [str(row[0]) for row in rows]


async def _ledger_kinds(session: AsyncSession, scene: Scene) -> list[str]:
    rows = await session.execute(
        text("SELECT kind FROM ledger_entries WHERE buyer_order_id = CAST(:id AS uuid)"),
        {"id": str(scene.order_id)},
    )
    return sorted(str(row[0]) for row in rows)
