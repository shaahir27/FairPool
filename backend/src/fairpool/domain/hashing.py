"""Canonical JSON, SHA-256 domain hashes, Merkle proofs and Ed25519 receipts.

Contract: ``docs/contracts/fairness-and-hashing.md``. Every formula here is
reproduced by ``docs/contracts/vectors/fairness_v1.json`` (PT-03) and by the
browser verify-my-place widget; do not change a byte format without a contract
change request (I11, I13).

Ed25519 lives only in this module; the receipt seed is 32 raw bytes and all
base64url output is unpadded.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .errors import CanonicalJSONError, HashingError

_COMMIT_PREFIX: Final = "fairpool/commit/v1"
_RANK_PREFIX: Final = "fairpool/rank/v1"
_DEMO_SEED_PREFIX: Final = "fairpool/demo-seed/v1"
_LOT_SEED_PREFIX: Final = "fairpool/lot-seed/v1"
_TIEBREAK_PREFIX: Final = "fairpool/tiebreak/v1"
_EMPTY_PREFIX: Final = "fairpool/empty/v1"

_HEX_DIGITS: Final = frozenset("0123456789abcdef")

_RULES_DOCUMENT_KEYS: Final = frozenset(
    {
        "v",
        "pool_id",
        "rule_version",
        "template",
        "lot_plan",
        "timeline",
        "require_paypal_link",
        "allocation",
        "bid_ranking",
        "refill",
        "beacon",
        "disclosures",
    }
)
_AWARD_KEYS: Final = frozenset(
    {
        "v",
        "lot_id",
        "bid_revision_id",
        "merchant_id",
        "tier_index",
        "item_cents",
        "moq",
        "totals",
        "valid_until",
        "rule_version",
    }
)
_AUDIT_ROW_KEYS: Final = frozenset(
    {"actor", "action", "subject_type", "subject_id", "payload", "created_at"}
)

#: The first audit row's ``prev_hash`` (contract section 8).
ZERO_HASH: Final = "0" * 64


def _require_hex64(value: object, field: str) -> str:
    """Return a 64-character lowercase hex string or raise ``HashingError``."""
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX_DIGITS:
        raise HashingError(f"{field} must be 64 lowercase hex characters")
    return value


def _require_exact_keys(
    document: Mapping[str, object], required: frozenset[str], name: str
) -> None:
    missing = required - set(document.keys())
    extra = set(document.keys()) - required
    if missing or extra:
        raise HashingError(f"{name} keys mismatch: missing={sorted(missing)} extra={sorted(extra)}")


# ---------------------------------------------------------------------------
# Canonical JSON (contract section 1)
# ---------------------------------------------------------------------------


def _validate_canonical(value: object, path: str) -> None:
    if value is None or isinstance(value, bool | int | str):
        return
    if isinstance(value, float):
        raise CanonicalJSONError(f"floats are forbidden at {path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError(f"non-string key at {path}: {type(key).__name__}")
            if not key.isascii():
                raise CanonicalJSONError(f"non-ASCII key at {path}: {key!r}")
            _validate_canonical(item, f"{path}.{key}")
        return
    raise CanonicalJSONError(f"unsupported type at {path}: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Encode with sorted keys, no whitespace and non-ASCII values preserved."""
    _validate_canonical(value, "$")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


