"""Merchant API keys: shown once, stored only as an HMAC (T06A07, INT-9).

Contract: ``db-schema.md`` ``merchant_api_keys``, ``api.md`` section 4.2 (the three
session endpoints) and section 4.3 (what a key may then call), and ``domain-ports.md``
section 6: Member A's merchant routes ask ``MerchantAuth`` for the principal and check the
scope themselves. Nothing outside this module and ``merchants/auth.py`` reads a key row,
and nothing here ever returns a stored hash.

The format is ``fpm_<8 characters>_<43 base64url characters>``. The prefix is the public
identifier that ``GET /merchant/api-keys`` shows an operator; the secret exists only in
the create response. Looking a key up by prefix and comparing its HMAC, rather than
scanning every row's hash, is what keeps the check constant-time per merchant and lets a
revoked key be refused without deleting the row it is recorded in.

A key is not a second login: it carries only the scopes it was created with, and creating
one requires the merchant's three attestations to be accepted (``api.md`` section 4.2),
because a bot must not be able to bid for a merchant that has not accepted the rules.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import logging
import secrets
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant, MerchantApiKey
from fairpool.domain.errors import ApplicationError
from fairpool.modules.merchants.profile import ATTESTATION_KEYS
from fairpool.ports import AuditLog, Clock

logger: Final[logging.Logger] = logging.getLogger("fairpool.merchants.keys")

#: The scope vocabulary of ``db-schema.md``'s ``merchant_api_keys.scopes``.
SCOPES: Final[frozenset[str]] = frozenset(
    {
        "lots:read",
        "bids:read",
        "bids:write",
        "fulfillment:read",
        "shipments:write",
        "manifest:read",
    }
)

KEY_PREFIX: Final[str] = "fpm"
PREFIX_CHARS: Final[int] = 8
SECRET_BYTES: Final[int] = 32


def hash_key(hmac_key: str, key: str) -> str:
    """HMAC-SHA256 of the full key under ``HMAC_KEY``; the key itself is never stored."""
    return hmac_lib.new(hmac_key.encode(), key.encode(), hashlib.sha256).hexdigest()


def matches(hmac_key: str, key: str, stored_hash: str) -> bool:
    """A constant-time comparison of the derived hash against the stored one."""
    return hmac_lib.compare_digest(hash_key(hmac_key, key), stored_hash)


def _new_key() -> tuple[str, str, str]:
    """``(prefix, secret, full key)``: 8 identifier characters and 43 base64url ones."""
    prefix = secrets.token_hex(PREFIX_CHARS // 2)
    secret = secrets.token_urlsafe(SECRET_BYTES)[:43]
    return prefix, secret, f"{KEY_PREFIX}_{prefix}_{secret}"


class MerchantApiKeys:
    """Create, list and revoke one merchant's keys."""

    def __init__(self, *, clock: Clock, audit: AuditLog, hmac_key: str) -> None:
        self.clock = clock
        self.audit = audit
        self.hmac_key = hmac_key

    async def create(
        self, session: AsyncSession, *, merchant: Merchant, name: str, scopes: list[str]
    ) -> tuple[MerchantApiKey, str]:
        """Issue a key and return it once, alongside the row that holds only its hash."""
        if not name.strip() or len(name) > 120:
            raise ApplicationError("VALIDATION_ERROR")
        if not scopes or any(scope not in SCOPES for scope in set(scopes)):
            raise ApplicationError("VALIDATION_ERROR")
        if not self._attested(merchant):
            # The row exists (require_merchant checked), so this is the second half of
            # the gate: no key for a merchant that has not accepted the attestations.
            raise ApplicationError("FORBIDDEN")

        granted = sorted(set(scopes))
        for _attempt in range(3):
            prefix, _secret, full = _new_key()
            if await session.scalar(
                select(MerchantApiKey.id).where(MerchantApiKey.key_prefix == prefix)
            ):
                continue
            row = MerchantApiKey(
                id=uuid4(),
                merchant_id=merchant.id,
                name=name,
                key_prefix=prefix,
                key_hash=hash_key(self.hmac_key, full),
                scopes=granted,
            )
            session.add(row)
            await session.flush()
            await self.audit.append(
                session,
                actor=str(merchant.user_id),
                action="merchant_api_key.created",
                subject_type="merchant_api_key",
                subject_id=str(row.id),
                payload={
                    "merchant_id": str(merchant.id),
                    "name": name,
                    "key_prefix": prefix,
                    "scopes": granted,
                },
            )
            logger.info("merchant key created merchant_id=%s key_id=%s", merchant.id, row.id)
            return row, full
        raise ApplicationError("INTERNAL_ERROR")

    async def list(self, session: AsyncSession, *, merchant_id: UUID) -> list[MerchantApiKey]:
        return list(
            await session.scalars(
                select(MerchantApiKey)
                .where(MerchantApiKey.merchant_id == merchant_id)
                .order_by(MerchantApiKey.created_at, MerchantApiKey.id)
            )
        )

    async def revoke(
        self, session: AsyncSession, *, merchant: Merchant, key_id: UUID
    ) -> MerchantApiKey:
        """Mark the key revoked; the row stays so the audit trail keeps its subject."""
        row = await session.scalar(
            select(MerchantApiKey)
            .where(MerchantApiKey.id == key_id, MerchantApiKey.merchant_id == merchant.id)
            .with_for_update()
        )
        if row is None:
            # Another merchant's key is not there: never a 403 that discloses it (I11).
            raise ApplicationError("NOT_FOUND")
        if row.revoked_at is None:
            row.revoked_at = await self.clock.db_now(session)
            await session.flush()
            await self.audit.append(
                session,
                actor=str(merchant.user_id),
                action="merchant_api_key.revoked",
                subject_type="merchant_api_key",
                subject_id=str(row.id),
                payload={"merchant_id": str(merchant.id), "key_prefix": row.key_prefix},
            )
        return row

    @staticmethod
    def _attested(merchant: Merchant) -> bool:
        values: dict[str, Any] = dict(merchant.attestations or {})
        return all(
            isinstance(values.get(key), dict) and values[key].get("accepted") is True
            for key in ATTESTATION_KEYS
        )
