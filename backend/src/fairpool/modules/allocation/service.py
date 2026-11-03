"""``pool.allocate``: seeded ordering, lot formation and the waitlist (T04A05).

Contract: ``state-machines.md`` PS-05, PS-09 and LS-12, ``fairness-and-hashing.md``
section 5, ``domain-ports.md`` section 5, ``db-schema.md`` ``lots``/``allocations``.

The ordering is not computed here: ``domain/fairness.assign_lots`` ranks each
zone by ``(rank_hash, entry_id)`` and walks the frozen lot plan, so the backend
and the browser widget can reproduce the same result from the same published
seed (I11). This handler only persists the result:

* one ``allocations`` row per ELIGIBLE entry, with its zone rank and ``rank_hash``;
* one ``lots`` row per planned lot, in plan order, ``lot_order`` following zone
  order then ``lot_index`` (N7), and ``bid_open_at``/``bid_close_at`` derived from
  the frozen timeline (the pool closes, then the bid window opens);
* an undersized lot is created PLANNED and then moved to CANCELLED through LS-12
  in this same trigger, so its entries stay WAITLISTED for later lots (N2);
* PS-05 moves the pool SEEDED to ALLOCATED, and PS-09 completes a pool whose
  every lot was cancelled because then no lot can ever be awarded.

Nothing here decides a bid: it emits the PS-05 effect ``job:lot.bid_open`` for every
lot it leaves PLANNED, timed at the lot's own ``bid_open_at``, and the auction handlers
own the window from there.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import EntryReceipt, Pool, PoolEntry
from fairpool.db.models.enums import AllocationStatus, EntryStatus, LotStatus, PoolStatus
from fairpool.db.models.pools import Allocation, Lot
from fairpool.domain import fairness
from fairpool.domain.errors import ApplicationError
from fairpool.domain.states import assert_transition
from fairpool.ports import AuditLog, Clock, JobQueue

LOT_STATUS_PLANNED: Final[str] = "PLANNED"
LOT_STATUS_CANCELLED: Final[str] = "CANCELLED"


def _parse_iso(value: object) -> datetime:
    if not isinstance(value, str):
        raise ApplicationError("INTERNAL_ERROR")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lot_plan(pool: Pool) -> list[fairness.ZoneLotPlan]:
    plan: list[fairness.ZoneLotPlan] = []
    for zone in pool.lot_plan:
        plan.append(
            fairness.ZoneLotPlan(
                zone_id=str(zone["zone_id"]),
                lots=[
                    fairness.LotSpec(seats=int(lot["seats"]), min_seats=int(lot["min_seats"]))
                    for lot in zone["lots"]
                ],
            )
        )
    return plan


class AllocationService:
    """The ``pool.allocate`` job handler."""

    def __init__(self, clock: Clock, audit: AuditLog, jobs: JobQueue) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs

    async def allocate(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        pool_id = UUID(str(payload["pool_id"]))
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        existing = await session.scalar(
            select(func.count()).select_from(Allocation).where(Allocation.pool_id == pool.id)
        )
        if existing:
            # PS-05 already applied; a retry writes nothing (I15).
            return
        if str(pool.status) != str(PoolStatus.SEEDED):
            return
        if pool.seed_hex is None:
            # SEEDED without a seed is a broken snapshot, never a re-derivation.
            raise ApplicationError("INTEGRITY_ERROR")

        entries = await self._eligible_entries(session, pool.id)
        result = fairness.assign_lots(entries, _lot_plan(pool), str(pool.seed_hex))

        close_at = _parse_iso(pool.timeline.get("close_at"))
        bid_window_s = int(pool.timeline.get("bid_window_s", 120))
        bid_open_at = close_at
        bid_close_at = close_at + timedelta(seconds=bid_window_s)
        now = await self.clock.db_now(session)

        lots: dict[int, Lot] = {}
        cancelled: list[fairness.PlannedLot] = []
        for planned in result.lots:
            lot = Lot(
                id=uuid4(),
                pool_id=pool.id,
                zone_id=planned.zone_id,
                lot_index=planned.lot_index,
                lot_order=planned.lot_order,
                seats=planned.seats,
                min_seats=planned.min_seats,
                # LS-12 is applied below; the row is created PLANNED so the move
                # is a whitelisted transition with its own audit row (I10).
                status=LotStatus.PLANNED,
                bid_open_at=bid_open_at,
                bid_close_at=bid_close_at,
            )
            session.add(lot)
            await session.flush()
            lots[planned.lot_order] = lot
            if planned.status == LOT_STATUS_CANCELLED:
                cancelled.append(planned)

        for planned in cancelled:
            cancelled_lot = lots[planned.lot_order]
            # LS-12: entries available below min_seats (N2). The domain function
            # only marks a lot cancelled when it took fewer than min_seats.
            assert_transition("lot", "PLANNED", "CANCELLED", trigger="job:pool.allocate")
            cancelled_lot.status = LotStatus.CANCELLED
            await session.flush()
            await self.audit.append(
                session,
                actor="worker",
                action="lot.cancelled",
                subject_type="lot",
                subject_id=str(cancelled_lot.id),
                payload={
                    "pool_id": str(pool.id),
                    "transition_id": "LS-12",
                    "from": LOT_STATUS_PLANNED,
                    "to": LOT_STATUS_CANCELLED,
                    "zone_id": cancelled_lot.zone_id,
                    "lot_order": cancelled_lot.lot_order,
                },
            )

        for allocation in result.allocations:
            lot_id = None
            if allocation.lot_order is not None:
                lot_id = lots[allocation.lot_order].id
            session.add(
                Allocation(
                    id=uuid4(),
                    pool_id=pool.id,
                    entry_id=UUID(allocation.entry_id),
                    zone_id=allocation.zone_id,
                    rank=allocation.rank,
                    rank_hash=allocation.rank_hash,
                    lot_id=lot_id,
                    status=AllocationStatus(allocation.status),
                    created_at=now,
                )
            )
        await session.flush()

        # PS-05 with its audit row, in this same transaction (I10).
        assert_transition("pool", "SEEDED", "ALLOCATED", trigger="job:pool.allocate")
        pool.status = PoolStatus.ALLOCATED
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action="pool.allocated",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={
                "seed_is_demo": bool(pool.seed_is_demo),
                "lots": len(result.lots),
                "cancelled_lots": len(cancelled),
                "seated": sum(1 for item in result.allocations if item.lot_order is not None),
                "waitlisted": len(result.waitlist),
            },
        )

        # PS-05's declared effect (domain-ports.md section 5): every lot left PLANNED
        # gets its bidding window opened on a timer, and the job row is the timer (I15).
        for planned in result.lots:
            if planned.status != LOT_STATUS_PLANNED:
                continue
            lot = lots[planned.lot_order]
            await self.jobs.enqueue(
                session,
                "lot.bid_open",
                {"lot_id": str(lot.id)},
                run_at=lot.bid_open_at,
                concurrency_key=f"lot:{lot.id}",
            )

        if not any(planned.status == LOT_STATUS_PLANNED for planned in result.lots):
            # PS-09: with every lot cancelled no award can ever happen, so the
            # pool completes instead of sitting ALLOCATED forever.
            assert_transition("pool", "ALLOCATED", "COMPLETED", trigger="job:pool.allocate")
            pool.status = PoolStatus.COMPLETED
            await session.flush()
            await self.audit.append(
                session,
                actor="worker",
                action="pool.completed",
                subject_type="pool",
                subject_id=str(pool.id),
                payload={"transition_id": "PS-09", "lots": len(result.lots)},
            )

    async def _eligible_entries(
        self, session: AsyncSession, pool_id: UUID
    ) -> list[fairness.EntryCommitment]:
        rows = (
            await session.execute(
                select(PoolEntry.id, PoolEntry.zone_id, EntryReceipt.commitment)
                .join(EntryReceipt, EntryReceipt.entry_id == PoolEntry.id)
                .where(PoolEntry.pool_id == pool_id, PoolEntry.status == EntryStatus.ELIGIBLE)
                .order_by(PoolEntry.id)
            )
        ).all()
        return [
            fairness.EntryCommitment(
                entry_id=str(row.id), zone_id=str(row.zone_id), commitment=str(row.commitment)
            )
            for row in rows
        ]
