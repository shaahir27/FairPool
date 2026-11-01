"""T03A01 acceptance 3 and 8: one transaction per transition, no effect twice.

These run on the real Postgres ports (audit chain, ledger, job queue, idempotency
store) because the property under test is that a state change, its audit row, its
ledger fact, its notification and its next job are all discarded or all kept
(I10). A failure injected into any one effect must leave no trace of the others,
and a replay must duplicate none of them.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import IllegalTransition
from fairpool.fakes.notifier import FakeNotifier
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from fairpool.modules.ledger.service import PostgresLedger
from tests.unit.test_checkout_engine import (
    Scene,
    insert_authorization,
    insert_capture,
    insert_paypal_order,
    make_scene,
    set_lot_status,
    stored_status,
    trigger_for,
)

pytestmark = pytest.mark.integration


class _FailingLedger(PostgresLedger):
    def __init__(self, message: str = "ledger write failed") -> None:
        self.message = message

    async def record(self, *args: Any, **kwargs: Any) -> bool:
        raise RuntimeError(self.message)


class _FailingAudit(PostgresAuditLog):
    async def append(self, *args: Any, **kwargs: Any) -> int:
        raise RuntimeError("audit append failed")


class _FailingJobs(PostgresJobQueue):
    async def enqueue(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("job enqueue failed")


class _FailingNotifier(FakeNotifier):
    async def notify(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("notify failed")


def real_engine(**overrides: Any) -> CheckoutEngine:
    """The engine on the Postgres ports, with one port replaceable per test."""
    ports: dict[str, Any] = {
        "clock": DbClock(),
        "audit": PostgresAuditLog(),
        "jobs": PostgresJobQueue(),
        "ledger": PostgresLedger(),
        "notifier": FakeNotifier(),
        "idempotency": PostgresIdempotencyStore(),
    }
    ports.update(overrides)
    return CheckoutEngine(**ports)  # type: ignore[arg-type]


async def counts(session: AsyncSession, scene: Scene) -> dict[str, int]:
    """Audit, ledger and job rows written for one scene.

    Lot-scoped jobs carry only a lot id in their payload (``domain-ports.md``
    section 5: payloads contain IDs), so the job count matches on either id.
    """
    order_id = str(scene.order_id)
    lot_id = str(scene.lot_id)
    sql = {
        "audit": "SELECT count(*) FROM audit_log WHERE subject_id = :id",
        "ledger": ("SELECT count(*) FROM ledger_entries WHERE buyer_order_id = CAST(:id AS uuid)"),
        "jobs": (
            "SELECT count(*) FROM jobs WHERE payload->>'buyer_order_id' = :id "
            "OR payload->>'lot_id' = :lot"
        ),
    }
    return {
        name: int((await session.scalar(text(query), {"id": order_id, "lot": lot_id})) or 0)
        for name, query in sql.items()
    }


async def authorize_request(scene: Scene) -> TransitionRequest:
    """Put one order in AUTHORIZING with a persisted authorization to evidence."""
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    return TransitionRequest(
        buyer_order_id=scene.order_id,
        to_state="AUTHORIZED",
        trigger=trigger_for("BO-04"),
        actor="test.effect.atomicity",
        observation=Observation("authorization", "CREATED", auth_id, amount_cents=50_000),
    )


@pytest.mark.parametrize("failing", ["audit", "ledger", "job"])
async def test_a_failing_effect_rolls_back_the_whole_transition(
    db_session: AsyncSession, failing: str
) -> None:
    """T03A01 acceptance 3: audit, ledger and job share the state change's fate (I10)."""
    scene = await make_scene(db_session, status="AUTHORIZING")
    request = await authorize_request(scene)
    overrides = {
        "audit": _FailingAudit(),
        "ledger": _FailingLedger(),
        "jobs": _FailingJobs(),
    }
    failing_port = {"job": "jobs"}.get(failing, failing)
    engine = real_engine(**{failing_port: overrides[failing_port]})
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await engine.apply(db_session, request)
    db_session.expire_all()
    assert await stored_status(db_session, scene.order_id) == "AUTHORIZING"
    assert await counts(db_session, scene) == {"audit": 0, "ledger": 0, "jobs": 0}


