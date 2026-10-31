"""Vectors test: every value in ``docs/contracts/vectors/fairness_v1.json``.

Each assertion computes the value from the vector's own inputs; no expected
hash, signature or root is copied into this file. The test also covers the
allocation and waitlist helpers that share the same ranking rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fairpool.domain import auction_rules, fairness, hashing, money
from fairpool.domain.errors import AllocationError, HashingError

ROOT = Path(__file__).resolve().parents[3]
VECTORS_PATH = ROOT / "docs" / "contracts" / "vectors" / "fairness_v1.json"


@pytest.fixture(scope="module")
def vectors() -> dict[str, Any]:
    with VECTORS_PATH.open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def _commitments(vectors: dict[str, Any]) -> list[str]:
    return [entry["commitment"] for entry in vectors["entries"]]


def test_canonical_json_cases(vectors: dict[str, Any]) -> None:
    for case in vectors["canonical_json_cases"]:
        assert hashing.canonical_json(case["input"]) == case["output"]


def test_request_hashes_and_commitments(vectors: dict[str, Any]) -> None:
    for entry in vectors["entries"]:
        request = entry["canonical_request"]
        computed_request_hash = hashing.request_hash(request)
        assert computed_request_hash == entry["request_hash"]
        computed_commitment = hashing.commitment(
            request["pool_id"], entry["entry_id"], computed_request_hash, entry["salt_hex"]
        )
        assert computed_commitment == entry["commitment"]
        assert hashing.rank_hash(vectors["seed_hex"], computed_commitment) == entry["rank_hash"]


def test_sorted_commitments(vectors: dict[str, Any]) -> None:
    assert sorted(_commitments(vectors)) == vectors["sorted_commitments"]


def test_merkle_root(vectors: dict[str, Any]) -> None:
    assert hashing.merkle_root(_commitments(vectors)) == vectors["merkle_root"]
    shuffled = list(reversed(_commitments(vectors)))
    assert hashing.merkle_root(shuffled) == vectors["merkle_root"]


def test_inclusion_proof(vectors: dict[str, Any]) -> None:
    inclusion = vectors["inclusion_proof"]
    proof = hashing.inclusion_proof(_commitments(vectors), inclusion["commitment"])
    assert [step.to_dict() for step in proof] == inclusion["steps"]
    assert hashing.verify_inclusion_proof(inclusion["commitment"], proof, vectors["merkle_root"])


def test_empty_merkle_root(vectors: dict[str, Any]) -> None:
    assert hashing.EMPTY_MERKLE_ROOT == hashing.sha256_hex("fairpool/empty/v1")
    assert hashing.merkle_root([]) == hashing.EMPTY_MERKLE_ROOT
    with pytest.raises(HashingError):
        hashing.inclusion_proof([], "ab" * 32)


def test_demo_seed(vectors: dict[str, Any]) -> None:
    pool_id = vectors["entries"][0]["canonical_request"]["pool_id"]
    assert hashing.demo_seed(pool_id) == vectors["demo_seed"]


def test_rank_order(vectors: dict[str, Any]) -> None:
    entries = [
        fairness.EntryCommitment(
            entry_id=entry["entry_id"],
            zone_id=entry["canonical_request"]["delivery"]["zone_id"],
            commitment=entry["commitment"],
        )
        for entry in vectors["entries"]
    ]
    ranked = fairness.rank_order(entries, vectors["seed_hex"])
    assert [entry.entry_id for entry in ranked] == vectors["order"]
    assert [entry.rank for entry in ranked] == list(range(1, len(entries) + 1))
    expected_hashes = {entry["entry_id"]: entry["rank_hash"] for entry in vectors["entries"]}
    for ranked_entry in ranked:
        assert ranked_entry.rank_hash == expected_hashes[ranked_entry.entry_id]


def test_receipt_payload_and_signature(vectors: dict[str, Any]) -> None:
    receipt = vectors["receipt"]
    seed = bytes.fromhex(receipt["private_key_hex"])
    payload = receipt["payload"]
    assert hashing.canonical_json(payload) == receipt["payload_canonical"]
    assert (
        hashing.receipt_payload(
            payload["pool_id"], payload["entry_id"], payload["commitment"], payload["received_at"]
        )
        == payload
    )
    assert hashing.ed25519_public_key(seed) == receipt["public_key_b64url"]
    signature = hashing.sign_ed25519(payload, seed)
    assert signature == receipt["signature_b64url"]
    assert "=" not in signature
    assert hashing.verify_ed25519(payload, signature, receipt["public_key_b64url"])
    tampered = dict(payload)
    tampered["commitment"] = hashing.sha256_hex("tampered")
    assert not hashing.verify_ed25519(tampered, signature, receipt["public_key_b64url"])


def test_audit_chain(vectors: dict[str, Any]) -> None:
    previous = hashing.ZERO_HASH
    for item in vectors["audit_chain"]:
        assert item["prev_hash"] == previous
        previous = hashing.audit_hash(item["prev_hash"], item["row"])
        assert previous == item["hash"]


def test_tax_and_mean_cases(vectors: dict[str, Any]) -> None:
    for case in vectors["money"]["tax_cases"]:
        assert money.tax_cents(case["item_cents"], case["rate_bps"]) == case["tax_cents"]
    for case in vectors["money"]["mean_cases"]:
        assert money.mean_total_cents(case["values"]) == case["mean_cents"]


def test_lot_seed_and_tiebreaks(vectors: dict[str, Any]) -> None:
    tiebreak = vectors["tiebreak"]
    assert hashing.lot_seed(vectors["seed_hex"], tiebreak["lot_id"]) == tiebreak["lot_seed"]
    assert (
        hashing.tiebreak_hash(tiebreak["lot_seed"], tiebreak["merchant_a"])
        == tiebreak["tiebreak_a"]
    )
    assert (
        hashing.tiebreak_hash(tiebreak["lot_seed"], tiebreak["merchant_b"])
        == tiebreak["tiebreak_b"]
    )


def test_tier_case(vectors: dict[str, Any]) -> None:
    case = vectors["tier_case"]
    seated = [
        auction_rules.SeatedBuyer(
            entry_id=f"entry-{index}",
            cap_cents=cap,
            shipping_cents=case["shipping_cents"],
            tax_rate_bps=case["tax_rate_bps"],
        )
        for index, cap in enumerate(case["caps_cents"])
    ]
    tiers = [
        auction_rules.Tier(min_qty=tier["min_qty"], item_price_cents=tier["item_price_cents"])
        for tier in case["tiers"]
    ]
    evaluations = auction_rules.evaluate_tiers(seated, tiers)
    for expected, evaluation in zip(case["tiers"], evaluations, strict=True):
        assert {item.total_cents for item in evaluation.totals} == {expected["total_cents"]}
        assert evaluation.n_tier == expected["n_can_accept"]
        assert evaluation.applies is expected["applies"]
    resolution = auction_rules.resolve_tiers(seated, tiers, moq=1)
    assert resolution.chosen_tier_index == case["chosen_tier_index"]
    assert resolution.feasible
    chosen = resolution.evaluations[case["chosen_tier_index"]]
    tiebreak = vectors["tiebreak"]["tiebreak_a"]
    key = auction_rules.bid_ranking_key(resolution, tiebreak)
    assert key == (chosen.mean_total_cents, chosen.max_total_cents, tiebreak)


def test_rank_order_breaks_ties_on_entry_id() -> None:
    shared = hashing.sha256_hex("shared commitment")
    entries = [
        fairness.EntryCommitment("bbbb", "ZONE", shared),
        fairness.EntryCommitment("aaaa", "ZONE", shared),
    ]
    ranked = fairness.rank_order(entries, hashing.demo_seed("pool"))
    assert [entry.entry_id for entry in ranked] == ["aaaa", "bbbb"]
    assert ranked[0].rank_hash == ranked[1].rank_hash


def test_rank_order_rejects_duplicate_entries() -> None:
    entry = fairness.EntryCommitment("aaaa", "ZONE", hashing.sha256_hex("a"))
    with pytest.raises(AllocationError):
        fairness.rank_order([entry, entry], hashing.demo_seed("pool"))


def test_assign_lots_cancels_undersized_lots_and_waitlists_remainder() -> None:
    entries = [
        fairness.EntryCommitment(f"z1-{index}", "Z1", hashing.sha256_hex(f"z1-{index}"))
        for index in range(3)
    ] + [
        fairness.EntryCommitment("z2-0", "Z2", hashing.sha256_hex("z2-0")),
        fairness.EntryCommitment("z2-1", "Z2", hashing.sha256_hex("z2-1")),
        fairness.EntryCommitment("z3-0", "Z3", hashing.sha256_hex("z3-0")),
    ]
    plan = [
        fairness.ZoneLotPlan("Z1", (fairness.LotSpec(2, 2), fairness.LotSpec(2, 2))),
        fairness.ZoneLotPlan("Z2", (fairness.LotSpec(2, 2),)),
    ]
    result = fairness.assign_lots(entries, plan, hashing.demo_seed("pool"))
    assert [lot.status for lot in result.lots] == [
        fairness.LOT_PLANNED,
        fairness.LOT_CANCELLED,
        fairness.LOT_PLANNED,
    ]
    assert [lot.lot_order for lot in result.lots] == [1, 2, 3]
    assert [lot.lot_index for lot in result.lots] == [0, 1, 0]
    assert len(result.lots[0].entry_ids) == 2
    assert result.lots[1].entry_ids == ()
    assert set(result.lots[2].entry_ids) == {"z2-0", "z2-1"}
    assert sorted(item.entry_id for item in result.allocations) == sorted(
        entry.entry_id for entry in entries
    )
    seated = {item.entry_id for item in result.allocations if item.status == fairness.ENTRY_SEATED}
    assert len(seated) == 4
    waitlisted = {item.entry_id for item in result.waitlist}
    assert waitlisted == ({"z1-0", "z1-1", "z1-2"} - seated) | {"z3-0"}
    assert result.waitlist[0].zone_id == "Z1"
    assert result.waitlist[-1].zone_id == "Z3"


def test_assign_lots_rejects_invalid_plans() -> None:
    entry = fairness.EntryCommitment("aaaa", "Z1", hashing.sha256_hex("a"))
    with pytest.raises(AllocationError):
        fairness.assign_lots(
            [entry], [fairness.ZoneLotPlan("Z1", (fairness.LotSpec(0, 0),))], hashing.demo_seed("p")
        )
    with pytest.raises(AllocationError):
        fairness.assign_lots(
            [entry],
            [fairness.ZoneLotPlan("Z1", (fairness.LotSpec(1, 0),))] * 2,
            hashing.demo_seed("p"),
        )


def test_waitlist_candidate_skips_cap_ineligible_and_missing_totals() -> None:
    candidates = [
        fairness.WaitlistCandidate("a", "Z", 1, 100),
        fairness.WaitlistCandidate("b", "Z", 2, 1000, entry_status="WITHDRAWN"),
        fairness.WaitlistCandidate("c", "Y", 3, 1000),
        fairness.WaitlistCandidate("d", "Z", 4, 500),
        fairness.WaitlistCandidate("e", "Z", 5, 1000),
    ]
    totals = {"a": 500, "b": 500, "d": 500}
    chosen = fairness.waitlist_candidate(candidates, totals, zone_id="Z")
    assert chosen is not None
    assert chosen.entry_id == "d"
    assert fairness.waitlist_candidate(candidates, totals, zone_id="Y") is None
    assert fairness.waitlist_candidate([], {}, zone_id="Z") is None


def test_waitlist_candidate_rejects_invalid_rank() -> None:
    candidate = fairness.WaitlistCandidate("a", "Z", 0, 1000)
    with pytest.raises(AllocationError):
        fairness.waitlist_candidate([candidate], {"a": 500}, zone_id="Z")


def test_fixed_rules_document_vector(vectors):
    case = vectors["rules"]
    assert hashing.canonical_json(case["document"]) == case["canonical_json"]
    assert hashing.rules_hash(case["document"]) == case["sha256"]
