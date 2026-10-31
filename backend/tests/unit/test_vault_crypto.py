"""T03B04 CR-3: the AES-256-GCM at-rest primitive and the consent record helpers.

Pure unit tests: no database, no provider. They prove the shape ``vault-charge.md``
section 5 requires of stored credentials (per-row nonce, authenticated decryption,
a key that must be 32 bytes) and the consent wording rules of section 6, including
the one property the rest of the product leans on: a failure never carries the
plaintext it could not decrypt (rule 27, I14).
"""

from __future__ import annotations

import base64
import re

import pytest

from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import sha256_hex
from fairpool.infra.crypto import AesGcmCipher, DecryptionError, key_from_config_value
from fairpool.modules.pools.vault import (
    CONSENT_TEXTS,
    consent_text_sha256,
    label_of,
    render_consent_text,
)

TOKEN_ID = "S-0NV7N5E7U3X2FAKEPAYMENTTOKENID"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def cipher() -> AesGcmCipher:
    return AesGcmCipher(key_from_config_value(base64.b64encode(b"k" * 32).decode("ascii")))


def test_seal_then_open_round_trips_and_never_stores_the_plaintext() -> None:
    subject = cipher()
    nonce, ciphertext = subject.seal(TOKEN_ID)
    assert TOKEN_ID not in repr((nonce, ciphertext))
    assert TOKEN_ID.encode("utf-8") not in ciphertext
    assert subject.open(nonce, ciphertext) == TOKEN_ID


def test_each_row_gets_its_own_nonce() -> None:
    subject = cipher()
    first = subject.seal(TOKEN_ID)
    second = subject.seal(TOKEN_ID)
    # A per-row nonce: two rows holding the same token do not look alike (vault §5).
    assert first[0] != second[0]
    assert first[1] != second[1]
    assert len(first[0]) == 12
    assert subject.open(second[0], second[1]) == TOKEN_ID


def test_foreign_key_tampering_and_short_nonce_all_fail_closed() -> None:
    subject = cipher()
    nonce, ciphertext = subject.seal(TOKEN_ID)

    other = AesGcmCipher(b"x" * 32)
    with pytest.raises(DecryptionError) as wrong_key:
        other.open(nonce, ciphertext)
    with pytest.raises(DecryptionError) as tampered:
        flipped = bytearray(ciphertext)
        flipped[0] ^= 0x01
        subject.open(nonce, bytes(flipped))
    with pytest.raises(DecryptionError) as short_nonce:
        subject.open(nonce[:-1], ciphertext)

    # A failure message is safe to log: never the credential it could not read.
    for error in (wrong_key.value, tampered.value, short_nonce.value):
        assert TOKEN_ID not in str(error)


def test_the_key_must_be_32_bytes_of_base64() -> None:
    assert len(key_from_config_value(base64.b64encode(b"k" * 32).decode("ascii"))) == 32
    with pytest.raises(DecryptionError):
        key_from_config_value(base64.b64encode(b"k" * 31).decode("ascii"))
    with pytest.raises(DecryptionError):
        key_from_config_value("not base64 @@@")
    with pytest.raises(DecryptionError):
        AesGcmCipher(b"k" * 16)


def test_rendered_consent_states_the_cap_in_integer_cents_terms() -> None:
    text = render_consent_text("v1", 60000)
    # "$600.00" is the only money shape allowed outside the PayPal boundary (BD-14).
    assert "$600.00" in text
    assert "60000" not in text
    for phrase in (
        "once for this pool",
        "at or below your maximum",
        "will not show the amount",
        "FairPool, not PayPal, enforces your maximum",
        "withdraw before the pool closes",
        "Nothing is charged if you are not selected",
        "Refunds follow the pool rules",
    ):
        assert phrase in text


def test_an_unknown_consent_version_is_refused_not_assumed() -> None:
    assert set(CONSENT_TEXTS) == {"v1"}
    with pytest.raises(ApplicationError) as refused:
        render_consent_text("v2", 60000)
    assert refused.value.code == "VALIDATION_ERROR"


def test_consent_hash_is_stable_hex_and_binds_the_cap() -> None:
    digest = consent_text_sha256("v1", 60000)
    assert HEX64.match(digest)
    assert digest == consent_text_sha256("v1", 60000)
    assert digest == sha256_hex(render_consent_text("v1", 60000).encode("utf-8"))
    # A different cap is a different consent, so the hash must differ (FR-IN-05).
    assert digest != consent_text_sha256("v1", 59999)


def test_only_the_last_four_characters_of_a_token_are_showable() -> None:
    assert label_of(TOKEN_ID) == TOKEN_ID[-4:]
    assert len(label_of(TOKEN_ID)) == 4
