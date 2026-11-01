"""The real ``AllocationReadService`` (T04A05; ``domain-ports.md`` section 4.1).

This is the only place checkout code reads allocation, lot and award data, and it
is the only place the N12 waitlist rule is applied: ``next_candidates`` selects
WAITLISTED allocations in the lot's zone, ascending rank, whose cap covers that
lot's awarded total and whose entry is still ELIGIBLE, and flips them SEATED with
the lot id. The rule itself comes from ``domain/fairness.waitlist_candidate``
(``fairness-and-hashing.md`` section 5), never from a second implementation here.

Every method takes the caller's session and never commits or commits-adjacent
flushes beyond a statement flush, so ``lot.open_checkout`` and ``lot.refill`` can
hold the lot lock across the read and the write (``domain-ports.md`` section 1,
I8).

CR-4: ``pools.timeline`` now carries ``pending_wait_s`` and ``capture_grace_s``
and ``lots`` carries ``refill_waves``. The shipped ``ports.LotView`` dataclass in
this tree does not declare them yet even though the contract does, so
:class:`LotViewDetail` extends it with those three fields; ``get_lot`` returns the
subclass and a caller typed against the port still sees a ``LotView``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Award
from fairpool.db.models.catalog import PoolEntry
from fairpool.db.models.enums import AllocationStatus
from fairpool.db.models.pools import Allocation
from fairpool.domain import fairness
from fairpool.domain.errors import ApplicationError
from fairpool.ports import AwardView, LotView, SeatView, Totals


@dataclass(frozen=True)
class LotViewDetail(LotView):
    """``LotView`` plus the CR-4 timing values the checkout handlers need.

    ``refill_waves`` is a ``lots`` column (migration 0004); ``pending_wait_s`` and
    ``capture_grace_s`` live in ``pools.timeline``. They are here rather than
    re-read from the rows at each call site so every handler sees one snapshot.
    """

    pending_wait_s: int = 120
    capture_grace_s: int = 120
    refill_waves: int = 0


def _seconds(timeline: dict[str, object], key: str, default: int) -> int:
    value = timeline.get(key, default)
    return int(value) if isinstance(value, int) else default


def _region(canonical_request: dict[str, object]) -> str:
    delivery = canonical_request.get("delivery")
    if isinstance(delivery, dict):
        region = delivery.get("region")
        if isinstance(region, str):
            return region
    raise ApplicationError("INTEGRITY_ERROR")


def _seat(row: Any) -> SeatView:
    """One seat view from a row that joins an allocation to its own entry."""
    return SeatView(
        entry_id=row.entry_id,
        user_id=row.user_id,
        cap_cents=int(row.cap_cents),
        zone_id=str(row.zone_id),
        region=_region(row.canonical_request),
        rank=int(row.rank),
        paypal_account_key=(
            None if row.paypal_account_key is None else str(row.paypal_account_key)
        ),
    )


class PostgresAllocationRead:
    """The real ``AllocationReadService``; see the module docstring.

    ``calls`` records the method names this instance served. It exists so a test can
    assert that the real service -- not ``FakeAllocationRead`` -- is the one wired
    into checkout (IT-4, T04X01).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_lot(self, session: AsyncSession, lot_id: UUID) -> LotView:
        self.calls.append("get_lot")
        row = (
            await session.execute(
                text(
                    "SELECT l.id, l.pool_id, l.zone_id, l.lot_order, l.seats, l.status, "
                    "l.payment_router, l.payment_mode, l.fund_deadline_at, l.refill_cutoff_at, "
                    "l.refill_waves, p.mode AS pool_mode, p.timeline "
                    "FROM lots l JOIN pools p ON p.id = l.pool_id WHERE l.id = :lot"
                ),
                {"lot": lot_id},
            )
        ).first()
        if row is None:
            raise ApplicationError("NOT_FOUND")
        timeline = row.timeline if isinstance(row.timeline, dict) else {}
        return LotViewDetail(
            id=row.id,
            pool_id=row.pool_id,
            zone_id=row.zone_id,
            lot_order=int(row.lot_order),
            seats=int(row.seats),
            status=str(row.status),
            payment_router=None if row.payment_router is None else str(row.payment_router),
            payment_mode=None if row.payment_mode is None else str(row.payment_mode),
            fund_deadline_at=row.fund_deadline_at,
            refill_cutoff_at=row.refill_cutoff_at,
            offer_window_s=_seconds(timeline, "offer_window_s", 180),
            fund_deadline_s=_seconds(timeline, "fund_deadline_s", 600),
            max_refill_waves=_seconds(timeline, "max_refill_waves", 1),
            pool_mode=str(row.pool_mode),
            pending_wait_s=_seconds(timeline, "pending_wait_s", 120),
            capture_grace_s=_seconds(timeline, "capture_grace_s", 120),
            refill_waves=int(row.refill_waves or 0),
        )

    async def get_award(self, session: AsyncSession, lot_id: UUID) -> AwardView:
        self.calls.append("get_award")
        award = await session.scalar(select(Award).where(Award.lot_id == lot_id))
        if award is None:
            raise ApplicationError("NOT_FOUND")
        totals: dict[UUID, Totals] = {}
        for entry_id, values in dict(award.totals).items():
            if not isinstance(values, dict):
                raise ApplicationError("INTEGRITY_ERROR")
            totals[UUID(str(entry_id))] = Totals(
                item_cents=int(values["item_cents"]),
                shipping_cents=int(values["shipping_cents"]),
                tax_cents=int(values["tax_cents"]),
                total_cents=int(values["total_cents"]),
            )
        return AwardView(
            lot_id=award.lot_id,
            merchant_id=award.merchant_id,
            item_cents=int(award.item_cents),
            moq=int(award.moq),
            tier_index=int(award.tier_index),
            totals=totals,
            valid_until=award.valid_until,
            award_hash=str(award.award_hash),
        )

    async def list_seated(self, session: AsyncSession, lot_id: UUID) -> list[SeatView]:
        self.calls.append("list_seated")
        rows = (
            await session.execute(
                select(
                    Allocation.entry_id,
                    PoolEntry.user_id,
                    PoolEntry.cap_cents,
                    Allocation.zone_id,
                    PoolEntry.canonical_request,
                    Allocation.rank,
                    PoolEntry.paypal_account_key,
                )
                .join(PoolEntry, PoolEntry.id == Allocation.entry_id)
                .where(
                    Allocation.lot_id == lot_id,
                    Allocation.status == AllocationStatus.SEATED,
                )
                .order_by(Allocation.rank, Allocation.entry_id)
            )
        ).all()
        return [_seat(row) for row in rows]

    async def next_candidates(
        self, session: AsyncSession, lot_id: UUID, count: int
    ) -> list[SeatView]:
        """Flip up to ``count`` affordable waitlisted allocations to SEATED (N12)."""
        self.calls.append("next_candidates")
        if count <= 0:
            return []
        lot = await self.get_lot(session, lot_id)
        try:
            award = await self.get_award(session, lot_id)
        except ApplicationError:
            # No award means no total any candidate could be compared against; the
            # contract's rule is "cap >= that lot's total", so no seat is offered.
            return []
        totals_cents = {
            str(entry_id): totals.total_cents for entry_id, totals in award.totals.items()
        }
        rows = (
            await session.execute(
                select(
                    Allocation.id,
                    Allocation.entry_id,
                    Allocation.zone_id,
                    Allocation.rank,
                    PoolEntry.cap_cents,
                    PoolEntry.status,
                    PoolEntry.user_id,
                    PoolEntry.canonical_request,
                    PoolEntry.paypal_account_key,
                )
                .join(PoolEntry, PoolEntry.id == Allocation.entry_id)
                .where(
                    Allocation.pool_id == lot.pool_id,
                    Allocation.zone_id == lot.zone_id,
                    Allocation.status == AllocationStatus.WAITLISTED,
                )
                .order_by(Allocation.rank, Allocation.entry_id)
                .with_for_update(of=Allocation)
            )
        ).all()

        remaining = [
            (
                row.id,
                fairness.WaitlistCandidate(
                    entry_id=str(row.entry_id),
                    zone_id=str(row.zone_id),
                    rank=int(row.rank),
                    cap_cents=int(row.cap_cents),
                    entry_status=str(row.status),
                ),
                row,
            )
            for row in rows
        ]
        selected: list[SeatView] = []
        while len(selected) < count:
            chosen = fairness.waitlist_candidate(
                [candidate for _, candidate, _ in remaining],
                totals_cents,
                zone_id=lot.zone_id,
            )
            if chosen is None:
                break
            index = next(i for i, (_, candidate, _) in enumerate(remaining) if candidate is chosen)
            allocation_id, _, row = remaining.pop(index)
            updated = await session.scalar(
                text(
                    "UPDATE allocations SET status = 'SEATED'::allocation_status, lot_id = :lot "
                    "WHERE id = :id AND status = 'WAITLISTED'::allocation_status RETURNING id"
                ),
                {"lot": lot_id, "id": allocation_id},
            )
            if updated is None:
                # Another transaction seated it first; this candidate is gone.
                continue
            selected.append(_seat(row))
        await session.flush()
        return selected


__all__ = ["LotViewDetail", "PostgresAllocationRead"]
