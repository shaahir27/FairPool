"""``GET .../progress``: one grouped count over the lot's buyer orders (api.md 4.2).

The counts are zero-filled so a screen never has to distinguish "not started" from
"missing". No buyer identity is read: the response is counts, the lot's stored
deadlines and the badge labels. ``captures_completed`` comes from the ledger, not
from order status, because only a completed capture is money (I4, I5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.paypal import routers as paypal_routers
from fairpool.db.models.checkout import BuyerOrder
from fairpool.db.models.enums import BuyerOrderStatus
from fairpool.modules.checkout.funding import AUTHORIZED_STATES
from fairpool.modules.checkout.sdk import FALLBACK_LABEL

if TYPE_CHECKING:
    from fairpool.modules.fulfillment.service import AwardedLot
    from fairpool.ports import Ledger


def labels_for(lot: Any) -> list[str]:
    """SANDBOX plus the stand-in sentence when a fallback governs this lot (DEP-4)."""
    labels = paypal_routers.checkout_labels(str(lot.payment_router or ""))
    if str(lot.payment_router) == "single_seller" or str(lot.payment_mode) == "capture_only":
        labels.append(FALLBACK_LABEL)
    return labels


async def lot_progress(
    session: AsyncSession, *, awarded: AwardedLot, ledger: Ledger
) -> dict[str, Any]:
    counts = {status.value: 0 for status in BuyerOrderStatus}
    rows = await session.execute(
        select(BuyerOrder.status, func.count())
        .where(BuyerOrder.lot_id == awarded.id)
        .group_by(BuyerOrder.status)
    )
    for status, count in rows:
        counts[str(status)] = int(count)
    lot = awarded.lot
    return {
        "lot_id": lot.id,
        "status": str(lot.status),
        "seats": int(lot.seats),
        "moq": awarded.moq,
        # A hold is an authorized (or already captured) seat: the tracker shows this
        # against the MOQ until the capture sweep starts (design 11.6).
        "holds_placed": sum(counts[state] for state in AUTHORIZED_STATES),
        "captures_completed": await ledger.completed_capture_count(session, lot.id),
        "refills_offered": int(lot.refill_waves),
        "counts": counts,
        "fund_deadline_at": lot.fund_deadline_at,
        "labels": labels_for(lot),
    }


__all__ = ["labels_for", "lot_progress"]
