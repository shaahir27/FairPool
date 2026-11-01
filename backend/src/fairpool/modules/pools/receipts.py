"""Entry receipts: Ed25519 signing over the stored database timestamp (fairness-and-hashing.md §6).

The receipt payload is the canonical object ``{commitment, entry_id, pool_id,
received_at, v}``; the signature covers its canonical JSON bytes, base64url
without padding. The private seed comes from ``RECEIPT_SIGNING_KEY`` only: it is
never returned, logged or placed in any payload (I14). The public key served at
``GET /api/v1/public/keys`` is the raw 32-byte Ed25519 public key, base64url.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import EntryReceipt, PoolEntry
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import (
    ed25519_public_key,
    receipt_payload,
    sign_ed25519,
)

#: Wire format of timestamps inside hashed data (fairness-and-hashing.md §1).
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def signing_seed(secret_value: str) -> bytes:
    """Decode ``RECEIPT_SIGNING_KEY`` (base64url) into the 32-byte Ed25519 seed.

    A malformed key is an operational failure (500), never a fallback and never
    a detail that reaches a client or a log.
    """
    try:
        raw = base64.urlsafe_b64decode(secret_value + "=" * (-len(secret_value) % 4))
    except (binascii.Error, ValueError):
        raise ApplicationError("INTERNAL_ERROR") from None
    if len(raw) != 32:
        raise ApplicationError("INTERNAL_ERROR")
    return raw


def public_key_b64url(seed: bytes) -> str:
    """The raw 32-byte public key, base64url without padding."""
    return ed25519_public_key(seed)


def format_received_at(value: datetime) -> str:
    """UTC text of a stored timestamp in the signed format (verify-my-place parity)."""
    if value.tzinfo is None:
        raise ApplicationError("INTERNAL_ERROR")
    return value.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def build_receipt(
    seed: bytes,
    *,
    pool_id: str,
    entry_id: str,
    commitment: str,
    salt_hex: str,
    request_hash: str,
    received_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(payload, receipt)`` signed over the timestamp that is stored.

    The caller stores ``received_at`` on ``pool_entries.received_at`` and
    ``entry_receipts.signed_at`` and signs the identical text, so a signature
    always verifies against the row it describes (CR-3).
    """
    payload = receipt_payload(pool_id, entry_id, commitment, format_received_at(received_at))
    signature = sign_ed25519(payload, seed)
    receipt = {
        "payload": payload,
        "salt_hex": salt_hex,
        "request_hash": request_hash,
        "signature": signature,
    }
    return payload, receipt


async def receipt_for_entry(session: AsyncSession, entry: PoolEntry) -> dict[str, Any]:
    """Rebuild the stored receipt body for an entry (replays and existing-entry joins).

    An entry without its receipt row is an integrity break: never an invented
    receipt (``INTEGRITY_ERROR``).
    """
    stored = await session.scalar(select(EntryReceipt).where(EntryReceipt.entry_id == entry.id))
    if stored is None:
        raise ApplicationError("INTEGRITY_ERROR")
    payload = receipt_payload(
        str(entry.pool_id),
        str(entry.id),
        str(stored.commitment),
        format_received_at(entry.received_at),
    )
    return {
        "payload": payload,
        "salt_hex": str(stored.salt),
        "request_hash": entry.request_hash,
        "signature": stored.signature,
    }
