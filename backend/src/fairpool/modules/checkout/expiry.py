"""Offer expiry and seat control (T03A02; BO-15 to BO-17, I7, I8, F5).

The ``offer.expire`` job handler. It owns three decisions and nothing else:

* Only the states the contract lists may expire on this trigger. AUTHORIZING,
  CAPTURING and CAPTURE_PENDING have no edge into EXPIRED, and no timer or job
  lease alone releases such a seat: an unknown outcome is not proof of failure
  (I7, N4, F5, CR-3 note 4).
* The deadline is the stored ``offer_expires_at`` compared with the wall clock read
  *after* the locks, so a timer that fires early does nothing and a transaction that
  waited on a lock across its deadline cannot act on a stale time (I15, CR-3 note 1).
* A vacancy is computed from the lot's orders and allocations under the lot lock,
  never from a counter column, and one valid vacancy means one deduplicated
  ``lot.refill`` (I8, ``domain-ports.md`` section 5 and section 6, the vacancy rule
  after the buyer_order table).

The ``lot.refill`` handler itself is deliberately not here: the funding tasks own
it, and an enqueue is not evidence that work happened (``domain-ports.md`` section 5).
"""

from __future__ import annotations

import logging
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import BuyerOrder
from fairpool.db.models.enums import AllocationStatus, BuyerOrderStatus
from fairpool.db.models.pools import Allocation, Lot
from fairpool.domain import checkout_guards
from fairpool.domain.states import MACHINES
from fairpool.modules.checkout.engine import (
    CheckoutEngine,
    GuardDecision,
    TransitionRequest,
    alert_illegal_transition,
    lot_advisory_lock_key,
)
from fairpool.ports import JobQueue

logger = logging.getLogger("fairpool.checkout.expiry")

#: The trigger that owns these edges; the whitelist stays the only source (I10).
EXPIRE_TRIGGER: Final[str] = "job:offer.expire"
EXPIRED_STATE: Final[str] = "EXPIRED"

#: The buyer_order states that still hold a seat, read from the machine table so
#: this list cannot drift away from the contract (``states.BUYER_ORDER.active``).
ACTIVE_STATES: Final[tuple[str, ...]] = MACHINES["buyer_order"].active


class OfferExpiry:
    """The ``offer.expire`` handler plus the seat-vacancy read it needs."""

    def __init__(self, *, engine: CheckoutEngine, jobs: JobQueue) -> None:
        self.engine = engine
        self.jobs = jobs

    async def expire(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Expire one offer when the whitelist and the stored deadline both allow it.

        Registered as the ``offer.expire`` job handler: the payload carries a buyer
        order id and nothing else (``domain-ports.md`` section 5).
        """
        if "buyer_order_id" not in payload:
            raise ValueError("offer.expire needs a buyer_order_id")
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        decision = await self.evaluate(session, buyer_order_id)
        if decision.illegal_pair:
            # AUTHORIZING, CAPTURING, CAPTURE_PENDING and every terminal state have
            # no edge into EXPIRED: alert as CR-3 note 5 requires, keep the seat and
            # let the job finish. Only the money path decides those orders (I7, F5).
            self._alert_stale_timer(decision, buyer_order_id)
            return
        if decision.reason is not None:
            # A listed edge whose guard the stored data does not satisfy: the timer
            # fired early, or the lot is stamped vault_charge and has no buyer offer
            # window (vault-charge.md section 3). Nothing happens and no seat moves;
            # a genuinely missed deadline is healed by the reconciler, not guessed here.
            logger.info(
                "checkout.offer_expiry.skipped buyer_order_id=%s reason=%s",
                buyer_order_id,
                decision.reason,
            )
            return
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state=EXPIRED_STATE,
                trigger=EXPIRE_TRIGGER,
                actor="worker:offer.expire",
            ),
        )
        if await self.claimable_vacancies(session, decision.lot_id) > 0:
            # The transition's own ``job:lot.refill`` effect already queued one under
            # this same dedupe key; asking again is what makes "one refill per valid
            # vacancy" true even when a caller reached the vacancy by another route.
            await self.enqueue_refill(session, decision.lot_id)

    async def evaluate(self, session: AsyncSession, buyer_order_id: UUID) -> GuardDecision:
        """Ask the engine, under its locks, whether this offer may expire right now."""
        return await self.engine.decide(
            session,
            buyer_order_id=buyer_order_id,
            to_state=EXPIRED_STATE,
            trigger=EXPIRE_TRIGGER,
        )

    async def claimable_vacancies(self, session: AsyncSession, lot_id: UUID) -> int:
        """Claimable vacancies on a lot, computed under the lot's own locks.

        Two numbers decide it and both come from rows, never from a counter column:
        the seats still free (``seats`` minus the active orders, the refill rule of
        ``domain-ports.md`` section 6) and the orders and PRICED_OUT allocations that
        the vacancy rule says actually freed a seat. A VOIDED with
        ``void_source = lot_failing`` is in neither, so it counts as no vacancy, and
        the lower of the two is returned so a count can never offer more seats than
        the lot has (I8).
        """
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": lot_advisory_lock_key(lot_id)}
        )
        lot = await session.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
        if lot is None:
            return 0
        active_statuses = [BuyerOrderStatus(state) for state in ACTIVE_STATES]
        active_orders = int(
            await session.scalar(
                select(func.count())
                .select_from(BuyerOrder)
                .where(BuyerOrder.lot_id == lot_id, BuyerOrder.status.in_(active_statuses))
            )
            or 0
        )
        free_seats = int(lot.seats) - active_orders
        if free_seats <= 0:
            # I8: offers in flight plus committed buyers never exceed lot seats.
            return 0
        released = [BuyerOrderStatus(state) for state in sorted(checkout_guards.VACANCY_STATES)]
        void_sources = sorted(checkout_guards.VACANCY_VOID_SOURCES)
        freed_orders = int(
            await session.scalar(
                select(func.count())
                .select_from(BuyerOrder)
                .where(
                    BuyerOrder.lot_id == lot_id,
                    or_(
                        BuyerOrder.status.in_(released),
                        and_(
                            BuyerOrder.status == BuyerOrderStatus.VOIDED,
                            BuyerOrder.void_source.in_(void_sources),
                        ),
                    ),
                )
            )
            or 0
        )
        priced_out = int(
            await session.scalar(
                select(func.count())
                .select_from(Allocation)
                .where(
                    Allocation.lot_id == lot_id,
                    Allocation.status == AllocationStatus.PRICED_OUT,
                )
            )
            or 0
        )
        return min(free_seats, freed_orders + priced_out)

    async def enqueue_refill(self, session: AsyncSession, lot_id: UUID) -> UUID | None:
        """One deduplicated ``lot.refill`` per lot, under key ``refill:{lot_id}``."""
        return await self.jobs.enqueue(
            session,
            "lot.refill",
            {"lot_id": str(lot_id)},
            concurrency_key=f"lot:{lot_id}",
            dedupe_key=f"refill:{lot_id}",
        )

    def _alert_stale_timer(self, decision: GuardDecision, buyer_order_id: UUID) -> None:
        """Write the illegal-transition alert with the ids the engine already read."""
        alert_illegal_transition(
            machine="buyer_order",
            from_state=decision.from_state,
            to_state=EXPIRED_STATE,
            trigger=EXPIRE_TRIGGER,
            reason=f"{decision.reason}; the seat is kept (I7, N4, F5)",
            pool_id=decision.pool_id,
            lot_id=decision.lot_id,
            buyer_order_id=buyer_order_id,
        )
