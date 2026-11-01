"""PT-12 model-based: no sequence of timer, lease or expiry events frees a seat
whose order is AUTHORIZING (I7), and only the contracted states ever expire (T03A02).

The model is the buyer_order machine's own active-state set: while a row sits in
AUTHORIZING, CAPTURING or CAPTURE_PENDING, every event in the timer alphabet must
leave it where it is, because an unknown outcome is not proof of failure (I7, N4).
The rest of the file pins the seat-vacancy rules of the vacancy paragraph after the
buyer_order table: vacancies come from the lot's orders under the lot lock, never
from a counter column, one valid vacancy means one deduplicated ``lot.refill``, a
VOIDED with ``void_source = lot_failing`` frees nothing, and a replay frees nothing
twice.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import IllegalTransition
from fairpool.domain.states import MACHINES, TRANSITIONS_BY_ID
from fairpool.modules.checkout.engine import TransitionRequest
from fairpool.modules.checkout.expiry import EXPIRE_TRIGGER, EXPIRED_STATE, OfferExpiry
from tests.property.test_pt07_runtime_transitions import _close_driver, _open_driver, drive
from tests.unit.test_checkout_engine import (
    Scene,
    insert_allocation,
    insert_order,
    insert_vault_token,
    make_scene,
    set_order_status,
    stored_status,
    trigger_for,
)

pytestmark = pytest.mark.property

LOCKED_STATES = ("AUTHORIZING", "CAPTURING", "CAPTURE_PENDING")
# The model's active set is the whitelist's own, not a copy that can drift.
ACTIVE_STATES_SOURCE = MACHINES["buyer_order"].active
TIMER_EVENTS = (
    "offer.expire",
    "lease.reclaim",
    "buyer.decline",
    "buyer.cancel",
    "expiry.request",
)
EXPIRABLE = {"OFFERED", "ORDER_CREATED", "APPROVED"}


@pytest.fixture(scope="module", autouse=True)
def _driver(migrated_db: None) -> Iterator[None]:
    _open_driver()
    try:
        yield
    finally:
        _close_driver()


async def add_second_order(
    session: AsyncSession,
    scene: Scene,
    *,
    status: str,
    void_source: str | None = None,
    total_cents: int = 50_000,
) -> UUID:
    """Another buyer order on the same lot, with its own entry, user and seat."""
    from tests.unit.test_checkout_engine import add_entry, add_user

    pool_id = scene.pool_id
    user_id = await add_user(session)
    entry_id = await add_entry(session, pool_id, user_id=user_id)
    await insert_allocation(session, pool_id, entry_id, scene.lot_id, status="SEATED")
    return await insert_order(
        session,
        scene.lot_id,
        entry_id,
        status=status,
        total_cents=total_cents,
        offer_expires_at=scene.now,
        void_source=void_source,
    )


def expiry_handler(scene: Scene) -> OfferExpiry:
    return OfferExpiry(engine=scene.ports.engine, jobs=scene.ports.jobs)


async def run_event(session: AsyncSession, scene: Scene, event: str) -> None:
    """Apply one timer-or-lease event, exactly as a worker or a buyer action would."""
    handler = expiry_handler(scene)
    payload = {"buyer_order_id": str(scene.order_id)}
    if event in {"offer.expire", "lease.reclaim"}:
        # lease.reclaim is the same job delivered again after its lease expired.
        await handler.expire(session, payload)
        return
    if event == "expiry.request":
        # Same refusal as the decline edge above: no state in the whitelist expires
        # a locked seat, so the engine raises and the row must not move (I7, N4).
        with contextlib.suppress(IllegalTransition):
            await scene.ports.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=scene.order_id,
                    to_state=EXPIRED_STATE,
                    trigger=EXPIRE_TRIGGER,
                    actor="test.pt12",
                ),
            )
        return
    to_state = "DECLINED"
    transition_id = "BO-21" if event == "buyer.decline" else "BO-22"
    # A decline against a locked seat is the refusal this property is about: BO-21
    # and BO-22 both exclude AUTHORIZING (I7), so the whitelist raises and the row
    # stays where it was. Swallowing it here is the assertion, not a hiding place --
    # the caller re-reads the stored status after every event.
    with contextlib.suppress(IllegalTransition):
        await scene.ports.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state=to_state,
                trigger=trigger_for(transition_id),
                actor="test.pt12",
            ),
        )


@settings(
    max_examples=24,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    state=st.sampled_from(LOCKED_STATES),
    events=st.lists(st.sampled_from(TIMER_EVENTS), min_size=1, max_size=6),
)
def test_no_timer_or_lease_sequence_releases_a_locked_seat(
    state: str, events: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    """PT-12: an AUTHORIZING, CAPTURING or CAPTURE_PENDING seat never moves on a timer.

    The offer deadline is deliberately long past: the lock, not the clock, is what
    keeps the seat (I7, N4). Each refusal is alerted, never silently swallowed
    (CR-3 note 5).
    """

    async def _work(session: AsyncSession) -> None:
        scene = await make_scene(session, status=state, offer_in=-600)
        if state == "AUTHORIZING":
            await _insert(session, scene.order_id, state)
        before = await expiry_handler(scene).claimable_vacancies(session, scene.lot_id)
        caplog.clear()
        for event in events:
            await run_event(session, scene, event)
            assert await stored_status(session, scene.order_id) == state, event
        errors = [record for record in caplog.records if record.levelname == "ERROR"]
        assert errors, "a refused timer must alert, not skip silently"
        assert await expiry_handler(scene).claimable_vacancies(session, scene.lot_id) == before

    drive(_work)


async def _insert(session: AsyncSession, order_id: UUID, state: str) -> None:
    await session.execute(
        text(
            "UPDATE buyer_orders SET seat_locked_until = now() + interval '120 seconds' "
            "WHERE id = :id"
        ),
        {"id": order_id},
    )
    assert await stored_status(session, order_id) == state


@settings(
    max_examples=16,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    state=st.sampled_from(tuple(MACHINES["buyer_order"].states)),
    offer_in=st.sampled_from([-600, -1, 1, 600]),
    mode=st.sampled_from(["authorize_capture", "capture_only", "vault_charge"]),
)
def test_only_the_contracted_fallback_states_expire(state: str, offer_in: int, mode: str) -> None:
    """T03A02 acceptance: expiry is BO-15 to BO-17 only, after the stored deadline.

    The predicted outcome is the model: the whitelist's three edges into EXPIRED,
    the wall-clock deadline, and no buyer offer window under vault_charge
    (vault-charge.md section 3).
    """

    async def _work(session: AsyncSession) -> None:
        scene = await make_scene(session, status=state, offer_in=offer_in, mode=mode)
        if mode == "vault_charge":
            await insert_vault_token(session, scene.entry_id, scene.user_id)
        await expiry_handler(scene).expire(session, {"buyer_order_id": str(scene.order_id)})
        after = await stored_status(session, scene.order_id)
        may_expire = state in EXPIRABLE and offer_in < 0 and mode != "vault_charge"
        # A seat already sitting in EXPIRED is "unchanged" and "EXPIRED" at once, so
        # the expectation is the state the model predicts, not two separate asserts.
        assert after == ("EXPIRED" if may_expire else state), (state, offer_in, mode, after)

    drive(_work)


async def test_an_early_timer_does_nothing_at_all(db_session: AsyncSession) -> None:
    """T03A02 acceptance: a timer that fires before the deadline releases no seat."""
    scene = await make_scene(db_session, status="OFFERED", offer_in=600)
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(scene.order_id)})
    assert await stored_status(db_session, scene.order_id) == "OFFERED"
    assert scene.ports.jobs.jobs == []
    assert scene.ports.audit.rows == []
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 0


async def test_expiry_after_the_deadline_creates_one_deduplicated_refill(
    db_session: AsyncSession,
) -> None:
    """T03A02 acceptance: one valid vacancy, one lot.refill under refill:{lot_id}."""
    scene = await make_scene(db_session, status="OFFERED", offer_in=-1)
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(scene.order_id)})
    assert await stored_status(db_session, scene.order_id) == "EXPIRED"
    refills = [job for job in scene.ports.jobs.jobs if job.kind == "lot.refill"]
    assert len(refills) == 1
    assert refills[0].dedupe_key == f"refill:{scene.lot_id}"
    assert refills[0].concurrency_key == f"lot:{scene.lot_id}"
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1


async def test_a_replayed_expiry_creates_no_second_vacancy(db_session: AsyncSession) -> None:
    """T03A02 acceptance: redelivery expires nothing twice and frees nothing twice."""
    scene = await make_scene(db_session, status="OFFERED", offer_in=-1)
    payload = {"buyer_order_id": str(scene.order_id)}
    await expiry_handler(scene).expire(db_session, payload)
    await expiry_handler(scene).expire(db_session, payload)
    assert await stored_status(db_session, scene.order_id) == "EXPIRED"
    assert len([job for job in scene.ports.jobs.jobs if job.kind == "lot.refill"]) == 1
    assert len(scene.ports.audit.rows) == 1
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1


async def test_a_lot_failing_void_creates_no_vacancy(db_session: AsyncSession) -> None:
    """T03A02 acceptance: VOIDED with void_source lot_failing never frees a seat."""
    scene = await make_scene(db_session, status="OFFERED", offer_in=-1)
    other = await add_second_order(
        db_session, scene, status="AUTHORIZED", void_source="lot_failing"
    )
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 0
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(scene.order_id)})
    # one vacancy from the expiry; the lot_failing void adds none.
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1
    await set_order_status(db_session, other, "VOIDED")
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1


async def test_an_age_guard_void_does_create_a_vacancy(db_session: AsyncSession) -> None:
    """T03A02 acceptance: the vacancy rule names age_guard, buyer_withdraw, paypal_expired."""
    scene = await make_scene(db_session, status="OFFERED")
    other = await add_second_order(db_session, scene, status="AUTHORIZED", void_source="age_guard")
    await set_order_status(db_session, other, "VOIDED")
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1
    for source in ("buyer_withdraw", "paypal_expired"):
        await set_order_status(db_session, other, "AUTHORIZED")
        await _set_void_source(db_session, other, source)
        await set_order_status(db_session, other, "VOIDED")
        assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1


async def _set_void_source(session: AsyncSession, order_id: UUID, source: str) -> None:
    await session.execute(
        text("UPDATE buyer_orders SET void_source = :source WHERE id = :id"),
        {"source": source, "id": order_id},
    )


async def test_vacancies_come_from_orders_not_a_counter_column(db_session: AsyncSession) -> None:
    """T03A02 acceptance: no counter column exists, so the count is the row set (I8)."""
    columns = (
        (
            await db_session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'lots'")
            )
        )
        .scalars()
        .all()
    )
    # refill_cutoff_at is a contracted deadline column, not a counter; what must not
    # exist is a stored tally that can drift from the rows it claims to count.
    assert not [name for name in columns if any(w in name for w in ("vacanc", "taken", "seats_"))]
    scene = await make_scene(db_session, seats=2, status="OFFERED", offer_in=-1)
    other = await add_second_order(db_session, scene, status="OFFERED")
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 0
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(scene.order_id)})
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(other)})
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 2


async def test_a_priced_out_seat_counts_as_a_vacancy(db_session: AsyncSession) -> None:
    """T03A02 acceptance: PRICED_OUT allocations free a seat at award time (I8)."""
    scene = await make_scene(db_session, seats=2, status="OFFERED")
    from tests.unit.test_checkout_engine import add_entry, add_user

    entry_id = await add_entry(db_session, scene.pool_id, user_id=await add_user(db_session))
    await insert_allocation(db_session, scene.pool_id, entry_id, scene.lot_id, status="PRICED_OUT")
    assert await expiry_handler(scene).claimable_vacancies(db_session, scene.lot_id) == 1


async def test_the_engine_gate_stops_a_vault_offer_expiry_timer(db_session: AsyncSession) -> None:
    """T03A02 acceptance: vault_charge orders carry no buyer offer-expiry timer."""
    scene = await make_scene(db_session, mode="vault_charge", offer_in=-600)
    await insert_vault_token(db_session, scene.entry_id, scene.user_id)
    await expiry_handler(scene).expire(db_session, {"buyer_order_id": str(scene.order_id)})
    assert await stored_status(db_session, scene.order_id) == "OFFERED"
    assert scene.ports.jobs.jobs == []
    outcome = await scene.ports.engine.apply(
        db_session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="CAPTURING",
            trigger=trigger_for("BO-23"),
        ),
    )
    assert outcome.transition_id == "BO-23"


async def test_lease_reclaim_of_a_done_job_duplicates_nothing(db_session: AsyncSession) -> None:
    """T03A02 acceptance: a redelivered offer.expire returns the original outcome."""
    scene = await make_scene(db_session, status="ORDER_CREATED", offer_in=-1)
    payload = {"buyer_order_id": str(scene.order_id)}
    await expiry_handler(scene).expire(db_session, payload)
    first_jobs = list(scene.ports.jobs.jobs)
    await expiry_handler(scene).expire(db_session, payload)
    assert scene.ports.jobs.jobs == first_jobs
    assert await stored_status(db_session, scene.order_id) == "EXPIRED"


def test_active_state_set_matches_the_contract() -> None:
    """PT-12 model: the active set the model uses is the contract's own."""
    assert tuple(ACTIVE_STATES_SOURCE) == tuple(MACHINES["buyer_order"].active)
    assert set(LOCKED_STATES) <= set(MACHINES["buyer_order"].active)
    assert set(LOCKED_STATES).isdisjoint(EXPIRABLE)
    assert {
        transition.id
        for transition in TRANSITIONS_BY_ID.values()
        if transition.to_state == "EXPIRED"
    } == {"BO-15", "BO-16", "BO-17"}
