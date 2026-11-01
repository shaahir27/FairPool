"""The real ``MerchantAuth`` (``domain-ports.md`` section 6, merchant identity).

Member A's merchant routes ask this service for the principal and then check the
scope and the lot's award owner; no route reads merchant keys itself. Phase 4 needs
the session path only: the merchant console sends the buyer session cookie, so a
session user with a ``merchants`` row is a merchant and one without it is not.

The API-key path belongs to Phase 7 (``merchant_api_keys``, INT-9 / T07B..), where
the key format, scopes and HMAC storage are defined. Until then it raises
``NotEnabled`` rather than guessing a key format or a scope set.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant
from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import NotEnabled
from fairpool.ports import MerchantPrincipal

#: What a merchant's own session may do: the whole console, no key scopes involved.
#: The names match the keys' scopes in ``api.md`` section 4.3 so a Phase 7 key can
#: reuse them without a second vocabulary.
SESSION_SCOPES: Final[frozenset[str]] = frozenset(
    {
        "lots:read",
        "bids:read",
        "bids:write",
        "fulfillment:read",
        "shipments:write",
        "manifest:read",
    }
)


class PostgresMerchantAuth:
    """Implements the ``MerchantAuth`` port's session path."""

    async def from_session(self, session: AsyncSession, user_id: UUID) -> MerchantPrincipal:
        merchant = await session.scalar(select(Merchant).where(Merchant.user_id == user_id))
        if merchant is None:
            # 403 FORBIDDEN is the allowlisted answer for "not a merchant"; the
            # fake's MERCHANT_NOT_FOUND is a test-only code (config-and-errors.md).
            raise ApplicationError("FORBIDDEN")
        return MerchantPrincipal(merchant_id=merchant.id, scopes=SESSION_SCOPES, via="session")

    async def from_api_key(self, session: AsyncSession, bearer: str) -> MerchantPrincipal:
        """Phase 7 owns merchant API keys; until then this path is closed."""
        del session, bearer
        raise NotEnabled()


__all__ = ["PostgresMerchantAuth", "SESSION_SCOPES"]
