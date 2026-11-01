"""PT-10: replaying any handler twice leaves the same final state and one ledger
row per idempotency key (I9).

The same session and the real Postgres ports are used, because the property is about
what a database sees after a second delivery of a job or a repeated HTTP attempt: the
state stays where the first application put it, the audit chain gains no row, the job
queue gains no work and the ledger keeps exactly one fact per key.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.states import TRANSITIONS_BY_ID
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from fairpool.modules.checkout.expiry import OfferExpiry
from tests.property.test_pt07_runtime_transitions import (
    BO_IDS,
    _close_driver,
    _open_driver,
    drive,
    prepare,
    scene_kwargs,
)
from tests.unit.test_checkout_engine import (
    Scene,
    make_scene,
    stored_status,
)
from tests.unit.test_checkout_engine_effects import real_engine

pytestmark = pytest.mark.property


@pytest.fixture(scope="module", autouse=True)
def _driver(migrated_db: None) -> Iterator[None]:
    _open_driver()
    try:
        yield
    finally:
        _close_driver()


async def _tally(session: AsyncSession, scene: Scene) -> dict[str, Any]:
    """What the database actually holds for this order after a series of attempts."""
    ledger = (
        await session.execute(
            text(
                "SELECT idempotency_key, count(*) FROM ledger_entries "
                "WHERE buyer_order_id = CAST(:id AS uuid) GROUP BY idempotency_key"
            ),
            {"id": scene.order_id},
        )
    ).all()
    audit = int(
        await session.scalar(
            text("SELECT count(*) FROM audit_log WHERE subject_id = :id"),
            {"id": str(scene.order_id)},
        )
        or 0
    )
    jobs = int(
        await session.scalar(
            text(
                "SELECT count(*) FROM jobs WHERE payload->>'buyer_order_id' = :id "
                "OR payload->>'lot_id' = :lot"
            ),
            {"id": str(scene.order_id), "lot": str(scene.lot_id)},
        )
        or 0
    )
    return {
        "ledger": [row[1] for row in ledger],
        "ledger_keys": [row[0] for row in ledger],
        "audit": audit,
        "jobs": jobs,
    }


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(transition_id=st.sampled_from(BO_IDS), extra_attempts=st.integers(min_value=1, max_value=3))
def test_replaying_the_engine_twice_changes_nothing(
    transition_id: str, extra_attempts: int
) -> None:
    """PT-10: apply the same request N more times; the state and effects do not move."""

    async def _work(session: AsyncSession) -> None:
        transition = TRANSITIONS_BY_ID[transition_id]
        scene = await make_scene(
            session, status=transition.from_states[0], **scene_kwargs(transition_id)
        )
        request = await prepare(session, scene, transition_id)
        first = await scene.ports.engine.apply(session, request)
        after_first = await _tally(session, scene)
        state_after_first = await stored_status(session, scene.order_id)
        for _ in range(extra_attempts):
            replay = await scene.ports.engine.apply(session, request)
            assert replay.applied is False
            assert replay.transition_id == first.transition_id
            assert replay.idempotency_key == first.idempotency_key
        assert await stored_status(session, scene.order_id) == state_after_first
        after_replays = await _tally(session, scene)
        assert after_replays == after_first
        assert all(count == 1 for count in after_replays["ledger"]), after_replays

    drive(_work)


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(transition_id=st.sampled_from(BO_IDS))
def test_one_ledger_row_per_idempotency_key_on_the_postgres_ports(
    transition_id: str,
) -> None:
    """PT-10: real ledger, audit and jobs; replay adds no row for the same key."""
    transition = TRANSITIONS_BY_ID[transition_id]
    money_bearing = any(effect.startswith("ledger:") for effect in transition.effects)

    async def _work(session: AsyncSession) -> None:
        scene = await make_scene(
            session, status=transition.from_states[0], **scene_kwargs(transition_id)
        )
        request = await prepare(session, scene, transition_id)
        engine = real_engine()
        async with session.begin_nested():
            first = await engine.apply(session, request)
        assert first.applied is True
        async with session.begin_nested():
            replay = await engine.apply(session, request)
        assert replay.applied is False
        tally = await _tally(session, scene)
        assert all(count == 1 for count in tally["ledger"]), tally
        assert len(set(tally["ledger_keys"])) == len(tally["ledger_keys"])
        assert tally["audit"] == 1
        if money_bearing:
            assert tally["ledger"], transition_id
        else:
            assert tally["ledger"] == [], transition_id

    drive(_work)


@settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(offer_in=st.integers(min_value=-900, max_value=-1))
def test_replaying_the_expiry_handler_twice_leaves_one_refill(offer_in: int) -> None:
    """PT-10 with T03A02: a redelivered offer.expire expires nothing twice."""

    async def _work(session: AsyncSession) -> None:
        scene = await make_scene(session, status="OFFERED", offer_in=offer_in)
        expiry = OfferExpiry(engine=scene.ports.engine, jobs=scene.ports.jobs)
        payload = {"buyer_order_id": str(scene.order_id)}
        await expiry.expire(session, payload)
        await expiry.expire(session, payload)
        assert await stored_status(session, scene.order_id) == "EXPIRED"
        refills = [job for job in scene.ports.jobs.jobs if job.kind == "lot.refill"]
        assert len(refills) == 1
        assert refills[0].dedupe_key == f"refill:{scene.lot_id}"

    drive(_work)


async def test_replayed_request_with_a_different_payload_conflicts(
    db_session: AsyncSession,
) -> None:
    """PT-10 boundary: a reused key is a conflict, never a second application (I9)."""
    scene = await make_scene(db_session, status="AUTHORIZING")
    request = await prepare(db_session, scene, "BO-04")
    outcome = await scene.ports.engine.apply(db_session, request)
    assert outcome.applied is True
    with pytest.raises(ApplicationError) as excinfo:
        await scene.ports.engine.apply(db_session, replace_actor(request))
    assert excinfo.value.code == "IDEMPOTENCY_CONFLICT"
    assert await stored_status(db_session, scene.order_id) == "AUTHORIZED"


def replace_actor(request: TransitionRequest) -> TransitionRequest:
    from dataclasses import replace

    return replace(request, actor="a-different-actor")


async def test_a_handler_that_refuses_writes_no_idempotency_row(
    db_session: AsyncSession,
) -> None:
    """PT-10: an illegal request is not recorded, so a retry reads the same refusal."""
    scene = await make_scene(db_session, status="CAPTURED")
    engine: CheckoutEngine = scene.ports.engine
    for _ in range(2):
        with pytest.raises(IllegalTransition):
            await engine.apply(
                db_session,
                TransitionRequest(
                    buyer_order_id=scene.order_id, to_state="OFFERED", trigger="job:test"
                ),
            )
    assert await stored_status(db_session, scene.order_id) == "CAPTURED"
