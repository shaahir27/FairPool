"""Seeded ranking, lot assignment and waitlist selection.

Contract: ``docs/contracts/fairness-and-hashing.md`` sections 3 to 5. Ranking is
per delivery zone (``rank_hash`` then ``entry_id`` ascending); lots are formed in
lot-plan order and undersized lots are created CANCELLED, leaving their entries
WAITLISTED (LS-12, N2). ``lot_order`` follows zone order then lot index (N7).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import hashing
from .errors import AllocationError

LOT_PLANNED = "PLANNED"
LOT_CANCELLED = "CANCELLED"
ENTRY_SEATED = "SEATED"
ENTRY_WAITLISTED = "WAITLISTED"
ENTRY_ELIGIBLE = "ELIGIBLE"


@dataclass(frozen=True)
class EntryCommitment:
    """One eligible entry as published at pool close."""

    entry_id: str
    zone_id: str
    commitment: str


@dataclass(frozen=True)
class RankedEntry:
    entry_id: str
    zone_id: str
    commitment: str
    rank_hash: str
    rank: int


@dataclass(frozen=True)
class LotSpec:
    seats: int
    min_seats: int


@dataclass(frozen=True)
class ZoneLotPlan:
    zone_id: str
    lots: Sequence[LotSpec]


@dataclass(frozen=True)
class PlannedLot:
    zone_id: str
    lot_index: int
    lot_order: int
    seats: int
    min_seats: int
    status: str
    entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class Allocation:
    entry_id: str
    zone_id: str
    rank: int
    rank_hash: str
    lot_order: int | None
    status: str


@dataclass(frozen=True)
class AllocationResult:
    lots: tuple[PlannedLot, ...]
    allocations: tuple[Allocation, ...]
    waitlist: tuple[Allocation, ...]


@dataclass(frozen=True)
class WaitlistCandidate:
    """A WAITLISTED allocation considered for a vacancy (N12)."""

    entry_id: str
    zone_id: str
    rank: int
    cap_cents: int
    entry_status: str = ENTRY_ELIGIBLE


def _require_rank(rank: int, field: str) -> None:
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise AllocationError(f"{field} must be a positive integer")


def _require_non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AllocationError(f"{field} must be a non-negative integer")


def rank_order(entries: Sequence[EntryCommitment], seed_hex: str) -> list[RankedEntry]:
    """Rank entries inside each zone by ``(rank_hash, entry_id)`` ascending."""
    seen: set[str] = set()
    by_zone: dict[str, list[EntryCommitment]] = {}
    for entry in entries:
        if entry.entry_id in seen:
            raise AllocationError(f"duplicate entry_id: {entry.entry_id}")
        seen.add(entry.entry_id)
        by_zone.setdefault(entry.zone_id, []).append(entry)

    ranked: list[RankedEntry] = []
    for zone_id in sorted(by_zone):
        scored = [
            (hashing.rank_hash(seed_hex, entry.commitment), entry) for entry in by_zone[zone_id]
        ]
        scored.sort(key=lambda pair: (pair[0], pair[1].entry_id))
        for position, (rank_hash, entry) in enumerate(scored, start=1):
            ranked.append(
                RankedEntry(
                    entry_id=entry.entry_id,
                    zone_id=entry.zone_id,
                    commitment=entry.commitment,
                    rank_hash=rank_hash,
                    rank=position,
                )
            )
    return ranked


def assign_lots(
    entries: Sequence[EntryCommitment],
    plan: Sequence[ZoneLotPlan],
    seed_hex: str,
) -> AllocationResult:
    """Walk each zone's ranking through its lot plan and waitlist the remainder."""
    ranked = rank_order(entries, seed_hex)
    ranked_by_zone: dict[str, list[RankedEntry]] = {}
    for entry in ranked:
        ranked_by_zone.setdefault(entry.zone_id, []).append(entry)

    seen_zones: set[str] = set()
    lots: list[PlannedLot] = []
    seated: dict[str, int] = {}
    next_lot_order = 1
    for zone_plan in plan:
        if zone_plan.zone_id in seen_zones:
            raise AllocationError(f"duplicate zone in lot plan: {zone_plan.zone_id}")
        seen_zones.add(zone_plan.zone_id)
        zone_ranked = ranked_by_zone.get(zone_plan.zone_id, [])
        cursor = 0
        for lot_index, spec in enumerate(zone_plan.lots):
            if isinstance(spec.seats, bool) or not isinstance(spec.seats, int) or spec.seats < 1:
                raise AllocationError("lot seats must be a positive integer")
            _require_non_negative(spec.min_seats, "lot min_seats")
            take = min(spec.seats, len(zone_ranked) - cursor)
            if take < spec.min_seats:
                # LS-12: entries stay WAITLISTED so later lots in the zone can use them.
                lots.append(
                    PlannedLot(
                        zone_id=zone_plan.zone_id,
                        lot_index=lot_index,
                        lot_order=next_lot_order,
                        seats=spec.seats,
                        min_seats=spec.min_seats,
                        status=LOT_CANCELLED,
                        entry_ids=(),
                    )
                )
            else:
                assigned = zone_ranked[cursor : cursor + take]
                cursor += take
                for entry in assigned:
                    seated[entry.entry_id] = next_lot_order
                lots.append(
                    PlannedLot(
                        zone_id=zone_plan.zone_id,
                        lot_index=lot_index,
                        lot_order=next_lot_order,
                        seats=spec.seats,
                        min_seats=spec.min_seats,
                        status=LOT_PLANNED,
                        entry_ids=tuple(entry.entry_id for entry in assigned),
                    )
                )
            next_lot_order += 1

    # Planned zones in plan order, then zones without a lot plan (deterministic order).
    zone_order = [zone_plan.zone_id for zone_plan in plan if zone_plan.zone_id in ranked_by_zone]
    zone_order.extend(sorted(set(ranked_by_zone) - set(zone_order)))
    allocations: list[Allocation] = []
    for zone_id in zone_order:
        for entry in ranked_by_zone[zone_id]:
            lot_order = seated.get(entry.entry_id)
            allocations.append(
                Allocation(
                    entry_id=entry.entry_id,
                    zone_id=entry.zone_id,
                    rank=entry.rank,
                    rank_hash=entry.rank_hash,
                    lot_order=lot_order,
                    status=ENTRY_WAITLISTED if lot_order is None else ENTRY_SEATED,
                )
            )
    waitlist = tuple(item for item in allocations if item.status == ENTRY_WAITLISTED)
    return AllocationResult(lots=tuple(lots), allocations=tuple(allocations), waitlist=waitlist)


def waitlist_candidate(
    candidates: Iterable[WaitlistCandidate],
    totals_cents: Mapping[str, int],
    *,
    zone_id: str,
) -> WaitlistCandidate | None:
    """First WAITLISTED entry in the zone by rank that can afford the lot total.

    Entries whose cap is below the lot's total, or whose entry is no longer
    ELIGIBLE, are skipped and stay on the waitlist (contract section 5, N12).
    """
    ordered = sorted(candidates, key=lambda item: (item.rank, item.entry_id))
    for candidate in ordered:
        if candidate.zone_id != zone_id:
            continue
        if candidate.entry_status != ENTRY_ELIGIBLE:
            continue
        _require_rank(candidate.rank, "waitlist rank")
        _require_non_negative(candidate.cap_cents, "waitlist cap_cents")
        total = totals_cents.get(candidate.entry_id)
        if total is None:
            continue
        _require_non_negative(total, "lot total_cents")
        if candidate.cap_cents >= total:
            return candidate
    return None
