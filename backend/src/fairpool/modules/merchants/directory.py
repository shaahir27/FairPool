"""The real ``MerchantDirectory`` (``domain-ports.md`` section 4.2; T04X01 wiring).

Checkout asks this service for the payee it may route money to, and it reads the
``merchants`` row the merchant actually owns. Under ``PAYMENT_ROUTER=single_seller``
the plan routes every lot to the one stand-in seller, so the payee fields resolve to
``SINGLE_SELLER_EMAIL`` while the merchant's own display name stays on every screen
carrying the fallback label (DEP-4). Reading the row here rather than in each
handler is what keeps the router decision in one place.

``calls`` records which merchant ids were looked up. IT-4 asserts on it to prove the
real directory is the one wired into checkout, not the fixture fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant
from fairpool.domain.errors import ApplicationError
from fairpool.ports import PayeeRef

#: The router names whose payee is the configured stand-in seller (N8, DEP-4).
SINGLE_SELLER: str = "single_seller"


@dataclass(frozen=True)
class PayeeCall:
    """One lookup, for tests: ids only, never a payee address."""

    merchant_id: UUID


class PostgresMerchantDirectory:
    """Implements the ``MerchantDirectory`` port over the ``merchants`` table."""

    def __init__(
        self,
        *,
        payment_router: str,
        single_seller_email: str | None,
        single_seller_merchant_id: str | None = None,
    ) -> None:
        self.payment_router = payment_router
        self.single_seller_email = single_seller_email
        self.single_seller_merchant_id = single_seller_merchant_id or None
        self.calls: list[PayeeCall] = []

    async def get_payee(self, session: AsyncSession, merchant_id: UUID) -> PayeeRef:
        self.calls.append(PayeeCall(merchant_id=merchant_id))
        merchant = await session.scalar(select(Merchant).where(Merchant.id == merchant_id))
        if merchant is None:
            # An award naming a merchant that does not exist cannot be paid.
            raise ApplicationError("NOT_FOUND")
        if self.payment_router == SINGLE_SELLER:
            return PayeeRef(
                merchant_id=merchant.id,
                display_name=str(merchant.display_name),
                payee_email=self.single_seller_email,
                paypal_merchant_id=self.single_seller_merchant_id,
                onboarding_status=str(merchant.onboarding_status),
            )
        return PayeeRef(
            merchant_id=merchant.id,
            display_name=str(merchant.display_name),
            payee_email=None if merchant.payee_email is None else str(merchant.payee_email),
            paypal_merchant_id=(
                None if merchant.paypal_merchant_id is None else str(merchant.paypal_merchant_id)
            ),
            onboarding_status=str(merchant.onboarding_status),
        )


__all__ = ["PayeeCall", "PostgresMerchantDirectory", "SINGLE_SELLER"]