async def test_a_failing_notification_rolls_back_the_whole_transition(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 3: the notification is part of the same transaction (I10)."""
    scene = await make_scene(db_session, status="ORDER_CREATED")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id, status="CREATED")
    engine = real_engine(notifier=_FailingNotifier())
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await engine.apply(
                db_session,
                TransitionRequest(
                    buyer_order_id=scene.order_id,
                    to_state="REJECTED",
                    trigger=trigger_for("BO-18"),
                    reject_reason="WRONG_COUNTRY",
                    observation=Observation(
                        "approval", "CREATED", paypal_order_id, checks_passed=False
                    ),
                    actor="test.notify.rollback",
                ),
            )
    db_session.expire_all()
    assert await stored_status(db_session, scene.order_id) == "ORDER_CREATED"
    assert await counts(db_session, scene) == {"audit": 0, "ledger": 0, "jobs": 0}


async def test_committed_transition_writes_exactly_one_of_each_effect(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 3: state, audit, ledger and next job all land together."""
    scene = await make_scene(db_session, status="AUTHORIZING")
    request = await authorize_request(scene)
    engine = real_engine()
    async with db_session.begin_nested():
        outcome = await engine.apply(db_session, request)
    assert outcome.applied is True
    assert await stored_status(db_session, scene.order_id) == "AUTHORIZED"
    assert await counts(db_session, scene) == {"audit": 1, "ledger": 1, "jobs": 1}
    ledger = (
        await db_session.execute(
            text(
                "SELECT kind, amount_cents, idempotency_key, source FROM ledger_entries "
                "WHERE buyer_order_id = :id"
            ),
            {"id": scene.order_id},
        )
    ).all()
    assert [(row.kind, row.amount_cents, row.idempotency_key, row.source) for row in ledger] == [
        ("AUTH_CREATED", 50_000, f"auth:{scene.order_id}:auth_created", "api")
    ]
    job = (
        await db_session.execute(
            text(
                "SELECT kind, concurrency_key, dedupe_key FROM jobs WHERE payload->>'lot_id' = :lot"
            ),
            {"lot": str(scene.lot_id)},
        )
    ).one()
    assert (job.kind, job.concurrency_key, job.dedupe_key) == (
        "lot.try_fund",
        f"lot:{scene.lot_id}",
        f"try_fund:{scene.lot_id}",
    )


async def test_replay_duplicates_no_ledger_audit_or_job_effect(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 8 (I9): the second call returns the original outcome only."""
    scene = await make_scene(db_session, status="AUTHORIZING")
    request = await authorize_request(scene)
    engine = real_engine()
    async with db_session.begin_nested():
        first = await engine.apply(db_session, request)
    async with db_session.begin_nested():
        second = await engine.apply(db_session, request)
    assert second.applied is False
    assert second.transition_id == first.transition_id
    assert second.idempotency_key == first.idempotency_key
    assert await stored_status(db_session, scene.order_id) == "AUTHORIZED"
    assert await counts(db_session, scene) == {"audit": 1, "ledger": 1, "jobs": 1}


async def test_replayed_capture_writes_one_ledger_row_per_key(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 8: one ledger row per idempotency key even across steps (I9)."""
    scene = await make_scene(db_session, status="CAPTURING")
    await set_lot_status(db_session, scene.lot_id, "FUNDING")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    capture_id = await insert_capture(scene.session, scene.order_id, auth_id=auth_id)
    engine = real_engine()
    request = TransitionRequest(
        buyer_order_id=scene.order_id,
        to_state="CAPTURED",
        trigger=trigger_for("BO-07"),
        observation=Observation("capture", "COMPLETED", capture_id, amount_cents=50_000),
    )
    async with db_session.begin_nested():
        await engine.apply(db_session, request)
    async with db_session.begin_nested():
        await engine.apply(db_session, request)
    assert await counts(db_session, scene) == {"audit": 1, "ledger": 1, "jobs": 1}


async def test_lot_failing_void_creates_no_refill_job(db_session: AsyncSession) -> None:
    """T03A02 acceptance: a VOIDED with void_source lot_failing frees no seat."""
    scene = await make_scene(db_session, status="AUTHORIZED")
    await set_lot_status(db_session, scene.lot_id, "FAILING")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    engine = real_engine()
    async with db_session.begin_nested():
        outcome = await engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="VOIDED",
                trigger=trigger_for("BO-12"),
                void_source="lot_failing",
                observation=Observation("authorization", "VOIDED", auth_id),
            ),
        )
    assert outcome.transition_id == "BO-12"
    assert (await counts(db_session, scene))["jobs"] == 0
    assert (await counts(db_session, scene))["ledger"] == 1


async def test_expired_offer_enqueues_one_deduplicated_refill(
    db_session: AsyncSession,
) -> None:
    """T03A02 acceptance: one lot.refill per valid vacancy, keyed refill:{lot_id}."""
    scene = await make_scene(db_session, offer_in=-1)
    engine = real_engine()
    request = TransitionRequest(
        buyer_order_id=scene.order_id,
        to_state="EXPIRED",
        trigger=trigger_for("BO-15"),
        actor="worker:offer.expire",
    )
    async with db_session.begin_nested():
        await engine.apply(db_session, request)
    async with db_session.begin_nested():
        replay = await engine.apply(db_session, request)
    assert replay.applied is False
    jobs = (
        await db_session.execute(
            text("SELECT kind, dedupe_key, status FROM jobs WHERE payload->>'lot_id' = :lot"),
            {"lot": str(scene.lot_id)},
        )
    ).all()
    assert [(row.kind, row.dedupe_key) for row in jobs] == [
        ("lot.refill", f"refill:{scene.lot_id}")
    ]
    assert await stored_status(db_session, scene.order_id) == "EXPIRED"


async def test_illegal_pair_leaves_the_row_and_writes_nothing(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 1 and 8: a refused transition writes no idempotency row."""
    scene = await make_scene(db_session, status="CAPTURED")
    engine = real_engine()
    with pytest.raises(IllegalTransition):
        async with db_session.begin_nested():
            await engine.apply(
                db_session,
                TransitionRequest(
                    buyer_order_id=scene.order_id,
                    to_state="OFFERED",
                    trigger="job:test",
                    actor="test.illegal",
                ),
            )
    db_session.expire_all()
    assert await stored_status(db_session, scene.order_id) == "CAPTURED"
    assert await counts(db_session, scene) == {"audit": 0, "ledger": 0, "jobs": 0}
    stored = await db_session.scalar(
        text("SELECT count(*) FROM idempotency_keys WHERE scope = 'checkout.buyer_order'")
    )
    assert int(stored or 0) == 0
