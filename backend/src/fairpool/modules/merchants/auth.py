"""The real ``MerchantAuth`` (``domain-ports.md`` section 6, merchant identity).

Member A's merchant routes ask this service for the principal and then check the
scope and the lot's award owner; no route reads merchant keys itself. The session path
is the merchant console: a session user with a ``merchants`` row is a merchant and one
without it is not. The key path is T06A07: it resolves a ``fpm_`` bearer to the same
principal, carrying only the scopes the key was created with.

Both paths return ``MerchantPrincipal`` and differ only in ``via``, so a route that
checks a scope cannot have to know how the caller proved who they are.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant, MerchantApiKey
from fairpool.domain.errors import ApplicationError
from fairpool.modules.merchants.api_keys import (
    KEY_PREFIX,
    PREFIX_CHARS,
    SCOPES,
    matches,
)
from fairpool.ports import Clock, MerchantPrincipal


class PostgresMerchantAuth:
    """Implements the ``MerchantAuth`` port for sessions and for API keys."""

    def __init__(self, *, clock: Clock, hmac_key: str) -> None:
        self.clock = clock
        self.hmac_key = hmac_key

    async def from_session(self, session: AsyncSession, user_id: UUID) -> MerchantPrincipal:
        merchant = await session.scalar(select(Merchant).where(Merchant.user_id == user_id))
        if merchant is None:
            # 403 FORBIDDEN is the allowlisted answer for "not a merchant"; the
            # fake's MERCHANT_NOT_FOUND is a test-only code (config-and-errors.md).
            raise ApplicationError("FORBIDDEN")
        # A session is the console: the whole scope vocabulary, none of it granted by a key.
        return MerchantPrincipal(merchant_id=merchant.id, scopes=SCOPES, via="session")

    async def from_api_key(self, session: AsyncSession, bearer: str) -> MerchantPrincipal:
        """Resolve a ``fpm_<prefix>_<secret>`` key, or refuse without saying which half.

        Malformed, unknown, revoked and mismatched all answer ``API_KEY_INVALID``: the
        difference would tell an attacker that a prefix exists, and the prefix is already
        on the merchant's own list screen (I11). The stored hash is compared, never read
        back out (I14).
        """
        prefix, secret = _split_key(bearer)
        if prefix is None or secret is None:
            raise ApplicationError("API_KEY_INVALID")
        row = await session.scalar(
            select(MerchantApiKey).where(MerchantApiKey.key_prefix == prefix).with_for_update()
        )
        if row is None or not matches(self.hmac_key, bearer, row.key_hash):
            raise ApplicationError("API_KEY_INVALID")
        if row.revoked_at is not None:
            raise ApplicationError("API_KEY_INVALID")
        row.last_used_at = await self.clock.db_now(session)
        await session.flush()
        return MerchantPrincipal(
            merchant_id=row.merchant_id, scopes=frozenset(row.scopes), via="api_key"
        )


def _split_key(bearer: str) -> tuple[str | None, str | None]:
    """``(prefix, secret)`` from ``fpm_<8 chars>_<secret>``, or ``(None, None)``."""
    if not bearer.startswith(f"{KEY_PREFIX}_"):
        return None, None
    parts = bearer[len(KEY_PREFIX) + 1 :].split("_", 1)
    if len(parts) != 2 or len(parts[0]) != PREFIX_CHARS or not parts[1]:
        return None, None
    return parts[0], parts[1]


def require_scope(principal: MerchantPrincipal, scope: str) -> None:
    """The scope gate ``domain-ports.md`` section 6 leaves to the route: a key that
    resolves but was not granted this operation answers ``403 API_KEY_SCOPE``.

    Kept here rather than copied into each route so a session and a key are measured
    against the same vocabulary, and the answer is the one code in the allowlist.
    """
    if scope not in principal.scopes:
        raise ApplicationError("API_KEY_SCOPE")


__all__ = ["PostgresMerchantAuth", "require_scope"]
