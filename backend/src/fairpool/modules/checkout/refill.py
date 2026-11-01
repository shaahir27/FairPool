"""``lot.refill``: offer a vacancy to the waitlist, once per wave (T04A03/T04A05).

Contract: the vacancy rule after the ``buyer_order`` table, ``domain-ports.md``
section 6 ("Refill"), N12, CR-4.

A vacancy is never read from a counter: it is ``seats`` minus the active buyer
orders, recomputed under the lot lock, and the waitlist selection is the read
service's N12 rule (same zone, ascending rank, cap covers the awarded total, entry
still ELIGIBLE). The handler stops when the lot is past ``refill_cutoff_at``, when
the wave budget (``max_refill_waves``) is spent, or when the lot is no longer
CHECKOUT_OPEN/FUNDING. The counter is incremented in this same transaction, so two
refill jobs cannot both spend the last wave (I8, I10).

The offer row, its timer and the active-order count are the ones
``lot.open_checkout`` writes (``create_offer``, ``schedule_offer``,
``active_order_count``), so a refilled seat and an opened seat cannot differ.

A replay is silent because the first run already filled the vacancies: the
recomputed count is zero, so nothing is offered and no wave is spent.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.modules.checkout.funding import lock_lot
from fairpool.modules.checkout.open_checkout import (
    active_order_count,
    create_offer,
    schedule_offer,
)
from fairpool.ports import (
    AllocationReadService,
    AuditLog,
    Clock,
    JobQueue,
    LotView,
)

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.refill")

#: Only these lot states accept a refill (the vacancy rule, plus the optional
#: top-up after FUNDED is off).
REFILLABLE: Final[frozenset[str]] = frozenset({"CHECKOUT_OPEN", "FUNDING"})


class RefillService:
    """The ``lot.refill`` job handler."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        allocations: AllocationReadService,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.allocations = allocations

    async def refill(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        lot_id = UUID(str(payload["lot_id"]))
        lot = await lock_lot(session, lot_id)
        if str(lot.status) not in REFILLABLE:
            return
        wall_now = await self.clock.db_wall_now(session)
        if lot.refill_cutoff_at is None or wall_now >= lot.refill_cutoff_at:
            # Past the cutoff a refill could no longer fund the lot (CR-4).
            return
        view: LotView = await self.allocations.get_lot(session, lot_id)
        if int(lot.refill_waves) >= int(view.max_refill_waves):
            return

        vacancies = int(lot.seats) - await active_order_count(session, lot_id)
        if vacancies <= 0:
            return
        candidates = await self.allocations.next_candidates(session, lot_id, vacancies)
        if not candidates:
            return

        award = await self.allocations.get_award(session, lot_id)
        now = await self.clock.db_now(session)
        mode = None if view.payment_mode is None else str(view.payment_mode)
        if mode == "vault_charge":
            offer_expires_at = lot.fund_deadline_at or now
        else:
            offer_expires_at = now + timedelta(seconds=int(view.offer_window_s))

        orders = [
            await create_offer(
                session,
                lot=lot,
                seat=seat,
                award=award,
                expires_at=offer_expires_at,
                now=now,
            )
            for seat in candidates
        ]

        lot.refill_waves = int(lot.refill_waves) + 1
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action="lot.refilled",
            subject_type="lot",
            subject_id=str(lot.id),
            payload={
                "pool_id": str(lot.pool_id),
                "wave": int(lot.refill_waves),
                "offers": len(orders),
                "payment_mode": mode,
            },
        )
        for order, seat in zip(orders, candidates, strict=True):
            await schedule_offer(
                session,
                self.jobs,
                order,
                mode=mode,
                expires_at=offer_expires_at,
                now=now,
            )
            logger.info(
                "checkout.refill.offered lot_id=%s buyer_order_id=%s entry_id=%s",
                lot.id,
                order.id,
                seat.entry_id,
            )
        await self.jobs.enqueue(
            session,
            "lot.try_fund",
            {"lot_id": str(lot.id)},
            run_at=offer_expires_at,
            concurrency_key=f"lot:{lot.id}",
            dedupe_key=f"try_fund:{lot.id}",
        )


__all__ = ["REFILLABLE", "RefillService"]
