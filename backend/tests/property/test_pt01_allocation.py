"""PT-01: seeded allocation is total, rank-consistent and deterministic.

Properties (``fairness-and-hashing.md`` section 5):

* every eligible entry receives exactly one allocation, SEATED or WAITLISTED;
* ranks inside a zone are a bijection onto 1..n and ``rank_hash`` is the
  contract's hash of the published *seed* and the entry's commitment;
* a lot never holds more entries than its seats; a cancelled lot holds none;
* the same inputs always produce the same result, and the input order does not
  matter.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fairpool.domain import fairness, hashing

pytestmark = pytest.mark.property

HEX64 = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
ZONE = st.sampled_from(["US-EAST", "US-WEST", "US-CENTRAL"])


@dataclass(frozen=True)
class Case:
    entries: tuple[fairness.EntryCommitment, ...]
    plan: tuple[fairness.ZoneLotPlan, ...]
    seed_hex: str


@st.composite
def cases(draw: st.DrawFn) -> Case:
    zones = draw(st.lists(ZONE, min_size=1, max_size=3, unique=True))
    count = draw(st.integers(min_value=0, max_value=10))
    entries = tuple(
        fairness.EntryCommitment(
            entry_id=f"00000000-0000-4000-8000-{index:012d}",
            zone_id=draw(ZONE),
            commitment=draw(HEX64),
        )
        for index in range(count)
    )
    plan = []
    for zone_id in zones:
        lots = [
            fairness.LotSpec(
                seats=draw(st.integers(min_value=1, max_value=4)),
                min_seats=draw(st.integers(min_value=0, max_value=4)),
            )
            for _ in range(draw(st.integers(min_value=1, max_value=3)))
        ]
        plan.append(fairness.ZoneLotPlan(zone_id=zone_id, lots=lots))
    return Case(entries=entries, plan=tuple(plan), seed_hex=draw(HEX64))


@settings(max_examples=80, deadline=None)
@given(cases())
def test_every_entry_has_exactly_one_allocation(case: Case) -> None:
    """PT-01: the allocation list is a partition of the eligible entries."""
    result = fairness.assign_lots(case.entries, case.plan, case.seed_hex)
    allocated = [allocation.entry_id for allocation in result.allocations]
    assert sorted(allocated) == sorted(entry.entry_id for entry in case.entries)
    assert len(allocated) == len(set(allocated))


@settings(max_examples=80, deadline=None)
@given(cases())
def test_ranks_are_a_bijection_per_zone_and_the_contract_hash(case: Case) -> None:
    """PT-01: per zone ranks are 1..n and ``rank_hash`` uses the published seed."""
    result = fairness.assign_lots(case.entries, case.plan, case.seed_hex)
    commitments = {entry.entry_id: entry.commitment for entry in case.entries}
    zones = {entry.entry_id: entry.zone_id for entry in case.entries}
    by_zone: dict[str, list[int]] = {}
    for allocation in result.allocations:
        assert allocation.rank_hash == hashing.rank_hash(
            case.seed_hex, commitments[allocation.entry_id]
        )
        assert allocation.zone_id == zones[allocation.entry_id]
        by_zone.setdefault(allocation.zone_id, []).append(allocation.rank)
    for ranks in by_zone.values():
        assert sorted(ranks) == list(range(1, len(ranks) + 1))


@settings(max_examples=80, deadline=None)
@given(cases())
def test_a_lot_never_exceeds_its_seats_and_cancelled_lots_hold_none(case: Case) -> None:
    """PT-01: seats are an upper bound; LS-12 lots seat nobody."""
    result = fairness.assign_lots(case.entries, case.plan, case.seed_hex)
    seated_by_lot: dict[int, int] = {}
    for allocation in result.allocations:
        if allocation.lot_order is not None:
            seated_by_lot[allocation.lot_order] = seated_by_lot.get(allocation.lot_order, 0) + 1
    for lot in result.lots:
        assert seated_by_lot.get(lot.lot_order, 0) <= lot.seats
        if lot.status == fairness.LOT_CANCELLED:
            assert lot.entry_ids == ()
            assert seated_by_lot.get(lot.lot_order, 0) == 0
        else:
            assert len(lot.entry_ids) >= lot.min_seats
            assert seated_by_lot.get(lot.lot_order, 0) == len(lot.entry_ids)
    waitlisted = {allocation.entry_id for allocation in result.waitlist}
    seated = {
        allocation.entry_id for allocation in result.allocations if allocation.lot_order is not None
    }
    assert waitlisted == {entry.entry_id for entry in case.entries} - seated


@settings(max_examples=50, deadline=None)
@given(cases())
def test_allocation_is_deterministic_and_order_independent(case: Case) -> None:
    """PT-01: the same commitments order the same way whatever their input order."""
    result = fairness.assign_lots(case.entries, case.plan, case.seed_hex)
    again = fairness.assign_lots(case.entries, case.plan, case.seed_hex)
    assert again == result
    shuffled = tuple(reversed(case.entries))
    assert fairness.assign_lots(shuffled, case.plan, case.seed_hex) == result
