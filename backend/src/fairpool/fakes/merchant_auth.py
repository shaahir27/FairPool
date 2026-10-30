"""Bearer-token merchant authentication fake."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from fairpool.domain import hashing
from fairpool.ports import AsyncSession, MerchantPrincipal


class MerchantAuthError(ValueError):
    """Merchant authentication failure carrying the public reason code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MerchantAuthCall:
    method: str
    principal: str


class FakeMerchantAuth:
    """Looks principals up in fixed tables and rejects unknown or revoked keys."""

    def __init__(
        self,
        *,
        api_keys: Mapping[str, MerchantPrincipal] | None = None,
        sessions: Mapping[UUID, MerchantPrincipal] | None = None,
        revoked: Iterable[str] = (),
    ) -> None:
        self.api_keys = dict(api_keys or {})
        self.sessions = dict(sessions or {})
        self.revoked = set(revoked)
        self.calls: list[MerchantAuthCall] = []

    def revoke(self, bearer: str) -> None:
        self.revoked.add(bearer)

    async def from_session(
        self,
        session: AsyncSession,
        user_id: UUID,
    ) -> MerchantPrincipal:
        self.calls.append(MerchantAuthCall(method="from_session", principal=str(user_id)))
        try:
            return self.sessions[user_id]
        except KeyError:
            raise MerchantAuthError("MERCHANT_NOT_FOUND") from None

    async def from_api_key(
        self,
        session: AsyncSession,
        bearer: str,
    ) -> MerchantPrincipal:
        # Record only a digest: raw bearer tokens are credentials (INT-2).
        self.calls.append(
            MerchantAuthCall(method="from_api_key", principal=hashing.sha256_hex(bearer))
        )
        if bearer in self.revoked:
            raise MerchantAuthError("API_KEY_INVALID")
        try:
            return self.api_keys[bearer]
        except KeyError:
            raise MerchantAuthError("API_KEY_INVALID") from None
