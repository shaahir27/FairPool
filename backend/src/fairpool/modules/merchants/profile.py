"""Merchant profile and the three attestations (T05A06; FR-AU-01, FR-AU-03).

Under ``PAYMENT_ROUTER=single_seller`` a new profile is stamped ``DEMO``: the
payee is the stand-in sandbox seller, so Router A onboarding is not offered as a
working action (DEP-4). Attestation timestamps come from the database clock and
an already-recorded acceptance keeps its original timestamp.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant
from fairpool.db.models.enums import MerchantOnboarding
from fairpool.domain.errors import ApplicationError
from fairpool.ports import Clock

ATTESTATION_KEYS: tuple[str, ...] = (
    "inventory_reserved",
    "map_compliance",
    "delivery_terms_accurate",
)


def _accepted(value: Any) -> bool:
    """An attestation is a yes or a no, never a truthy string.

    ``db-schema.md`` stores ``{"at": "iso", "accepted": true}``; anything that is
    not a boolean is a client bug and must not be recorded as a merchant's word.
    """
    raw = value.get("accepted") if isinstance(value, Mapping) else value
    if not isinstance(raw, bool):
        raise ApplicationError("VALIDATION_ERROR")
    return raw


class MerchantProfileService:
    def __init__(self, *, clock: Clock, demo: bool) -> None:
        self.clock = clock
        self.demo = demo

    async def upsert(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        display_name: str,
        payee_email: str | None,
        paypal_merchant_id: str | None,
        attestations: Mapping[str, Any],
        present: Collection[str] | None = None,
    ) -> Merchant:
        """Create or update the merchant row, stamping each acceptance once.

        ``present`` is the request's ``model_fields_set``: a field the client did
        not send keeps its stored value, while an explicitly sent null clears it.
        ``None`` means every value passed here is an update (direct callers).
        """
        now = await self.clock.db_now(session)
        stamp = now.isoformat()
        merchant = await session.scalar(select(Merchant).where(Merchant.user_id == user_id))
        updates_attestations = present is None or "attestations" in present
        merged: dict[str, Any] = dict(merchant.attestations) if merchant is not None else {}
        if updates_attestations:
            for key, value in attestations.items():
                if key not in ATTESTATION_KEYS:
                    raise ApplicationError("VALIDATION_ERROR")
                accepted = _accepted(value)
                previous_at: str | None = None
                previous = merged.get(key)
                if isinstance(previous, Mapping) and previous.get("accepted") is True:
                    at_value = previous.get("at")
                    if isinstance(at_value, str):
                        previous_at = at_value
                merged[key] = {"at": previous_at or stamp, "accepted": accepted}
        if merchant is None:
            merchant = Merchant(
                id=uuid4(),
                user_id=user_id,
                display_name=display_name,
                onboarding_status=(
                    MerchantOnboarding.DEMO if self.demo else MerchantOnboarding.NONE
                ),
                payee_email=payee_email,
                paypal_merchant_id=paypal_merchant_id,
                attestations=merged,
            )
            session.add(merchant)
        else:
            merchant.display_name = display_name
            if present is None or "payee_email" in present:
                merchant.payee_email = payee_email
            if present is None or "paypal_merchant_id" in present:
                merchant.paypal_merchant_id = paypal_merchant_id
            if updates_attestations:
                merchant.attestations = merged
        await session.flush()
        return merchant
