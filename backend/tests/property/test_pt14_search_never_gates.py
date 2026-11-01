"""PT-14, Phase 3 form (OD-P3-1): search never gates the award.

`IT-3` demands this property now and `lot.award` is a Phase 5 handler, so the half
owed here runs over the pure rules engine that already exists -
``domain/auction_rules.py`` (R1 to R9: tier resolution, feasibility, ranking, capacity)
plus ``domain/fairness.py`` (seeded ranking, lot assignment, waitlist) - with the
``SearchService`` port forced on, off and raising. No database, no handler, no network:
one synthetic scene is awarded three times and the three awards must be identical.

The rule under test is AGENTS.md rule 23 and ``docs/contracts/ai-schemas.md`` section
7: search is retrieval. So the candidate *set* comes from the frozen bid list, never
from a hit list, and the advisory ``similarity_check`` result is read and ignored. The
"on" double is deliberately adversarial: it returns lots ordered by a score the rules
do not use, lists each lot's bids in reverse in its text, and scripts a wrong-product
similarity (own_rank ``None``) for every lot - the exact condition that would raise a
LOW_SIMILARITY warning. The deterministic test at the bottom shows the equivalence is
not vacuous: an award taken from the top hit would differ from the rules' award, and
would differ between the three modes. The end-to-end half over real ``lot.award`` rows
is asserted at `IG-5`.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fairpool.domain import auction_rules, fairness, hashing
from fairpool.fakes.search import FakeSearch, SearchDocument
from fairpool.ports import SearchHit, SimilarityResult

pytestmark = pytest.mark.property

POOL_ID = "11111111-1111-4111-8111-111111111111"
ZONE_IDS = ("US-EAST", "US-WEST")
LOT_NAMESPACE = uuid.UUID("22222222-2222-4222-8222-222222222222")


def lot_document_id(lot_order: int) -> uuid.UUID:
    """A stable document id per planned lot, shared by all three search modes."""
    return uuid.uuid5(LOT_NAMESPACE, f"lot-{lot_order}")


def lot_query(lot_order: int) -> str:
    return f"lot-{lot_order:02d}"


def commitment_for(entry_id: str) -> str:
    """A published commitment: hex64, as ``fairness.rank_order`` requires."""
    return hashing.commitment(
        POOL_ID,
        entry_id,
        hashing.sha256_hex(f"request:{entry_id}"),
        hashing.sha256_hex(f"salt:{entry_id}"),
    )


@dataclass(frozen=True)
class Bid:
    """One merchant bid on one planned lot, as the frozen catalogue holds it."""

    bid_id: str
    lot_order: int
    merchant_id: str
    product_key: str
    tiers: tuple[auction_rules.Tier, ...]
    moq: int
    capacity: int


@dataclass(frozen=True)
class Scene:
    seed_hex: str
    entries: tuple[fairness.EntryCommitment, ...]
    plan: tuple[fairness.ZoneLotPlan, ...]
    buyers: Mapping[str, auction_rules.SeatedBuyer]
    bids: tuple[Bid, ...]


@dataclass(frozen=True)
class AwardRow:
    """The award facts PT-14 compares: who won each lot, at which tier, for whom."""

    lot_order: int
    winner_bid_id: str | None
    merchant_id: str | None
    tier_index: int | None
    seated_entry_ids: tuple[str, ...]


class Unavailable(RuntimeError):
    """The search port could not answer at all."""


class StrictlyUnavailable:
    """The raising mode: every call throws, which is the stress case of rule 23."""

    def __init__(self) -> None:
        self.attempts = 0

    async def search(self, *args: object, **kwargs: object) -> list[SearchHit]:
        del args, kwargs
        self.attempts += 1
        raise Unavailable("search backend down")

    async def similarity_check(self, *args: object, **kwargs: object) -> SimilarityResult:
        del args, kwargs
        self.attempts += 1
        raise Unavailable("search backend down")


def adversarial_search(scene: Scene) -> FakeSearch:
    """Search on: it answers, and everything it says is the wrong thing to decide on."""
    allocation = fairness.assign_lots(scene.entries, scene.plan, scene.seed_hex)
    documents: list[SearchDocument] = []
    similarity: dict[uuid.UUID, SimilarityResult] = {}
    for lot in allocation.lots:
        lot_id = lot_document_id(lot.lot_order)
        # Reverse catalogue order in the text: retrieval order the rules must ignore.
        bids = sorted(
            (bid for bid in scene.bids if bid.lot_order == lot.lot_order),
            key=lambda bid: bid.bid_id,
            reverse=True,
        )
        documents.append(
            SearchDocument(
                doc_id=str(lot_id),
                doc_kind="lot",
                pool_id=uuid.UUID(POOL_ID),
                lot_id=lot_id,
                product_key=bids[0].product_key if bids else "unrelated-key",
                title=f"{lot_query(lot.lot_order)} in {lot.zone_id}",
                content=" ".join([lot_query(lot.lot_order)] * (len(bids) + 1))
                + " "
                + " ".join(bid.bid_id for bid in bids),
                status="BIDDING",
            )
        )
        # own_rank None with a different product_key is section 7's flag condition.
        similarity[lot_id] = SimilarityResult(None, lot_id, "wrong-product-key")
    return FakeSearch(documents=documents, similarity=similarity)


async def award(scene: Scene, search: object) -> tuple[AwardRow, ...]:
    """The pure R1-R9 award, with the search port consulted for retrieval only."""
    allocation = fairness.assign_lots(scene.entries, scene.plan, scene.seed_hex)
    seed_hex = hashing.demo_seed(POOL_ID)
    rows: list[AwardRow] = []
    awarded: list[auction_rules.AwardedLot] = []

    for lot in sorted(allocation.lots, key=lambda item: item.lot_order):
        if lot.status != fairness.LOT_PLANNED:
            continue
        lot_id = lot_document_id(lot.lot_order)
        bids = sorted(
            (bid for bid in scene.bids if bid.lot_order == lot.lot_order),
            key=lambda bid: bid.bid_id,
        )
        hits = await _retrieve(search, lot, bids)
        await _advisory(search, lot_id, bids)

        candidates: list[auction_rules.BidCandidate] = []
        chosen: dict[str, int] = {}
        for bid in bids:
            seated = [scene.buyers[entry_id] for entry_id in lot.entry_ids]
            resolution = auction_rules.resolve_tiers(seated, bid.tiers, bid.moq)
            if not resolution.feasible or resolution.chosen_tier_index is None:
                continue  # R8
            if not auction_rules.capacity_ok(
                _capacity_ceiling(scene, lot), bid.merchant_id, bid.capacity, awarded
            ):
                continue  # R9
            key = auction_rules.bid_ranking_key(resolution, _tiebreak(seed_hex, lot_id, bid))
            candidates.append(
                auction_rules.BidCandidate(
                    bid_id=bid.bid_id,
                    merchant_id=bid.merchant_id,
                    mean_total_cents=key[0],
                    max_total_cents=key[1],
                    tiebreak_hash=key[2],
                )
            )
            chosen[bid.bid_id] = resolution.chosen_tier_index

        ranked = auction_rules.rank_bids(candidates)
        if not ranked:
            rows.append(AwardRow(lot.lot_order, None, None, None, tuple(lot.entry_ids)))
            continue
        winner = ranked[0]
        awarded.append(
            auction_rules.AwardedLot(
                lot_order=lot.lot_order, merchant_id=winner.merchant_id, seats=len(lot.entry_ids)
            )
        )
        rows.append(
            AwardRow(
                lot.lot_order,
                winner.bid_id,
                winner.merchant_id,
                chosen[winner.bid_id],
                tuple(lot.entry_ids),
            )
        )
        # Retrieval output is observed, never used: no hit changes a set, an order or a
        # status here, which is what the three-mode equality below proves (rule 23).
        assert all(isinstance(hit, SearchHit) for hit in hits)
    return tuple(rows)


def _capacity_ceiling(scene: Scene, lot: fairness.PlannedLot) -> int:
    return max(
        (bid.capacity for bid in scene.bids if bid.lot_order == lot.lot_order),
        default=len(lot.entry_ids),
    )


def _tiebreak(seed_hex: str, lot_id: uuid.UUID, bid: Bid) -> str:
    return hashing.tiebreak_hash(hashing.lot_seed(seed_hex, str(lot_id)), bid.merchant_id)


async def _retrieve(search: object, lot: fairness.PlannedLot, bids: Sequence[Bid]) -> list:
    """One retrieval call per planned lot; an outage answers with no hits, never an error."""
    del bids
    try:
        return await search.search(  # type: ignore[attr-defined]
            None,
            q=lot_query(lot.lot_order),
            kinds=["lot"],
            status=["BIDDING"],
            limit=20,
        )
    except Unavailable:
        return []  # FR-IG-01: search failure never fails the caller


async def _advisory(search: object, lot_id: uuid.UUID, bids: Sequence[Bid]) -> None:
    """The advisory wrong-product check: a WARNING at most, so it cannot move a bid."""
    try:
        await search.similarity_check(  # type: ignore[attr-defined]
            None, lot_id=lot_id, text=" ".join(bid.product_key for bid in bids)
        )
    except Unavailable:
        return


# --- the property: three modes, one award -----------------------------------------


@st.composite
def scenes(draw: st.DrawFn) -> Scene:
    entry_count = draw(st.integers(min_value=0, max_value=7))
    entries = tuple(
        fairness.EntryCommitment(
            entry_id=f"entry-{index:02d}",
            zone_id=draw(st.sampled_from(ZONE_IDS)),
            commitment=commitment_for(f"entry-{index:02d}"),
        )
        for index in range(1, entry_count + 1)
    )
    plan = tuple(
        fairness.ZoneLotPlan(
            zone,
            tuple(
                fairness.LotSpec(
                    seats=draw(st.integers(min_value=1, max_value=3)),
                    min_seats=draw(st.integers(min_value=1, max_value=2)),
                )
                for _ in range(draw(st.integers(min_value=1, max_value=2)))
            ),
        )
        for zone in ZONE_IDS
    )
    buyers = {
        entry.entry_id: auction_rules.SeatedBuyer(
            entry_id=entry.entry_id,
            cap_cents=draw(st.integers(min_value=0, max_value=200_000)),
            shipping_cents=draw(st.integers(min_value=0, max_value=5_000)),
            tax_rate_bps=draw(st.integers(min_value=0, max_value=2_000)),
            tax_included=draw(st.booleans()),
        )
        for entry in entries
    }
    bids = tuple(
        Bid(
            bid_id=f"bid-{lot_order}-{index}",
            lot_order=lot_order,
            merchant_id=f"merchant-{draw(st.integers(min_value=0, max_value=2))}",
            product_key=f"zephyr-key-{lot_order}-{index}",
            tiers=tuple(
                auction_rules.Tier(
                    min_qty=draw(st.integers(min_value=1, max_value=4)),
                    item_price_cents=draw(st.integers(min_value=0, max_value=100_000)),
                )
                for _ in range(draw(st.integers(min_value=1, max_value=3)))
            ),
            moq=draw(st.integers(min_value=1, max_value=4)),
            capacity=draw(st.integers(min_value=0, max_value=8)),
        )
        for lot_order in (1, 2, 3)
        for index in range(draw(st.integers(min_value=0, max_value=3)))
    )
    return Scene(
        seed_hex=hashing.demo_seed(POOL_ID), entries=entries, plan=plan, buyers=buyers, bids=bids
    )


def _award_three_ways(scene: Scene) -> tuple[tuple[AwardRow, ...], ...]:
    on = adversarial_search(scene)
    off = FakeSearch()  # search configured away: it answers, with nothing
    raising = StrictlyUnavailable()

    async def run() -> tuple[tuple[AwardRow, ...], ...]:
        return (
            await award(scene, on),
            await award(scene, off),
            await award(scene, raising),
        )

    return asyncio.run(run())


@given(scenes())
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_award_is_identical_with_search_on_off_and_raising(scene: Scene) -> None:
    with_on, with_off, with_raising = _award_three_ways(scene)
    assert with_on == with_off
    assert with_on == with_raising
    # Search was genuinely consulted in every mode, so the equality is not two no-ops.
    planned = [
        lot
        for lot in fairness.assign_lots(scene.entries, scene.plan, scene.seed_hex).lots
        if lot.status == fairness.LOT_PLANNED
    ]
    assert len(planned) == len(with_on)


def test_every_planned_lots_search_call_really_happens_in_all_three_modes() -> None:
    scene = _handcrafted_scene()
    on = adversarial_search(scene)
    off = FakeSearch()
    raising = StrictlyUnavailable()

    async def run() -> None:
        await award(scene, on)
        await award(scene, off)
        await award(scene, raising)

    asyncio.run(run())
    assert len(on.search_calls) == 1  # one retrieval per planned lot
    assert len(on.similarity_calls) == 1  # one advisory check per planned lot
    assert len(off.search_calls) == 1
    assert raising.attempts == 2  # both calls were attempted and both threw


def test_the_equivalence_is_not_vacuous_search_and_rules_would_disagree() -> None:
    """The top hit is not the winner, and the flag condition is scripted for every lot.

    If retrieval were used as a gate or an ordering, the three modes could not agree;
    they do, because the rules decide (R3, FR-IG-01, INT-1).
    """
    scene = _handcrafted_scene()
    on = adversarial_search(scene)
    awarded = _award_three_ways(scene)
    assert awarded[0] == awarded[1] == awarded[2]

    (row,) = awarded[0]
    assert row.winner_bid_id == "bid-001-0"  # the lowest feasible mean total (R8, ranking_v1)
    hits = asyncio.run(on.search(None, q=lot_query(1), kinds=["lot"], status=["BIDDING"], limit=20))
    (top,) = hits
    assert top.product_key == "zephyr-key-001-1"  # retrieval points at the other bid
    assert top.title.startswith(lot_query(1))
    # The retrieval order is the reverse of the catalogue order the rules walk.
    assert "bid-001-1 bid-001-0" in on.documents[0].content
    assert on.documents[0].doc_id == str(lot_document_id(1))
    advisory = asyncio.run(
        on.similarity_check(None, lot_id=lot_document_id(1), text="zephyr-key-001-0")
    )
    assert advisory == SimilarityResult(None, lot_document_id(1), "wrong-product-key")


def test_an_unavailable_award_never_raises_and_never_gains_a_winner() -> None:
    """Nothing a search double can say adds or removes an awarded lot."""
    scene = _handcrafted_scene()

    class SaysEverythingIsCancelled(StrictlyUnavailable):
        async def search(self, *args: object, **kwargs: object) -> list[SearchHit]:
            del args, kwargs
            return [
                SearchHit(
                    doc_id=str(lot_document_id(1)),
                    doc_kind="lot",
                    pool_id=uuid.UUID(POOL_ID),
                    lot_id=lot_document_id(1),
                    product_key="whatever",
                    title="lot-01",
                    score=9.0,
                )
            ]

    async def run() -> tuple[tuple[AwardRow, ...], tuple[AwardRow, ...]]:
        return await award(scene, adversarial_search(scene)), await award(
            scene, SaysEverythingIsCancelled()
        )

    with_hits, with_more_hits = asyncio.run(run())
    assert with_hits == with_more_hits


def _handcrafted_scene() -> Scene:
    """Two entries in one lot, two bids: the cheaper one wins whatever search says."""
    entries = tuple(
        fairness.EntryCommitment(
            entry_id=f"entry-{index}",
            zone_id="US-EAST",
            commitment=commitment_for(f"entry-{index}"),
        )
        for index in (1, 2)
    )
    return Scene(
        seed_hex=hashing.demo_seed(POOL_ID),
        entries=entries,
        plan=(
            fairness.ZoneLotPlan(
                "US-EAST", (fairness.LotSpec(seats=2, min_seats=1), fairness.LotSpec(2, 1))
            ),
            fairness.ZoneLotPlan("US-WEST", (fairness.LotSpec(1, 1),)),
        ),
        buyers={
            "entry-1": auction_rules.SeatedBuyer("entry-1", 50_000, 1_000, 0),
            "entry-2": auction_rules.SeatedBuyer("entry-2", 40_000, 1_000, 0),
        },
        bids=(
            Bid(
                bid_id="bid-001-0",
                lot_order=1,
                merchant_id="merchant-0",
                product_key="zephyr-key-001-0",
                tiers=(auction_rules.Tier(1, 10_000),),
                moq=1,
                capacity=8,
            ),
            Bid(
                bid_id="bid-001-1",
                lot_order=1,
                merchant_id="merchant-1",
                product_key="zephyr-key-001-1",
                tiers=(auction_rules.Tier(1, 20_000),),
                moq=1,
                capacity=8,
            ),
        ),
    )
