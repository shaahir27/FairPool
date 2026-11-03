"""T06A07 unit half: the key hash, the bearer parse and the scope vocabulary.

``db-schema.md`` says a merchant key is stored "only as an HMAC-SHA256 of the full key
with ``HMAC_KEY``" and shown once, so the two properties that make that safe are testable
without a database: the hash is a pure function of (key, HMAC_KEY), and the only thing
that can recover a key from a stored row is a guess that hashes to the same value.

The parse is the other half of the refusal rule: a malformed bearer must be rejected
before any row is looked up, because "unknown prefix" and "bad format" must not be
distinguishable answers (``api.md`` section 4.3).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.modules.merchants.api_keys import (
    KEY_PREFIX,
    PREFIX_CHARS,
    SCOPES,
    hash_key,
    matches,
)
from fairpool.modules.merchants.auth import _split_key, require_scope
from fairpool.ports import MerchantPrincipal

GOOD_KEY = f"{KEY_PREFIX}_{'a' * PREFIX_CHARS}_{'B' * 43}"


def test_the_same_key_under_the_same_secret_always_hashes_alike() -> None:
    assert hash_key("secret-1", GOOD_KEY) == hash_key("secret-1", GOOD_KEY)
    assert len(hash_key("secret-1", GOOD_KEY)) == 64
    assert all(c in "0123456789abcdef" for c in hash_key("secret-1", GOOD_KEY))


def test_a_different_hmac_key_is_a_different_table() -> None:
    """A stolen ``merchant_api_keys`` row is useless without ``HMAC_KEY``."""
    assert hash_key("secret-1", GOOD_KEY) != hash_key("secret-2", GOOD_KEY)


def test_one_character_of_the_key_changes_everything() -> None:
    other = GOOD_KEY[:-1] + ("X" if GOOD_KEY[-1] != "X" else "Y")
    assert hash_key("secret-1", GOOD_KEY) != hash_key("secret-1", other)


def test_matches_accepts_only_the_key_the_row_was_made_from() -> None:
    stored = hash_key("secret-1", GOOD_KEY)
    assert matches("secret-1", GOOD_KEY, stored) is True
    assert matches("secret-1", GOOD_KEY[:-1], stored) is False
    assert matches("secret-1", f"{KEY_PREFIX}_{'a' * PREFIX_CHARS}_{'B' * 42}c", stored) is False
    assert matches("secret-2", GOOD_KEY, stored) is False


def test_a_wellformed_bearer_splits_into_its_prefix_and_secret() -> None:
    assert _split_key(GOOD_KEY) == ("a" * PREFIX_CHARS, "B" * 43)


@pytest.mark.parametrize(
    "bearer",
    [
        "",
        f"fpn_{'a' * PREFIX_CHARS}_{'B' * 43}",  # our shape, a prefix that is not ours
        f"fpm_{'a' * 7}_{'B' * 43}",
        f"fpm_{'a' * 9}_{'B' * 43}",
        f"fpm_{'a' * PREFIX_CHARS}_",
        f"fpm_{'a' * PREFIX_CHARS}",
        f"{'a' * PREFIX_CHARS}_{'B' * 43}",
    ],
)
def test_a_malformed_bearer_splits_into_nothing(bearer: str) -> None:
    """Nothing here reaches a ``SELECT``, so no answer can confirm a prefix exists."""
    assert _split_key(bearer) == (None, None)


def test_the_scope_vocabulary_is_exactly_the_six_names_in_the_schema() -> None:
    assert SCOPES == frozenset(
        {
            "lots:read",
            "bids:read",
            "bids:write",
            "fulfillment:read",
            "shipments:write",
            "manifest:read",
        }
    )


def test_a_key_that_lacks_the_scope_is_refused_with_the_contracted_code() -> None:
    principal = MerchantPrincipal(
        merchant_id=uuid4(), scopes=frozenset({"lots:read"}), via="api_key"
    )
    require_scope(principal, "lots:read")
    with pytest.raises(ApplicationError) as caught:
        require_scope(principal, "shipments:write")
    assert caught.value.code == "API_KEY_SCOPE"
