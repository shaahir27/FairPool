"""PT-02: lot formation follows the frozen plan (lot_order, lot_index, LS-12).

Properties (``fairness-and-hashing.md`` section 5, N7, N2):

* one lot per planned lot, ``lot_order`` contiguous from 1 in plan order;
* ``lot_index`` is the lot's position inside its zone;
* an undersized lot is CANCELLED and seats nobody, so later lots in the zone can
  use the entries (they stay WAITLISTED);
* a PLANNED lot takes exactly the next ``take`` ranks of its zone, in rank order.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fairpool.domain import fairness

pytestmark = pytest.mark.property

HEX64 = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
ZONE = st.sampled_from(["US-EAST", "US-WEST"])


@st.composite
def plans(draw: st.DrawFn) -> tuple[tuple[fairness.EntryCommitment, ...], list]:
    zones = draw(st.lists(ZONE, min_size=1, max_size=2, unique=True))
    count = draw(st.integers(min_value=0, max_value=12))
    entries = tuple(
        fairness.EntryCommitment(
            entry_id=f"00000000-0000-4000-8000-{index:012d}",
            zone_id=draw(ZONE),
            commitment=draw(HEX64),
        )
        for index in range(count)
    )
    plan = [
        fairness.ZoneLotPlan(
            zone_id=zone_id,
            lots=[
                fairness.LotSpec(
                    seats=draw(st.integers(min_value=1, max_value=5)),
                    min_seats=draw(st.integers(min_value=0, max_value=5)),
                )
                for _ in range(draw(st.integers(min_value=1, max_value=4)))
            ],
        )
        for zone_id in zones
    ]
    return entries, plan


@settings(max_examples=80, deadline=None)
@given(plans(), HEX64)
def test_lot_order_is_contiguous_in_plan_order(case: tuple, seed_hex: str) -> None:
    """PT-02 (N7): ``lot_order`` walks zone order then ``lot_index``."""
    entries, plan = case
    result = fairness.assign_lots(entries, plan, seed_hex)
    expected = [index for index in range(1, len(result.lots) + 1)]
    assert [lot.lot_order for lot in result.lots] == expected
    assert sum(len(zone.lots) for zone in plan) == len(result.lots)
    cursor = 0
    for zone in plan:
        for lot_index, spec in enumerate(zone.lots):
            lot = result.lots[cursor]
            cursor += 1
            assert lot.zone_id == zone.zone_id
            assert lot.lot_index == lot_index
            assert lot.seats == spec.seats
            assert lot.min_seats == spec.min_seats


@settings(max_examples=80, deadline=None)
@given(plans(), HEX64)
def test_a_planned_lot_takes_the_next_ranks_of_its_zone(case: tuple, seed_hex: str) -> None:
    """PT-02: each PLANNED lot seats the next blocked ranks of its zone."""
    entries, plan = case
    result = fairness.assign_lots(entries, plan, seed_hex)
    ranked: dict[str, list[str]] = {}
    for allocation in fairness.rank_order(entries, seed_hex):
        ranked.setdefault(allocation.zone_id, []).append(allocation.entry_id)
    cursor = {zone.zone_id: 0 for zone in plan}
    for lot in result.lots:
        start = cursor[lot.zone_id]
        if lot.status == fairness.LOT_CANCELLED:
            # LS-12: the entries stay put for a later lot in the same zone.
            continue
        zone_ranked = ranked.get(lot.zone_id, [])
        assert lot.entry_ids == tuple(zone_ranked[start : start + len(lot.entry_ids)])
        cursor[lot.zone_id] = start + len(lot.entry_ids)


@settings(max_examples=80, deadline=None)
@given(plans(), HEX64)
def test_an_undersized_lot_is_cancelled_and_never_seats(case: tuple, seed_hex: str) -> None:
    """PT-02 (LS-12, N2): fewer entries than min_seats cancels, never partially seats."""
    entries, plan = case
    result = fairness.assign_lots(entries, plan, seed_hex)
    by_zone: dict[str, int] = {}
    for entry in entries:
        by_zone[entry.zone_id] = by_zone.get(entry.zone_id, 0) + 1
    for lot in result.lots:
        if lot.status == fairness.LOT_CANCELLED:
            assert lot.entry_ids == ()
        else:
            assert len(lot.entry_ids) >= lot.min_seats
            assert len(lot.entry_ids) <= lot.seats
    seated = sum(len(lot.entry_ids) for lot in result.lots)
    assert seated <= sum(by_zone.values())
