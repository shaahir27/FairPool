"""Encrypted shipping address storage (N14, BD-11).

The address is collected at checkout because fulfillment needs it and sent to
PayPal only at ``PAYPAL_PAYLOAD_LEVEL >= 3``. It is written to
``buyer_orders.shipping_enc`` as a Fernet token under ``ADDRESS_ENCRYPTION_KEY``
(BD-11, config-and-errors.md), before any provider call (I9). Nothing here logs,
audits or returns a decrypted value: a plaintext address must never reach a log
record, an audit payload, a ledger fact or an API response.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from cryptography.fernet import Fernet, InvalidToken

from fairpool.domain.errors import ApplicationError

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
        if field == "line2":
            # Optional: "no apartment" arrives as None, "" or an empty string.
            normalised[field] = "" if value is None else str(value).strip()
            continue
        if value is None:
            raise ApplicationError("VALIDATION_ERROR")
        if not isinstance(value, str) or not value.strip():
            raise ApplicationError("VALIDATION_ERROR")
        normalised[field] = value.strip()
    return normalised


class ShippingCipher:
    """Fernet seal and open for the stored address (BD-11).

    A key that is not a Fernet key is kept as ``None`` rather than failing app
    construction: the modes that never store an address must still start. A
    checkout that does need the column then fails with an allowlisted code, and
    the address is never written in plaintext.
    """

    def __init__(self, key: str | None) -> None:
        self._fernet: Fernet | None
        try:
            self._fernet = Fernet(key.encode()) if key else None
        except (ValueError, TypeError):
            self._fernet = None

    def seal(self, address: Mapping[str, Any]) -> bytes:
        if self._fernet is None:
            raise ApplicationError("INTERNAL_ERROR")
        payload = json.dumps(_normalise(address), sort_keys=True, separators=(",", ":"))
        return self._fernet.encrypt(payload.encode())

    def open(self, blob: bytes) -> dict[str, str]:
        if self._fernet is None:
            raise ApplicationError("INTERNAL_ERROR")
        try:
            plaintext = self._fernet.decrypt(bytes(blob))
        except InvalidToken:
            raise ApplicationError("INTEGRITY_ERROR") from None
        value = json.loads(plaintext)
        if not isinstance(value, dict):
            raise ApplicationError("INTEGRITY_ERROR")
        return {key: str(item) for key, item in value.items()}
