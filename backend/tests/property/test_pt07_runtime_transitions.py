"""PT-07 as runtime behaviour of the engine, not only of the pure table.

``tests/property/test_pt07_transitions.py`` proves the whitelist itself. This file
asks the same question of a real row: an unlisted (from, to) pair must never move a
``buyer_orders`` row and must never write an audit, ledger or job effect, and every
listed edge must move the row to the state its contract line names, from a database
state built for it (I10).

Hypothesis drives synchronous test bodies, so the engine runs on a dedicated event
loop with one connection held open for the module and each example rolled back to a
savepoint. ``drive`` is shared with the other checkout property files.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from fairpool.db.session import normalize_database_url
from fairpool.domain import checkout_guards
from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.states import MACHINES, TRANSITIONS_BY_ID
from fairpool.modules.checkout.engine import TransitionRequest
from tests.conftest import database_url
from tests.unit.test_checkout_engine import (
    Scene,
    ensure_vault_token,
    insert_authorization,
    insert_capture,
    insert_paypal_order,
    insert_refund,
    make_scene,
    set_lot_status,
    stamp_lot,
    stored_status,
    trigger_for,
)

pytestmark = pytest.mark.property

BO_PAIRS = {
    (from_state, transition.to_state)
    for transition in MACHINES["buyer_order"].transitions
    for from_state in transition.from_states
}
BO_STATES = tuple(MACHINES["buyer_order"].states)
BO_IDS = tuple(
    transition.id
    for transition in TRANSITIONS_BY_ID.values()
    if transition.machine == "buyer_order"
)
#: Both sets come from the contract rather than a list typed twice here: the vault
#: ids from the guards' own set, the expiry ids from the edges into EXPIRED.
VAULT_IDS = checkout_guards.VAULT_ONLY
EXPIRY_IDS = {
    transition.id
    for transition in TRANSITIONS_BY_ID.values()
    if transition.machine == "buyer_order" and transition.to_state == "EXPIRED"
}

_DRIVER: dict[str, Any] = {}


def _open_driver() -> None:
    if _DRIVER:
        return
    loop = asyncio.new_event_loop()
    url, connect_args = normalize_database_url(database_url())
    engine = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)

    async def _connect() -> tuple[Any, Any]:
        connection = await engine.connect()
        transaction = await connection.begin()
        return connection, transaction

    connection, transaction = loop.run_until_complete(_connect())
    _DRIVER.update(loop=loop, engine=engine, connection=connection, transaction=transaction)


def _close_driver() -> None:
    if not _DRIVER:
        return

    async def _disconnect() -> None:
        await _DRIVER["transaction"].rollback()
        await _DRIVER["connection"].close()
        await _DRIVER["engine"].dispose()

    _DRIVER["loop"].run_until_complete(_disconnect())
    _DRIVER["loop"].close()
    _DRIVER.clear()


@pytest.fixture(scope="module", autouse=True)
def driver(migrated_db: None) -> Iterator[None]:
    _open_driver()
    try:
        yield
    finally:
        _close_driver()


def drive(work: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
    """Run one example against a fresh savepoint and roll it back afterwards."""

    async def _once() -> Any:
        session = AsyncSession(
            bind=_DRIVER["connection"],
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        nested = await session.begin_nested()
        try:
            return await work(session)
        finally:
            await nested.rollback()
            session.expunge_all()

    return _DRIVER["loop"].run_until_complete(_once())


def scene_kwargs(transition_id: str) -> dict[str, Any]:
    """The scene each listed edge needs: its mode stamp and its offer window."""
    if transition_id in VAULT_IDS:
        return {"mode": "vault_charge"}
    if transition_id in EXPIRY_IDS:
        return {"offer_in": -1}
    return {}


async def stamp(session: AsyncSession, scene: Scene, transition_id: str) -> None:
    await stamp_lot(
        session,
        scene.lot_id,
        mode="vault_charge" if transition_id in VAULT_IDS else "authorize_capture",
        router="single_seller",
    )


async def prepare(session: AsyncSession, scene: Scene, transition_id: str) -> TransitionRequest:
    """Build the database state and the evidence one listed edge demands.

    Every row here is what the handler that owns the money call would persist
    before asking the engine to move the order (paypal-adapter.md section 7).
    """
    transition = TRANSITIONS_BY_ID[transition_id]
    await set_lot_status(session, scene.lot_id, "CHECKOUT_OPEN")
    if transition_id == "BO-06":
        await set_lot_status(session, scene.lot_id, "FUNDING")
    if transition_id == "BO-13":
        await set_lot_status(session, scene.lot_id, "FAILING")
    if transition_id in VAULT_IDS:
        await ensure_vault_token(
            session,
            scene.entry_id,
            scene.user_id,
            status="SETUP_PENDING" if transition_id == "BO-27" else "ACTIVE",
        )

    paypal_order_id = await insert_paypal_order(session, scene.order_id)
    observation: Any = None
    void_source: str | None = None
    reject_reason: str | None = None
    refund_seq: int | None = None
    seat_locked_until: Any = None

    if transition_id == "BO-02":
        observation = _observation("approval", "APPROVED", paypal_order_id, 50_000)
    elif transition_id == "BO-03":
        seat_locked_until = scene.now
    elif transition_id in {"BO-04", "BO-05", "BO-20"}:
        auth_id = await insert_authorization(
            session,
            scene.order_id,
            paypal_order_id=paypal_order_id,
            status="DENIED" if transition_id == "BO-05" else "CREATED",
        )
        observation = _observation(
            "authorization",
            "DENIED" if transition_id == "BO-05" else "CREATED",
            auth_id,
            49_999 if transition_id == "BO-20" else 50_000,
        )
        if transition_id == "BO-20":
            reject_reason = "AMOUNT_MISMATCH"
    elif transition_id == "BO-06":
        # BO-06 opens the capture: the authorization its key names was persisted by
        # the authorize step, and no capture result exists yet (I7, CR-3 note 4).
        await insert_authorization(session, scene.order_id, paypal_order_id=paypal_order_id)
    elif transition_id in {"BO-07", "BO-08", "BO-09", "BO-10", "BO-11", "BO-24", "BO-25", "BO-26"}:
        auth_id = await insert_authorization(
            session, scene.order_id, paypal_order_id=paypal_order_id
        )
        capture_id = await insert_capture(
            session,
            scene.order_id,
            auth_id=auth_id,
            status=_CAPTURE_STATUS[transition_id],
        )
        observation = _observation(
            "charge" if transition_id in {"BO-25", "BO-26"} else "capture",
            _CAPTURE_STATUS[transition_id],
            capture_id,
            50_000,
        )
    elif transition_id == "BO-12":
        auth_id = await insert_authorization(
            session, scene.order_id, paypal_order_id=paypal_order_id
        )
        observation = _observation("authorization", "VOIDED", auth_id, None)
        void_source = "buyer_withdraw"
    elif transition_id == "BO-13":
        auth_id = await insert_authorization(
            session, scene.order_id, paypal_order_id=paypal_order_id
        )
        capture_id = await insert_capture(session, scene.order_id, auth_id=auth_id)
        # BO-13 is backed by the capture being refunded, not by a refund row that
        # does not exist until the call returns (BO-14 then reads its status).
        observation = _observation("capture", "COMPLETED", capture_id, 50_000)
        refund_seq = 1
    elif transition_id == "BO-14":
        await set_lot_status(session, scene.lot_id, "FAILING")
        auth_id = await insert_authorization(
            session, scene.order_id, paypal_order_id=paypal_order_id
        )
        capture_id = await insert_capture(session, scene.order_id, auth_id=auth_id)
        refund_id = await insert_refund(session, scene.order_id, capture_id)
        observation = _observation("refund", "COMPLETED", refund_id, 50_000)
        refund_seq = 1
    elif transition_id == "BO-18":
        # The GET shows an order this buyer never approved: the checks failed, so
        # BO-18 rejects it and BO-02's edge stays shut (FR-CK-05).
        observation = Observation(
            "approval",
            "CREATED",
            paypal_order_id,
            amount_cents=50_000,
            currency="USD",
            checks_passed=False,
        )
        reject_reason = "WRONG_COUNTRY"
    elif transition_id == "BO-19":
        reject_reason = "DUPLICATE_PAYER"
    return TransitionRequest(
        buyer_order_id=scene.order_id,
        to_state=transition.to_state,
        trigger=trigger_for(transition_id),
        observation=observation,
        void_source=void_source,
        reject_reason=reject_reason,
        refund_seq=refund_seq,
        seat_locked_until=seat_locked_until,
        actor=f"test.pt07.{transition_id}",
    )


_CAPTURE_STATUS = {
    "BO-07": "COMPLETED",
    "BO-08": "PENDING",
    "BO-09": "COMPLETED",
    "BO-10": "DECLINED",
    "BO-11": "FAILED",
    "BO-24": "COMPLETED",
    "BO-25": "PENDING",
    "BO-26": "DENIED",
}


def _observation(kind: str, status: str, reference: str, amount: int | None) -> Observation:
    return Observation(
        kind=kind,
        status=status,
        reference=reference,
        amount_cents=amount,
        currency="USD",
        checks_passed=True if kind == "approval" else None,
        payee_matches=True,
    )


def _effect_tally(scene: Scene) -> tuple[int, int, int, int]:
    """How much the ports have been asked to write: audit, ledger, jobs, notify.

    A refusal must leave this untouched, which is the effect half of I10 stated as
    a number the walk can compare before and after a step.
    """
    return (
        len(scene.ports.audit.rows),
        len(scene.ports.ledger.entries),
        len(scene.ports.jobs.jobs),
        len(scene.ports.notifier.calls),
    )


@settings(max_examples=24, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(transition_id=st.sampled_from(BO_IDS))
def test_every_listed_edge_moves_a_real_row_to_the_stated_state(transition_id: str) -> None:
    """PT-07 runtime: each listed transition applies to a row in its own from state."""
    transition = TRANSITIONS_BY_ID[transition_id]

    async def _work(session: AsyncSession) -> str:
        scene = await make_scene(
            session, status=transition.from_states[0], **scene_kwargs(transition_id)
        )
        request = await prepare(session, scene, transition_id)
        outcome = await scene.ports.engine.apply(session, request)
        assert outcome.transition_id == transition_id
        assert outcome.to_state == transition.to_state
        assert outcome.applied is True
        return await stored_status(session, scene.order_id)

    assert drive(_work) == transition.to_state


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    from_state=st.sampled_from(BO_STATES),
    to_state=st.sampled_from(BO_STATES),
    trigger=st.sampled_from(["job:order.capture", "buyer.continue", "job:offer.expire", "x"]),
)
def test_an_unlisted_pair_never_moves_a_row_and_writes_nothing(
    from_state: str, to_state: str, trigger: str
) -> None:
    """PT-07 runtime: the whitelist is the only gate; a refusal writes no effect (I10)."""
    assume((from_state, to_state) not in BO_PAIRS)

    async def _work(session: AsyncSession) -> None:
        scene = await make_scene(session, status=from_state)
        with pytest.raises(IllegalTransition):
            await scene.ports.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=scene.order_id, to_state=to_state, trigger=trigger
                ),
            )
        assert await stored_status(session, scene.order_id) == from_state
        assert scene.ports.audit.rows == []
        assert scene.ports.ledger.entries == []
        assert scene.ports.jobs.jobs == []
        assert scene.ports.notifier.calls == []

    drive(_work)


@settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@example(chosen=["BO-01", "BO-01", "BO-21"])
@given(st.lists(st.sampled_from(BO_IDS), min_size=2, max_size=6))
def test_a_walk_of_refused_edges_leaves_the_row_where_the_whitelist_put_it(
    chosen: list[str],
) -> None:
    """PT-07 runtime: applying edges out of order cannot reach a state off the table.

    Each step is applied from whatever state the row is really in, and legality is
    the *pair's*: the whitelist keys it on (from, to), so the edge that matches a
    pair is not necessarily the one whose id was drawn. A pair the table does not
    list from this state must leave the row exactly where it was and write no effect
    (I10); a request naming the state the row already holds is answered like an
    idempotency store and never applied twice (I9).
    """
    model_states = set(BO_STATES)

    async def _work(session: AsyncSession) -> str:
        scene = await make_scene(session, status="OFFERED")
        for transition_id in chosen:
            transition = TRANSITIONS_BY_ID[transition_id]
            current = await stored_status(session, scene.order_id)
            assert current in model_states
            effects = _effect_tally(scene)
            if (current, transition.to_state) not in BO_PAIRS:
                # No edge for this pair from the state the row is really in. Two
                # refusals are possible and both apply nothing: IllegalTransition
                # for a pair the table does not list, and for a pair that names the
                # state the row already sits in, that same refusal or a conflict
                # when the request key already carries a different payload (I9).
                with pytest.raises((IllegalTransition, ApplicationError)):
                    await scene.ports.engine.apply(
                        session,
                        TransitionRequest(
                            buyer_order_id=scene.order_id,
                            to_state=transition.to_state,
                            trigger=trigger_for(transition_id),
                            actor="test.pt07.refused",
                        ),
                    )
                assert await stored_status(session, scene.order_id) == current
                assert _effect_tally(scene) == effects
                continue
            await set_lot_status(session, scene.lot_id, "CHECKOUT_OPEN")
            await stamp(session, scene, transition_id)
            request = await prepare(session, scene, transition_id)
            try:
                outcome = await scene.ports.engine.apply(session, request)
            except IllegalTransition:
                # A listed edge whose guard the stored data does not satisfy: the
                # row stays where it was and no effect is written (I10).
                assert await stored_status(session, scene.order_id) == current
                assert _effect_tally(scene) == effects
                continue
            assert outcome.applied is True
            assert outcome.to_state == transition.to_state
            assert await stored_status(session, scene.order_id) == transition.to_state
            applied = _effect_tally(scene)
            # Asking for the same transition again while the row sits in its target
            # state replays the stored outcome; it does not apply a second time (I9).
            replay = await scene.ports.engine.apply(session, request)
            assert replay.applied is False
            assert replay.transition_id == outcome.transition_id
            assert replay.idempotency_key == outcome.idempotency_key
            assert await stored_status(session, scene.order_id) == transition.to_state
            assert _effect_tally(scene) == applied
        return await stored_status(session, scene.order_id)

    assert drive(_work) in model_states


def test_the_engine_reads_no_second_transition_table() -> None:
    """PT-07 runtime: the engine and the guard module share the contract table."""
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2] / "src" / "fairpool"
    for name in ("modules/checkout/engine.py", "modules/checkout/expiry.py"):
        source = (backend / name).read_text(encoding="utf-8")
        assert (
            "MACHINES" in source or "assert_transition" in source or "TRANSITIONS_BY_ID" in source
        )
        tree = ast.parse(source)
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        # No transition id is written into the module: ids come from the table only.
        state_names = set(MACHINES["buyer_order"].states)
        assert not (literals & {f"BO-{index:02d}" for index in range(1, 40)})
        assert not (literals & state_names) or name.endswith("expiry.py")
