"""Fixture-backed merchant directory fake."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid5

from fairpool.ports import AsyncSession, PayeeRef

_NAMESPACE = UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")

DEFAULT_PAYEE = PayeeRef(
    merchant_id=uuid5(_NAMESPACE, "fairpool/fixture/v1/payee-merchant"),
    display_name="Demo Merchant",
    payee_email="payee@example.test",
    paypal_merchant_id=None,
    onboarding_status="DEMO",
)


@dataclass(frozen=True)
class DirectoryCall:
    merchant_id: UUID


class FakeMerchantDirectory:
    """Returns payees from a fixed table."""

    def __init__(self, *, payees: Mapping[UUID, PayeeRef] | None = None) -> None:
        self.payees = {DEFAULT_PAYEE.merchant_id: DEFAULT_PAYEE} if payees is None else dict(payees)
        self.calls: list[DirectoryCall] = []

    async def get_payee(self, session: AsyncSession, merchant_id: UUID) -> PayeeRef:
        self.calls.append(DirectoryCall(merchant_id=merchant_id))
        try:
            return self.payees[merchant_id]
        except KeyError:
            raise KeyError(f"unknown merchant: {merchant_id}") from None
