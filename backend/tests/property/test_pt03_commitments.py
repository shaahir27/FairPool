"""PT-03: commitments, Merkle root, inclusion proofs and receipt signatures.

Properties exercised here: canonical JSON is stable and strict, domain hashes
are deterministic and bind their inputs, Merkle roots ignore input order while
every proof verifies, and Ed25519 receipts are deterministic and tamper-evident.
The published vector values themselves are reproduced in
``tests/unit/test_fairness_vectors.py``.
"""

from __future__ import annotations

import json
import string

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from fairpool.domain import hashing
from fairpool.domain.errors import CanonicalJSONError, HashingError

pytestmark = pytest.mark.property

HEX64 = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)
ASCII_KEY = st.text(alphabet=string.ascii_letters + string.digits + "_-", min_size=1, max_size=8)
SEED32 = st.binary(min_size=32, max_size=32)


def _scalars() -> st.SearchStrategy[object]:
    return st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=20))


def _canonical_values() -> st.SearchStrategy[object]:
    return st.recursive(
        _scalars(),
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(ASCII_KEY, children, max_size=4),
        ),
        max_leaves=15,
    )


def _b64url_chars(text: str) -> bool:
    return all(character in string.ascii_letters + string.digits + "-_" for character in text)


@settings(max_examples=100)
@given(_canonical_values())
def test_canonical_json_is_stable(value: object) -> None:
    text = hashing.canonical_json(value)
    assert text == json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert json.loads(text) == value
    assert hashing.canonical_json(json.loads(text)) == text


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_canonical_json_rejects_floats(value: float) -> None:
    with pytest.raises(CanonicalJSONError):
        hashing.canonical_json({"a": [value]})
    with pytest.raises(CanonicalJSONError):
        hashing.canonical_json(value)


@given(st.integers())
def test_canonical_json_rejects_non_string_keys(key: int) -> None:
    with pytest.raises(CanonicalJSONError):
        hashing.canonical_json({key: 1})


@given(st.sampled_from(["é", "ü", "日本", "ключ"]))
def test_canonical_json_rejects_non_ascii_keys(key: str) -> None:
    with pytest.raises(CanonicalJSONError):
        hashing.canonical_json({key: 1})


@given(_scalars())
def test_canonical_json_rejects_unsupported_types(value: object) -> None:
    with pytest.raises(CanonicalJSONError):
        hashing.canonical_json((value,))


@given(HEX64, HEX64, HEX64)
def test_commitment_binds_request_and_salt(request_digest: str, salt_a: str, salt_b: str) -> None:
    assume(salt_a != salt_b)
    first = hashing.commitment("pool", "entry", request_digest, salt_a)
    assert first == hashing.commitment("pool", "entry", request_digest, salt_a)
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")
    assert first != hashing.commitment("pool", "entry", request_digest, salt_b)


@given(HEX64, HEX64, HEX64)
def test_rank_hash_binds_seed(seed_a: str, seed_b: str, commitment: str) -> None:
    assume(seed_a != seed_b)
    first = hashing.rank_hash(seed_a, commitment)
    assert first == hashing.rank_hash(seed_a, commitment)
    assert first != hashing.rank_hash(seed_b, commitment)


@given(st.dictionaries(ASCII_KEY, _canonical_values(), max_size=5))
def test_request_hash_covers_the_canonical_request(document: dict[str, object]) -> None:
    assert hashing.request_hash(document) == hashing.sha256_hex(hashing.canonical_json(document))


@given(st.lists(HEX64, min_size=1, max_size=16, unique=True))
def test_merkle_root_is_order_independent_and_proofs_verify(commitments: list[str]) -> None:
    root = hashing.merkle_root(commitments)
    assert root == hashing.merkle_root(list(reversed(commitments)))
    assert len(root) == 64
    for commitment in commitments:
        proof = hashing.inclusion_proof(commitments, commitment)
        assert hashing.verify_inclusion_proof(commitment, proof, root)
        assert len(proof) <= (len(commitments) - 1).bit_length()
        if proof:
            flipped = hashing.MerkleStep(
                side="L" if proof[0].side == "R" else "R", hash=proof[0].hash
            )
            assert not hashing.verify_inclusion_proof(commitment, (flipped, *proof[1:]), root)


