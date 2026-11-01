"""``lot.open_checkout``: offers within seats, timers and the LS-05 transition (T04A01).

Contract: ``state-machines.md`` LS-05, ``domain-ports.md`` section 6, FR-CK-01,
FR-CK-02, FR-LT-04, I8; ``vault-charge.md`` section 3 for the mode split.

The handler reads the award and the seats through ``AllocationReadService`` (the
port), never from a second query of its own, and then:

* creates one OFFERED buyer order per SEATED entry, capped at ``lot.seats``;
* fills priced-out vacancies by asking ``next_candidates`` until the vacancy count
  recomputed under the lot lock is zero or the waitlist has nobody affordable left
  (PT-08, I8);
* sets ``fund_deadline_at`` and ``refill_cutoff_at = fund_deadline_at`` (CR-4);
* in ``vault_charge`` every order is OFFERED and ``order.vault_charge`` is the
  timer, because that mode has no buyer payment window; in ``authorize_capture``
  the offer expires at ``offer_window_s`` and ``offer.expire`` is scheduled;
* schedules one ``lot.try_fund`` at the fund deadline and applies LS-05 through the
  whitelist with its audit, notifications and jobs (I10).

A replay is silent: a lot that is no longer AWARDED has already opened checkout.

``active_order_count``, ``create_offer`` and ``schedule_offer`` are module-level
because ``lot.refill`` writes the same offer rows with the same timer; one writer
keeps the two paths from drifting.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import BuyerOrder
from fairpool.db.models.enums import BuyerOrderStatus, LotStatus
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError
from fairpool.domain.states import MACHINES
from fairpool.modules.checkout.funding import apply_lot_transition, lock_lot
from fairpool.ports import (
    AllocationReadService,
    AuditLog,
    AwardView,
    Clock,
    JobQueue,
    Notifier,
    SeatView,
    Totals,
)

#: Active buyer-order states: an offer in flight or a committed buyer (I8).
ACTIVE_STATES: Final[tuple[str, ...]] = MACHINES["buyer_order"].active

#: The stamped modes this handler knows how to open (N8).
OPENABLE_MODES: Final[frozenset[str]] = frozenset(
    {"vault_charge", "authorize_capture", "capture_only"}
)


async def active_order_count(session: AsyncSession, lot_id: UUID) -> int:
    """Offers in flight plus committed buyers on one lot, read under the lot lock (I8)."""
    statuses = [BuyerOrderStatus(state) for state in ACTIVE_STATES]
    value = await session.scalar(
        select(func.count())
        .select_from(BuyerOrder)
        .where(BuyerOrder.lot_id == lot_id, BuyerOrder.status.in_(statuses))
    )
    return int(value or 0)


async def create_offer(
    session: AsyncSession,
    *,
    lot: Lot,
    seat: SeatView,
    award: AwardView,
    expires_at: datetime,
    now: datetime,
) -> BuyerOrder:
    """One OFFERED seat order, priced from the award that seats it."""
    totals: Totals | None = award.totals.get(seat.entry_id)
    if totals is None:
        # An award that does not price a seated entry cannot produce an offer.
        raise ApplicationError("INTEGRITY_ERROR")
    order = BuyerOrder(
        id=uuid4(),
        lot_id=lot.id,
        entry_id=seat.entry_id,
        status=BuyerOrderStatus.OFFERED,
        current_attempt=0,
        offer_expires_at=expires_at,
        total_cents=int(totals.total_cents),
        breakdown={
            "item_cents": int(totals.item_cents),
            "shipping_cents": int(totals.shipping_cents),
            "tax_cents": int(totals.tax_cents),
        },
        updated_at=now,
    )
    session.add(order)
    await session.flush()
    return order


async def schedule_offer(
    session: AsyncSession,
    jobs: JobQueue,
    order: BuyerOrder,
    *,
    mode: str | None,
    expires_at: datetime,
    now: datetime,
) -> None:
    """LS-05's timer: in vault_charge the charge is the timer, there is no offer window."""
    kind = "order.vault_charge" if mode == "vault_charge" else "offer.expire"
    await jobs.enqueue(
        session,
        kind,
        {"buyer_order_id": str(order.id)},
        run_at=now if kind == "order.vault_charge" else expires_at,
        concurrency_key=f"bo:{order.id}",
    )


class OpenCheckoutHandler:
    """The ``lot.open_checkout`` job handler."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        notifier: Notifier,
        allocations: AllocationReadService,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.notifier = notifier
        self.allocations = allocations

    async def open(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        lot_id = UUID(str(payload["lot_id"]))
        lot = await lock_lot(session, lot_id)
        if str(lot.status) != str(LotStatus.AWARDED):
            # LS-05 already applied (or the lot never reached AWARDED): no effect.
            return

        view = await self.allocations.get_lot(session, lot_id)
        award = await self.allocations.get_award(session, lot_id)
        mode = None if view.payment_mode is None else str(view.payment_mode)
        if mode not in OPENABLE_MODES:
            raise ApplicationError("INTEGRITY_ERROR")

        now = await self.clock.db_now(session)
        fund_deadline_at = now + timedelta(seconds=int(view.fund_deadline_s))
        if mode == "vault_charge":
            # vault-charge.md section 3: no buyer payment window; the charge is the
            # timer and the seat is held until the funding decision.
            offer_expires_at = fund_deadline_at
        else:
            offer_expires_at = now + timedelta(seconds=int(view.offer_window_s))

        seats = list(await self.allocations.list_seated(session, lot_id))[: int(lot.seats)]
        # These seats are about to hold an offer, so they count as taken here (I8);
        # a vacancy is only what is left beyond them.
        vacancies = int(lot.seats) - await active_order_count(session, lot_id) - len(seats)
        while vacancies > 0:
            candidates = await self.allocations.next_candidates(session, lot_id, vacancies)
            if not candidates:
                break
            seats.extend(candidates)
            vacancies -= len(candidates)
        orders = [
            await create_offer(
                session, lot=lot, seat=seat, award=award, expires_at=offer_expires_at, now=now
            )
            for seat in seats
        ]

        lot.fund_deadline_at = fund_deadline_at
        # CR-4: the cutoff is the deadline, the last moment a refill could fund.
        lot.refill_cutoff_at = fund_deadline_at
        await session.flush()

        await apply_lot_transition(
            session,
            lot=lot,
            to_status="CHECKOUT_OPEN",
            trigger="job:lot.open_checkout",
            audit=self.audit,
            payload={
                "transition_id": "LS-05",
                "seats": int(lot.seats),
                "orders": len(orders),
                "payment_mode": mode,
            },
        )

        for order, seat in zip(orders, seats, strict=True):
            await schedule_offer(
                session,
                self.jobs,
                order,
                mode=mode,
                expires_at=offer_expires_at,
                now=now,
            )
            await self.notifier.notify(
                session,
                user_id=seat.user_id,
                kind="buyer_order.offered",
                payload={
                    "lot_id": str(lot.id),
                    "buyer_order_id": str(order.id),
                    "total_cents": int(order.total_cents),
                    "offer_expires_at": offer_expires_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                },
            )

        await self.jobs.enqueue(
            session,
            "lot.try_fund",
            {"lot_id": str(lot.id)},
            run_at=fund_deadline_at,
            concurrency_key=f"lot:{lot.id}",
            dedupe_key=f"try_fund:{lot.id}",
        )


__all__ = [
    "ACTIVE_STATES",
    "OPENABLE_MODES",
    "OpenCheckoutHandler",
    "active_order_count",
    "create_offer",
    "schedule_offer",
]
