"""T04A06 / FR-SL-04: the frozen rules document hashes to the vector (fairness §7).

`docs/implementation-plan.md` names this file for the acceptance "rules document and
rules_hash match the vectors". The key set is part of the contract, so a document that
gains or loses one key is refused rather than hashed into a different meaning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fairpool.domain import hashing
from fairpool.domain.hashing import HashingError

VECTORS = Path(__file__).resolve().parents[3] / "docs/contracts/vectors/fairness_v1.json"


@pytest.fixture(scope="module")
def rules_vector() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8"))["rules"]
    return document


def test_rules_hash_vector_reproduces(rules_vector: dict[str, Any]) -> None:
    document = rules_vector["document"]
    assert hashing.canonical_json(document) == rules_vector["canonical_json"]
    assert hashing.rules_hash(document) == rules_vector["sha256"]


def test_rules_hash_rejects_a_missing_key(rules_vector: dict[str, Any]) -> None:
    document = dict(rules_vector["document"])
    document.pop("beacon")
    with pytest.raises(HashingError, match="missing=\\['beacon'\\]"):
        hashing.rules_hash(document)


def test_rules_hash_rejects_an_extra_key(rules_vector: dict[str, Any]) -> None:
    document = dict(rules_vector["document"])
    # An added key must not silently define a new rules_hash: the browser recompute and
    # the server would disagree about what was frozen at publish.
    document["integrity_finding"] = "none"
    with pytest.raises(HashingError, match="extra=\\['integrity_finding'\\]"):
        hashing.rules_hash(document)


@pytest.mark.parametrize("version", [0, 2, "1"])
def test_rules_hash_refuses_a_version_it_cannot_interpret(version: object) -> None:
    document = dict(json.loads(VECTORS.read_text(encoding="utf-8"))["rules"]["document"])
    document["v"] = version
    with pytest.raises(HashingError):
        hashing.rules_hash(document)
