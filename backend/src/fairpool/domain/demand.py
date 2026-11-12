"""Demand clustering rules (CR-17, FR-DM-02). Pure: no I/O, no provider, no clock.

A cluster is the set of buyers who asked for the same canonical product. The key is
derived from fields the buyer confirmed, so two people who word the same request
differently share a cluster and a different condition or bundle never does. Similarity
scores may *suggest* a merge to a human; they never compute this key (INT-1).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from fairpool.domain.hashing import canonical_json

CONDITIONS = frozenset({"NEW", "REFURBISHED", "OPEN_BOX"})
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def normalize_text(value: str) -> str:
    """Casefold and collapse every separator, so ``27-inch`` and ``27 inch`` agree."""
    return _SEPARATORS.sub(" ", value.casefold()).strip()


def cluster_key(
    *,
    product_key: str,
    condition: str,
    variant: str | None,
    bundle_contents: Sequence[str],
) -> str:
    """The deterministic identity of a demand cluster: 64 hex characters."""
    product = normalize_text(product_key)
    bundle = sorted(normalize_text(item) for item in bundle_contents)
    if not product or not bundle or any(not item for item in bundle):
        raise ValueError("A cluster needs a product and a non-empty bundle")
    if condition not in CONDITIONS:
        raise ValueError("Unknown condition")
    payload = {
        "bundle": bundle,
        "condition": condition,
        "product_key": product,
        "variant": normalize_text(variant or ""),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def cluster_title(*, product_key: str, variant: str | None, condition: str) -> str:
    """A readable label for the forming-demand card and the operator queue."""
    words = normalize_text(product_key).replace("-", " ")
    label = " ".join(part.capitalize() for part in words.split())
    if variant:
        label = f"{label} ({normalize_text(variant)})"
    if condition != "NEW":
        label = f"{label} — {condition.replace('_', ' ').lower()}"
    return label[:200]
