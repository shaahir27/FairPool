"""AES-256-GCM at-rest encryption for saved payment credentials (CR-3, rule 27).

``vault-charge.md`` section 5 makes the PayPal payment token ID a credential: it
lives only in ``vault_tokens.token_ciphertext`` with a per-row nonce, keyed by
``VAULT_TOKEN_KEY``. This module is the primitive only: it holds no session,
writes no row and knows nothing about entries, so Member B's vault service can be
handed a cipher through its constructor instead of importing ``fairpool.infra``
(scaffold section 5 rule 5: the lanes meet through ports, and
``fairpool.wiring`` or the router connects the concrete implementation).

Nothing here logs a plaintext: callers must never put a decrypted value in a log
record, an audit payload or an API body (I14).
"""

from __future__ import annotations

import base64
import binascii
import secrets
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: ``(nonce, ciphertext)`` as stored in the two ``*_nonce`` / ``*_ciphertext`` columns.
SealedPair = tuple[bytes, bytes]

#: AES-GCM standard nonce length (96 bits), generated fresh per row.
NONCE_BYTES: Final[int] = 12

#: ``VAULT_TOKEN_KEY`` is 32 raw bytes, base64-encoded (config-and-errors.md §1).
KEY_BYTES: Final[int] = 32


class DecryptionError(Exception):
    """The ciphertext is not this key's, or it was tampered with.

    Carries no plaintext and no ciphertext fragment, so it is safe to catch and
    map to an error code (never a raw value in a log or a response).
    """


def key_from_config_value(value: str) -> bytes:
    """Decode ``VAULT_TOKEN_KEY`` to its 32 raw bytes; never logs the value."""
    try:
        raw = base64.b64decode(value, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DecryptionError("vault key is not valid base64") from exc
    if len(raw) != KEY_BYTES:
        raise DecryptionError("vault key must decode to 32 bytes")
    return raw


class AesGcmCipher:
    """Authenticated encryption with a per-row nonce and the vault key."""

    def __init__(self, key: bytes) -> None:
        if len(key) != KEY_BYTES:
            raise DecryptionError("vault key must be exactly 32 bytes")
        self._aesgcm = AESGCM(key)

    @classmethod
    def from_config_value(cls, value: str) -> AesGcmCipher:
        return cls(key_from_config_value(value))

    def seal(self, plaintext: str) -> SealedPair:
        """Encrypt to ``(nonce, ciphertext)``; the nonce is new for every call."""
        nonce = secrets.token_bytes(NONCE_BYTES)
        return nonce, self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    def open(self, nonce: bytes, ciphertext: bytes) -> str:
        """Decrypt a stored pair; a mismatch is ``DecryptionError``, never a guess."""
        if len(nonce) != NONCE_BYTES:
            raise DecryptionError("stored nonce must be 12 bytes")
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
            raise DecryptionError("vault ciphertext failed authentication") from exc
