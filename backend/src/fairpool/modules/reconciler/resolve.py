"""``order.resolve`` and ``reconciler.sweep``: heal stale orders, never invent a state.

Contract: ``domain-ports.md`` section 5 (job kinds), ``state-machines.md`` BO-02,
BO-07/BO-08/BO-11, BO-24/BO-25/BO-26, BO-15 to BO-17, CR-3 note 1 and
``vault-charge.md`` section 7.

The sweep is a reader: it finds buyer orders that no timer will move again --
APPROVED seats without a running authorize job, offers whose stored deadline has
passed, AUTHORIZING rows whose seat horizon has passed, and CAPTURING rows older than
``capture_grace_s`` (an unknown capture or charge outcome) -- and enqueues
``order.resolve`` for each, with the ``bo:{buyer_order_id}`` concurrency key.

``order.resolve`` itself re-enqueues an **existing** trigger, or settles a CAPTURING
row through the handler that owns it:

* APPROVED or AUTHORIZING -> ``order.authorize`` (BO-03/04/05/20; the authorize
  handler replays its own key, so an unknown outcome is healed by the same
  identity and never by a new one);
* an OFFERED or ORDER_CREATED offer past ``offer_expires_at`` -> ``offer.expire``
  (BO-15/BO-16);
* CAPTURING -> ``resolve_charge``, which reads the provider resource back by the
  stored id (or replays the same request key) and applies BO-07/08/11 or
  BO-24/25/26 under that same identity (``vault-charge.md`` section 7).

It never writes ``buyer_orders.status`` itself and never applies a transition of its
own. An order in any other state, or an expired row that is already terminal, is
left alone.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
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

#: The state an unknown capture or vault-charge outcome leaves behind.
CAPTURING_STATE: Final[str] = "CAPTURING"

#: One sweep never enqueues more than this, so a large backlog cannot make a
#: single admin call unbounded.
BATCH_SIZE: Final[int] = 200

#: What replaces a webhook's raw body once its retention window has passed. The
#: ids, amounts and status of the event stay; the payer's words do not (I14).
EXPIRED_BODY: Final[str] = "[expired]"

#: Config default for ``WEBHOOK_RAW_RETENTION_S``: one week.
WEBHOOK_RAW_RETENTION_S: Final[int] = 604800

#: What the checkout layer supplies so a CAPTURING row can be settled by evidence.
type ResolveCharge = Callable[[AsyncSession, UUID], Awaitable[None]]


def _grace_seconds(timeline: dict[str, Any], default: int = 120) -> int:
    value = timeline.get("capture_grace_s", default)
    return int(value) if isinstance(value, int) else default


class Reconciler:
    """The ``reconciler.sweep`` and ``order.resolve`` handlers."""

    def __init__(
        self,
        *,
        clock: Clock,
        jobs: JobQueue,
        batch_size: int = BATCH_SIZE,
        resolve_charge: ResolveCharge | None = None,
        webhook_raw_retention_s: int = WEBHOOK_RAW_RETENTION_S,
    ) -> None:
        self.clock = clock
        self.jobs = jobs
        self.batch_size = batch_size
        # Wired by the composition root to the checkout handlers that own the money
        # call; without it a CAPTURING row is reported and left alone, never guessed.
        self.resolve_charge = resolve_charge
        self.webhook_raw_retention_s = webhook_raw_retention_s

    async def sweep(self, session: AsyncSession, payload: dict[str, Any]) -> int:
        """Enqueue one ``order.resolve`` per stale order and return the count."""
        wall_now = await self.clock.db_wall_now(session)
        await self._expire_webhook_bodies(session, wall_now)
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
                            CAPTURING_STATE,
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

    async def _expire_webhook_bodies(self, session: AsyncSession, wall_now: Any) -> None:
        """Replace raw bodies past the retention window; the row itself stays.

        A stored delivery is evidence that something was sent (P4), so the row is
        never deleted; only the part that carries the payer's identity is. The sweep
        is where this belongs because it is the one job that runs on a schedule.

        Migration ``0001`` installs ``trg_webhook_raw_immutable``, so the database
        refuses this update today: it is a change request and a new migration, not a
        decision this module may take on its own. The attempt runs in its own
        savepoint, so a refused retention pass is one logged line rather than a sweep
        that never enqueues anything; the day the migration lands, this starts working
        with no other change.
        """
        cutoff = wall_now - timedelta(seconds=self.webhook_raw_retention_s)
        try:
            async with session.begin_nested():
                await session.execute(
                    text(
                        "UPDATE webhook_events SET raw_body = :marker "
                        "WHERE received_at < :cutoff AND raw_body <> :marker"
                    ),
                    {"marker": EXPIRED_BODY, "cutoff": cutoff},
                )
        except DBAPIError:
            logger.error(
                "reconciler.webhook_retention.blocked reason=raw_body_immutable retention_s=%s",
                self.webhook_raw_retention_s,
            )

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
        if status == CAPTURING_STATE:
            await self._settle_capturing(session, order.id)
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

    async def _settle_capturing(self, session: AsyncSession, buyer_order_id: UUID) -> None:
        """Hand one CAPTURING row to the handler that owns its provider call."""
        if self.resolve_charge is None:
            logger.error(
                "reconciler.resolve.unwired buyer_order_id=%s status=%s",
                buyer_order_id,
                CAPTURING_STATE,
            )
            return
        await self.resolve_charge(session, buyer_order_id)

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
        if status == CAPTURING_STATE:
            # An unknown capture or charge outcome: the provider may have accepted
            # while our call timed out, so the row is read back, never re-done under
            # a new key (vault-charge.md section 7).
            grace = timedelta(seconds=_grace_seconds(row.timeline))
            return bool(wall_now >= row.updated_at + grace)
        if status in EXPIRING_STATES:
            return bool(row.offer_expires_at is not None and wall_now >= row.offer_expires_at)
        return False


__all__ = [
    "AUTHORIZE_STATES",
    "CAPTURING_STATE",
    "EXPIRED_BODY",
    "EXPIRING_STATES",
    "Reconciler",
    "ResolveCharge",
]