# ---------------------------------------------------------------------------
# SHA-256 domain hashes (contract section 2)
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    """SHA-256 of UTF-8 text or raw bytes as 64 lowercase hex characters."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


def request_hash(canonical_request: Mapping[str, object]) -> str:
    return sha256_hex(canonical_json(dict(canonical_request)))


def commitment(
    pool_id: str,
    entry_id: str,
    request_hash: str,
    salt_hex: str,
) -> str:
    """``sha256("fairpool/commit/v1|pool_id|entry_id|request_hash|salt_hex")``."""
    _require_hex64(request_hash, "request_hash")
    _require_hex64(salt_hex, "salt_hex")
    return sha256_hex(f"{_COMMIT_PREFIX}|{pool_id}|{entry_id}|{request_hash}|{salt_hex}")


def rank_hash(seed_hex: str, commitment: str) -> str:
    """``sha256("fairpool/rank/v1|seed_hex|commitment")``."""
    _require_hex64(seed_hex, "seed_hex")
    _require_hex64(commitment, "commitment")
    return sha256_hex(f"{_RANK_PREFIX}|{seed_hex}|{commitment}")


def demo_seed(pool_id: str) -> str:
    """``sha256("fairpool/demo-seed/v1|pool_id")`` (BEACON_MODE=demo)."""
    return sha256_hex(f"{_DEMO_SEED_PREFIX}|{pool_id}")


def lot_seed(seed_hex: str, lot_id: str) -> str:
    """``sha256("fairpool/lot-seed/v1|seed_hex|lot_id")``."""
    _require_hex64(seed_hex, "seed_hex")
    return sha256_hex(f"{_LOT_SEED_PREFIX}|{seed_hex}|{lot_id}")


def tiebreak_hash(lot_seed: str, merchant_id: str) -> str:
    """``sha256("fairpool/tiebreak/v1|lot_seed|merchant_id")`` (FR-AU-04)."""
    _require_hex64(lot_seed, "lot_seed")
    return sha256_hex(f"{_TIEBREAK_PREFIX}|{lot_seed}|{merchant_id}")


# ---------------------------------------------------------------------------
# Merkle tree (contract section 3)
# ---------------------------------------------------------------------------


def leaf_hash(commitment: str) -> str:
    """``sha256(0x00 || bytes(commitment))``; the commitment hex decodes to 32 bytes."""
    return sha256_hex(b"\x00" + bytes.fromhex(_require_hex64(commitment, "commitment")))


def parent_hash(left: str, right: str) -> str:
    """``sha256(0x01 || left || right)`` over 32-byte hashes."""
    left_hex = _require_hex64(left, "left")
    right_hex = _require_hex64(right, "right")
    return sha256_hex(b"\x01" + bytes.fromhex(left_hex) + bytes.fromhex(right_hex))


def _next_level(level: Sequence[str]) -> list[str]:
    next_level = [
        parent_hash(level[index], level[index + 1]) for index in range(0, len(level) - 1, 2)
    ]
    if len(level) % 2:
        # An odd node is promoted unchanged and adds no proof step (contract section 3.3).
        next_level.append(level[-1])
    return next_level


def _validate_commitments(commitments: Iterable[str]) -> list[str]:
    return sorted(_require_hex64(item, "commitment") for item in commitments)


#: ``sha256("fairpool/empty/v1")``, the root published for a pool with no entries.
EMPTY_MERKLE_ROOT: Final = sha256_hex(_EMPTY_PREFIX)


def merkle_root(commitments: Iterable[str]) -> str:
    """Root over the ascending commitment list; the empty list has the empty root."""
    level = [leaf_hash(item) for item in _validate_commitments(commitments)]
    if not level:
        return EMPTY_MERKLE_ROOT
    while len(level) > 1:
        level = _next_level(level)
    return level[0]


@dataclass(frozen=True)
class MerkleStep:
    """One inclusion-proof step; ``side`` is the side the sibling hash sits on."""

    side: str
    hash: str

    def __post_init__(self) -> None:
        if self.side not in ("L", "R"):
            raise HashingError(f"Merkle step side must be L or R, got {self.side!r}")
        _require_hex64(self.hash, "sibling hash")

    def to_dict(self) -> dict[str, str]:
        return {"side": self.side, "hash": self.hash}


def inclusion_proof(commitments: Iterable[str], commitment: str) -> tuple[MerkleStep, ...]:
    """Proof from the leaf to the root, leaf first (contract section 3.5)."""
    target = _require_hex64(commitment, "commitment")
    ordered = _validate_commitments(commitments)
    if ordered.count(target) != 1:
        raise HashingError("commitment must appear exactly once in the tree")
    node_index = ordered.index(target)
    level = [leaf_hash(item) for item in ordered]
    steps: list[MerkleStep] = []
    while len(level) > 1:
        if node_index % 2 == 1:
            steps.append(MerkleStep(side="L", hash=level[node_index - 1]))
        elif node_index + 1 < len(level):
            steps.append(MerkleStep(side="R", hash=level[node_index + 1]))
        level = _next_level(level)
        node_index //= 2
    return tuple(steps)


def verify_inclusion_proof(
    commitment: str,
    proof: Sequence[MerkleStep],
    root: str,
) -> bool:
    """Recompute the root from a leaf and its proof."""
    expected_root = _require_hex64(root, "root")
    node = leaf_hash(commitment)
    for step in proof:
        if step.side == "L":
            node = parent_hash(step.hash, node)
        else:
            node = parent_hash(node, step.hash)
    return node == expected_root


# ---------------------------------------------------------------------------
# Ed25519 receipts (contract section 6)
# ---------------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii"))


def _private_key(seed: bytes) -> Ed25519PrivateKey:
    if len(seed) != 32:
        raise HashingError("Ed25519 private seed must be exactly 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def ed25519_public_key(seed: bytes) -> str:
    """Raw 32-byte public key, base64url without padding."""
    raw = _private_key(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return _b64url(raw)


def sign_ed25519(payload: Mapping[str, object], seed: bytes) -> str:
    """Sign ``canonical_json(payload)``; base64url without padding."""
    message = canonical_json(dict(payload)).encode("utf-8")
    return _b64url(_private_key(seed).sign(message))


def verify_ed25519(
    payload: Mapping[str, object],
    signature_b64url: str,
    public_key_b64url: str,
) -> bool:
    """Verify a receipt signature over ``canonical_json(payload)``."""
    message = canonical_json(dict(payload)).encode("utf-8")
    try:
        signature = _b64url_decode(signature_b64url)
        public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64url))
        public_key.verify(signature, message)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


def receipt_payload(
    pool_id: str,
    entry_id: str,
    commitment: str,
    received_at: str,
) -> dict[str, object]:
    """Entry receipt payload; the buyer also keeps ``salt_hex`` and ``request_hash``."""
    return {
        "commitment": _require_hex64(commitment, "commitment"),
        "entry_id": entry_id,
        "pool_id": pool_id,
        "received_at": received_at,
        "v": 1,
    }


def bid_receipt_hash(
    bid_id: str,
    revision: int,
    structured: Mapping[str, object],
    submitted_at: str,
) -> str:
    """``sha256(canonical_json({"bid_id","revision","structured","submitted_at","v":1}))``."""
    return sha256_hex(
        canonical_json(
            {
                "bid_id": bid_id,
                "revision": revision,
                "structured": dict(structured),
                "submitted_at": submitted_at,
                "v": 1,
            }
        )
    )


def bid_receipt_payload(bid_id: str, revision: int, receipt_hash: str) -> dict[str, object]:
    """The object a merchant's bid receipt signature covers (contract section 6)."""
    return {
        "bid_id": bid_id,
        "receipt_hash": _require_hex64(receipt_hash, "receipt_hash"),
        "revision": revision,
        "v": 1,
    }


# ---------------------------------------------------------------------------
# Rules, award and audit document hashes (contract sections 7 and 8)
# ---------------------------------------------------------------------------


def rules_hash(rules_document: Mapping[str, object]) -> str:
    """Hash the frozen rules document published with the pool (FR-LT-03)."""
    _require_exact_keys(rules_document, _RULES_DOCUMENT_KEYS, "rules_document")
    if rules_document["v"] != 1:
        raise HashingError("rules_document v must be 1")
    return sha256_hex(canonical_json(dict(rules_document)))


def award_hash(award: Mapping[str, object]) -> str:
    """Hash the immutable award snapshot (contract section 7)."""
    _require_exact_keys(award, _AWARD_KEYS, "award")
    if award["v"] != 1:
        raise HashingError("award v must be 1")
    return sha256_hex(canonical_json(dict(award)))


def audit_hash(prev_hash: str, row: Mapping[str, object]) -> str:
    """``sha256(prev_hash + "|" + canonical_json(row))`` (contract section 8)."""
    previous = _require_hex64(prev_hash, "prev_hash")
    _require_exact_keys(row, _AUDIT_ROW_KEYS, "audit row")
    return sha256_hex(f"{previous}|{canonical_json(dict(row))}")
