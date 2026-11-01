"""``order.resolve`` and ``reconciler.sweep``: heal stale orders, never invent a state.

Contract: ``domain-ports.md`` section 5 (job kinds), ``state-machines.md`` BO-02,
BO-15 to BO-17 and CR-3 note 1.

The sweep is a reader: it finds buyer orders that no timer will move again --
APPROVED seats without a running authorize job, offers whose stored deadline has
passed, and AUTHORIZING rows whose seat horizon has passed -- and enqueues
``order.resolve`` for each, with the ``bo:{buyer_order_id}`` concurrency key.

``order.resolve`` itself only re-enqueues an **existing** trigger:

* APPROVED or AUTHORIZING -> ``order.authorize`` (BO-03/04/05/20; the authorize
  handler replays its own key, so an unknown outcome is healed by the same
  identity and never by a new one);
* an OFFERED or ORDER_CREATED offer past ``offer_expires_at`` -> ``offer.expire``
  (BO-15/BO-16).

It never writes ``buyer_orders.status`` and never applies a transition. An order
in any other state, or an expired row that is already terminal, is left alone.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.checkout import BuyerOrder
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError
from fairpool.ports import Clock, JobQueue

logger: Final[logging.Logger] = logging.getLogger("fairpool.reconciler")

#: States whose stored offer deadline is final: past it no timer may remain.
EXPIRING_STATES: Final[frozenset[str]] = frozenset({"OFFERED", "ORDER_CREATED"})

#: States the authorize trigger owns.
AUTHORIZE_STATES: Final[frozenset[str]] = frozenset({"APPROVED", "AUTHORIZING"})

#: One sweep never enqueues more than this, so a large backlog cannot make a
#: single admin call unbounded.
BATCH_SIZE: Final[int] = 200


def _grace_seconds(timeline: dict[str, Any], default: int = 120) -> int:
    value = timeline.get("capture_grace_s", default)
    return int(value) if isinstance(value, int) else default


class Reconciler:
    """The ``reconciler.sweep`` and ``order.resolve`` handlers."""

    def __init__(self, *, clock: Clock, jobs: JobQueue, batch_size: int = BATCH_SIZE) -> None:
        self.clock = clock
        self.jobs = jobs
        self.batch_size = batch_size

    async def sweep(self, session: AsyncSession, payload: dict[str, Any]) -> int:
        """Enqueue one ``order.resolve`` per stale order and return the count."""
        wall_now = await self.clock.db_wall_now(session)
        rows = (
            await session.execute(
                select(
                    BuyerOrder.id,
                    BuyerOrder.status,
                    BuyerOrder.offer_expires_at,
                    BuyerOrder.seat_locked_until,
                    BuyerOrder.updated_at,
                    Pool.timeline,
                )
                .join(Lot, Lot.id == BuyerOrder.lot_id)
                .join(Pool, Pool.id == Lot.pool_id)
                .where(
                    BuyerOrder.status.in_(
                        [
                            *sorted(EXPIRING_STATES),
                            *sorted(AUTHORIZE_STATES),
                        ]
                    )
                )
                .order_by(BuyerOrder.updated_at, BuyerOrder.id)
                .limit(self.batch_size)
            )
        ).all()
        now = await self.clock.db_now(session)
        enqueued = 0
        for row in rows:
            if not self._is_stale(row, wall_now):
                continue
            await self._enqueue(session, "order.resolve", row.id, now)
            enqueued += 1
        return enqueued

    async def resolve(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Re-enqueue the existing trigger for one order; never change a state."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        status = str(order.status)
        now = await self.clock.db_now(session)
        if status in AUTHORIZE_STATES:
            await self._enqueue(session, "order.authorize", order.id, now)
            return
        wall_now = await self.clock.db_wall_now(session)
        if (
            status in EXPIRING_STATES
            and order.offer_expires_at is not None
            and wall_now >= order.offer_expires_at
        ):
            await self._enqueue(session, "offer.expire", order.id, now)
            return
        logger.info("reconciler.resolve.skipped buyer_order_id=%s status=%s", order.id, status)

    async def _enqueue(
        self, session: AsyncSession, kind: str, buyer_order_id: UUID, run_at: Any
    ) -> None:
        await self.jobs.enqueue(
            session,
            kind,
            {"buyer_order_id": str(buyer_order_id)},
            run_at=run_at,
            concurrency_key=f"bo:{buyer_order_id}",
        )

    def _is_stale(self, row: Any, wall_now: Any) -> bool:
        status = str(row.status)
        if status == "APPROVED":
            # The approval job may simply be pending; the sweep is idempotent and
            # the authorize handler replays under its own key (I9).
            return True
        if status == "AUTHORIZING":
            grace = timedelta(seconds=_grace_seconds(row.timeline))
            horizon = row.seat_locked_until or (row.updated_at + grace)
            return bool(wall_now >= horizon)
        if status in EXPIRING_STATES:
            return bool(row.offer_expires_at is not None and wall_now >= row.offer_expires_at)
        return False


__all__ = ["AUTHORIZE_STATES", "EXPIRING_STATES", "Reconciler"]
