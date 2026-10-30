"""Award fixture arithmetic and hash consistency (T01B02)."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from fairpool.domain import hashing, money
from fairpool.fakes import (
    ITEM_CENTS,
    SHIPPING_CENTS_BY_ZONE,
    TAX_RATE_BPS,
    AwardFixture,
    make_award_fixture,
)


@pytest.fixture(scope="module")
def fixture() -> AwardFixture:
    return make_award_fixture()


def test_lot_and_entry_shape(fixture: AwardFixture) -> None:
    assert fixture.lot.seats == 3
    assert fixture.lot.lot_order == 0
    assert fixture.min_seats == 2
    assert len(fixture.seats) == 3
    assert [entry.status for entry in fixture.entries] == ["ELIGIBLE"] * 5
    assert [entry.allocation_status for entry in fixture.entries] == [
        "SEATED",
        "SEATED",
        "PRICED_OUT",
        "WAITLISTED",
        "WAITLISTED",
    ]


def test_totals_use_money_rounding_and_untaxed_shipping(fixture: AwardFixture) -> None:
    shipping_cents = SHIPPING_CENTS_BY_ZONE[fixture.lot.zone_id]
    expected_tax = money.tax_cents(ITEM_CENTS, TAX_RATE_BPS)
    assert expected_tax == 4113
    for entry_id, totals in fixture.award.totals.items():
        assert totals.item_cents == ITEM_CENTS
        assert totals.shipping_cents == shipping_cents
        assert totals.tax_cents == expected_tax
        assert totals.tax_cents == money.tax_cents(totals.item_cents, TAX_RATE_BPS)
        assert totals.total_cents == money.total_cents(
            totals.item_cents,
            totals.shipping_cents,
            totals.tax_cents,
        )
        assert totals.total_cents == totals.item_cents + totals.shipping_cents + totals.tax_cents
        assert fixture.award_document["totals"][str(entry_id)] == asdict(totals)


def test_one_seated_entry_is_priced_out(fixture: AwardFixture) -> None:
    priced_out = next(seat for seat in fixture.seats if seat.entry_id == fixture.priced_out)
    priced_out_total = fixture.award.totals[fixture.priced_out]
    assert priced_out.cap_cents < priced_out_total.total_cents
    for seat in fixture.seats:
        if seat.entry_id == fixture.priced_out:
            continue
        assert seat.cap_cents >= fixture.award.totals[seat.entry_id].total_cents


def test_waitlist_is_rank_ordered_and_cap_filtered(fixture: AwardFixture) -> None:
    assert [seat.rank for seat in fixture.waitlist] == [4, 5]
    over_cap, within_cap = fixture.waitlist
    over_total = fixture.award.totals[over_cap.entry_id].total_cents
    within_total = fixture.award.totals[within_cap.entry_id].total_cents
    assert over_cap.cap_cents < over_total
    assert within_cap.cap_cents >= within_total
    assert (
        sum(
            seat.cap_cents >= fixture.award.totals[seat.entry_id].total_cents
            for seat in fixture.waitlist
        )
        == 1
    )


def test_award_hash_recomputes_from_the_snapshot(fixture: AwardFixture) -> None:
    assert fixture.award.award_hash == hashing.award_hash(fixture.award_document)
    assert len(fixture.award.award_hash) == 64
    assert fixture.award_document["lot_id"] == str(fixture.lot.id)
    assert fixture.award_document["merchant_id"] == str(fixture.award.merchant_id)
    assert fixture.award_document["item_cents"] == fixture.award.item_cents
    assert fixture.award_document["moq"] == fixture.award.moq
    assert fixture.award_document["tier_index"] == fixture.award.tier_index
    assert fixture.award_document["valid_until"].endswith("Z")
    assert len(fixture.award_document["valid_until"]) == 27
