"""BD-11: the stored address is a Fernet token and never a plaintext fallback."""

from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from fairpool.domain.errors import ApplicationError
from fairpool.modules.checkout.shipping import ShippingCipher

KEY = base64.b64encode(b"A" * 32).decode()
ADDRESS = {
    "name": "Buyer One",
    "line1": "1 Market Street",
    "line2": None,
    "city": "New York",
    "region": "NY",
    "postal_code": "10001",
    "country_code": "US",
}


def test_the_stored_address_round_trips() -> None:
    cipher = ShippingCipher(KEY)
    blob = cipher.seal(ADDRESS)
    assert b"Market Street" not in blob
    assert Fernet(KEY).decrypt(blob) is not None
    assert cipher.open(blob) == {**ADDRESS, "line2": ""}


def test_a_tampered_token_is_an_integrity_error() -> None:
    cipher = ShippingCipher(KEY)
    with pytest.raises(ApplicationError) as caught:
        cipher.open(b"not-a-fernet-token")
    assert caught.value.code == "INTEGRITY_ERROR"


def test_an_unusable_key_never_writes_plaintext() -> None:
    cipher = ShippingCipher("not-a-fernet-key")
    with pytest.raises(ApplicationError) as caught:
        cipher.seal(ADDRESS)
    assert caught.value.code == "INTERNAL_ERROR"
