"""Encrypted shipping address storage (N14, BD-11).

The address is collected at checkout because fulfillment needs it and sent to
PayPal only at ``PAYPAL_PAYLOAD_LEVEL >= 3``. It is written to
``buyer_orders.shipping_enc`` as ``nonce || ciphertext`` from the existing
``AesGcmCipher`` keyed by ``ADDRESS_ENCRYPTION_KEY``, before any provider call
(I9). Nothing here logs, audits or returns a decrypted value: a plaintext address
must never reach a log record, an audit payload, a ledger fact or an API response.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from fairpool.domain.errors import ApplicationError
from fairpool.infra.crypto import NONCE_BYTES, AesGcmCipher, DecryptionError

FIELDS: Final[tuple[str, ...]] = (
    "name",
    "line1",
    "line2",
    "city",
    "region",
    "postal_code",
    "country_code",
)


def _normalise(address: Mapping[str, Any]) -> dict[str, str]:
    normalised: dict[str, str] = {}
    for field in FIELDS:
        value = address.get(field)
        if value is None and field == "line2":
            normalised[field] = ""
            continue
        if not isinstance(value, str) or not value.strip():
            raise ApplicationError("VALIDATION_ERROR")
        normalised[field] = value.strip()
    return normalised


class UnavailableCipher:
    """The cipher when the configured key cannot be decoded.

    Mirrors the vault's missing-key stand-in: construction must not fail the whole
    app, but a checkout that needs to store an address fails with an allowlisted
    code instead of silently dropping it.
    """

    def seal(self, plaintext: str) -> tuple[bytes, bytes]:
        del plaintext
        raise ApplicationError("INTERNAL_ERROR")

    def open(self, nonce: bytes, ciphertext: bytes) -> str:
        del nonce, ciphertext
        raise ApplicationError("INTERNAL_ERROR")


class ShippingCipher:
    """Seal and open the stored address; a failed open is an integrity error."""

    def __init__(self, cipher: AesGcmCipher | UnavailableCipher) -> None:
        self._cipher = cipher

    def seal(self, address: Mapping[str, Any]) -> bytes:
        payload = json.dumps(_normalise(address), sort_keys=True, separators=(",", ":"))
        nonce, ciphertext = self._cipher.seal(payload)
        return nonce + ciphertext

    def open(self, blob: bytes) -> dict[str, str]:
        if len(blob) <= NONCE_BYTES:
            raise ApplicationError("INTEGRITY_ERROR")
        try:
            plaintext = self._cipher.open(blob[:NONCE_BYTES], blob[NONCE_BYTES:])
        except DecryptionError:
            raise ApplicationError("INTEGRITY_ERROR") from None
        value = json.loads(plaintext)
        if not isinstance(value, dict):
            raise ApplicationError("INTEGRITY_ERROR")
        return {key: str(item) for key, item in value.items()}
