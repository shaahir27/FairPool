"""Fixture-backed allocation read service fake."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fairpool.domain import fairness
from fairpool.ports import AsyncSession, AwardView, LotView, SeatView

from .fixtures import PRICED_OUT, SEATED, WAITLISTED, AwardFixture, make_award_fixture


@dataclass
class _AllocationState:
    seat: SeatView
    status: str
    lot_id: UUID | None


@dataclass(frozen=True)
class AllocationCall:
    method: str
    lot_id: UUID
    count: int | None = None


class FakeAllocationRead:
    """Serves an ``AwardFixture`` and applies the N12 waitlist rule in memory."""

    def __init__(self, fixture: AwardFixture | None = None) -> None:
        self.fixture = make_award_fixture() if fixture is None else fixture
        self._entries = {entry.entry_id: entry for entry in self.fixture.entries}
        self._allocations: dict[UUID, _AllocationState] = {}
        for seat in self.fixture.seats:
            status = PRICED_OUT if seat.entry_id == self.fixture.priced_out else SEATED
            self._allocations[seat.entry_id] = _AllocationState(
                seat=seat,
                status=status,
                lot_id=self.fixture.lot.id,
            )
        for seat in self.fixture.waitlist:
            self._allocations[seat.entry_id] = _AllocationState(
                seat=seat,
                status=WAITLISTED,
                lot_id=None,
            )
        self.calls: list[AllocationCall] = []

    def _record(self, method: str, lot_id: UUID, count: int | None = None) -> None:
        self.calls.append(AllocationCall(method=method, lot_id=lot_id, count=count))

    def _require_lot(self, lot_id: UUID) -> None:
        if lot_id != self.fixture.lot.id:
            raise KeyError(f"unknown lot: {lot_id}")

    async def get_lot(self, session: AsyncSession, lot_id: UUID) -> LotView:
        self._record("get_lot", lot_id)
        self._require_lot(lot_id)
        return self.fixture.lot

    async def get_award(self, session: AsyncSession, lot_id: UUID) -> AwardView:
        self._record("get_award", lot_id)
        self._require_lot(lot_id)
        return self.fixture.award

    async def list_seated(self, session: AsyncSession, lot_id: UUID) -> list[SeatView]:
        self._record("list_seated", lot_id)
        self._require_lot(lot_id)
        seated = [
            state
            for state in self._allocations.values()
            if state.status == SEATED and state.lot_id == lot_id
        ]
        return [state.seat for state in sorted(seated, key=lambda state: state.seat.rank)]

    async def next_candidates(
        self,
        session: AsyncSession,
        lot_id: UUID,
        count: int,
    ) -> list[SeatView]:
        self._record("next_candidates", lot_id, count)
        self._require_lot(lot_id)
        if count <= 0:
            return []

        totals_cents = {
            str(entry_id): totals.total_cents
            for entry_id, totals in self.fixture.award.totals.items()
        }
        selected: list[SeatView] = []
        for _ in range(count):
            candidates = [
                fairness.WaitlistCandidate(
                    entry_id=str(entry_id),
                    zone_id=state.seat.zone_id,
                    rank=state.seat.rank,
                    cap_cents=state.seat.cap_cents,
                    entry_status=self._entries[entry_id].status,
                )
                for entry_id, state in self._allocations.items()
                if state.status == WAITLISTED
            ]
            chosen = fairness.waitlist_candidate(
                candidates,
                totals_cents,
                zone_id=self.fixture.lot.zone_id,
            )
            if chosen is None:
                break
            entry_id = UUID(chosen.entry_id)
            state = self._allocations[entry_id]
            state.status = SEATED
            state.lot_id = lot_id
            selected.append(state.seat)
        return selected

    def status_of(self, entry_id: UUID) -> str:
        return self._allocations[entry_id].status

    def lot_id_of(self, entry_id: UUID) -> UUID | None:
        return self._allocations[entry_id].lot_id
