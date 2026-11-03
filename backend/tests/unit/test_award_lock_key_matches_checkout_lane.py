"""The two lanes must lock the same lot with the same key (Q-2026-11-03-27).

``tools/check_imports.py`` rule 5 keeps Member B's ``modules/auction/handlers.py`` from
importing Member A's ``modules/checkout/engine.py``, so the per-lot advisory key is
derived twice. If the two derivations ever differ, ``lot.award`` and ``lot.try_fund`` do
not contend for the same lot: the seat count rule (I8) then has no lock behind it and
breaks silently. This test is the guard against that drift; the fix is to move the helper
somewhere both lanes may read.
"""

from __future__ import annotations

from uuid import UUID

from fairpool.modules.auction.handlers import LOT_LOCK_NAMESPACE, _lot_advisory_key
from fairpool.modules.checkout.engine import LOT_LOCK_NAMESPACE as CHECKOUT_NAMESPACE
from fairpool.modules.checkout.engine import lot_advisory_lock_key

#: Fixed ids rather than random ones, so a failure names a value a reader can re-run.
SAMPLES: tuple[UUID, ...] = (
    UUID("00000000-0000-4000-8000-000000000001"),
    UUID("7f3c1d24-9b4a-4e5f-8a6b-1c2d3e4f5a6b"),
    UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
)


def test_both_lanes_name_the_lock_the_same_way() -> None:
    assert LOT_LOCK_NAMESPACE == CHECKOUT_NAMESPACE == "fairpool/lot-lock/v1"


def test_the_advisory_key_is_identical_for_the_same_lot() -> None:
    for lot_id in SAMPLES:
        assert _lot_advisory_key(lot_id) == lot_advisory_lock_key(lot_id), str(lot_id)


def test_the_key_is_a_signed_bigint_within_the_advisory_lock_range() -> None:
    """``pg_advisory_xact_lock`` takes a bigint; the derivation must never overflow it."""
    for lot_id in SAMPLES:
        key = _lot_advisory_key(lot_id)
        assert -(2**63) <= key < 2**63
        assert isinstance(key, int)


def test_distinct_lots_distinct_keys() -> None:
    assert len({_lot_advisory_key(lot_id) for lot_id in SAMPLES}) == len(SAMPLES)