@given(SEED32)
def test_receipt_signature_is_deterministic_and_tamper_evident(seed: bytes) -> None:
    payload = hashing.receipt_payload(
        pool_id="11111111-1111-4111-8111-111111111111",
        entry_id="aaaaaaaa-0000-4000-8000-000000000001",
        commitment=hashing.sha256_hex("entry"),
        received_at="2026-10-28T10:00:00.123456Z",
    )
    public_key = hashing.ed25519_public_key(seed)
    signature = hashing.sign_ed25519(payload, seed)
    assert len(public_key) == 43 and _b64url_chars(public_key) and "=" not in public_key
    assert len(signature) == 86 and _b64url_chars(signature) and "=" not in signature
    assert signature == hashing.sign_ed25519(payload, seed)
    assert hashing.verify_ed25519(payload, signature, public_key)
    tampered = dict(payload)
    tampered["v"] = 2
    assert not hashing.verify_ed25519(tampered, signature, public_key)
    replacement = "A" if signature[0] != "A" else "B"
    assert not hashing.verify_ed25519(payload, replacement + signature[1:], public_key)


@given(
    st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=10),
    st.integers(min_value=1, max_value=20),
    st.dictionaries(ASCII_KEY, _canonical_values(), max_size=4),
)
def test_bid_receipt_hash_binds_the_revision(
    bid_id: str, revision: int, structured: dict[str, object]
) -> None:
    receipt_hash = hashing.bid_receipt_hash(bid_id, revision, structured, "2026-10-28T10:00:00Z")
    assert receipt_hash == hashing.bid_receipt_hash(
        bid_id, revision, structured, "2026-10-28T10:00:00Z"
    )
    assert receipt_hash != hashing.bid_receipt_hash(
        bid_id, revision + 1, structured, "2026-10-28T10:00:00Z"
    )
    payload = hashing.bid_receipt_payload(bid_id, revision, receipt_hash)
    assert payload["receipt_hash"] == receipt_hash


def test_empty_tree_uses_the_domain_separated_root() -> None:
    assert hashing.EMPTY_MERKLE_ROOT == hashing.sha256_hex("fairpool/empty/v1")
    assert hashing.merkle_root([]) == hashing.EMPTY_MERKLE_ROOT


def _rules_document() -> dict[str, object]:
    return {
        "v": 1,
        "pool_id": "11111111-1111-4111-8111-111111111111",
        "rule_version": "allocation_v1",
        "template": {"product_key": "monitor-27-4k"},
        "lot_plan": [{"zone_id": "US-EAST", "lots": [{"seats": 3, "min_seats": 2}]}],
        "timeline": {"open_at": "2026-11-02T10:00:00.000000Z"},
        "require_paypal_link": True,
        "allocation": "seeded_lottery_v1",
        "bid_ranking": "ranking_v1",
        "refill": {"max_refill_waves": 1},
        "beacon": {"source": "demo"},
        "disclosures": {"lots_may_differ": True},
    }


def _award_document() -> dict[str, object]:
    return {
        "v": 1,
        "lot_id": "22222222-2222-4222-8222-222222222222",
        "bid_revision_id": "44444444-4444-4444-8444-444444444444",
        "merchant_id": "33333333-3333-4333-8333-333333333331",
        "tier_index": 1,
        "item_cents": 47000,
        "moq": 2,
        "totals": {"entry": {"item_cents": 47000, "total_cents": 52613}},
        "valid_until": "2026-11-02T11:00:00.000000Z",
        "rule_version": "ranking_v1",
    }


def test_rules_hash_is_the_canonical_document_hash() -> None:
    document = _rules_document()
    assert hashing.rules_hash(document) == hashing.sha256_hex(hashing.canonical_json(document))
    changed = dict(document, disclosures={"lots_may_differ": False})
    assert hashing.rules_hash(document) != hashing.rules_hash(changed)
    missing = dict(document)
    del missing["timeline"]
    with pytest.raises(HashingError):
        hashing.rules_hash(missing)
    with pytest.raises(HashingError):
        hashing.rules_hash(dict(document, extra=True))
    with pytest.raises(HashingError):
        hashing.rules_hash(dict(document, v=2))


def test_award_hash_is_the_canonical_snapshot_hash() -> None:
    award = _award_document()
    assert hashing.award_hash(award) == hashing.sha256_hex(hashing.canonical_json(award))
    changed = dict(award, item_cents=48000)
    assert hashing.award_hash(award) != hashing.award_hash(changed)
    with pytest.raises(HashingError):
        hashing.award_hash({key: value for key, value in award.items() if key != "totals"})
    with pytest.raises(HashingError):
        hashing.award_hash(dict(award, v=2))
    with pytest.raises(CanonicalJSONError):
        hashing.award_hash(dict(award, totals={"entry": {"total_cents": 52613.0}}))


def test_ed25519_requires_a_32_byte_seed() -> None:
    with pytest.raises(HashingError):
        hashing.ed25519_public_key(b"short")
    assert hashing.sha256_hex(b"bytes") == hashing.sha256_hex("bytes")
