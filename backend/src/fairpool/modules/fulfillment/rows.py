"""``GET .../fulfillment`` rows: CAPTURED orders only, address opened here (N14).

The decrypted address exists only in the returned dict and the CSV bytes; nothing
in this module logs, audits or persists it. A captured row without its stored
address or its completed capture is an ``INTEGRITY_ERROR``: the merchant cannot
ship from a silently incomplete row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import BuyerOrder, PayPalCapture
from fairpool.db.models.enums import BuyerOrderStatus
from fairpool.domain.errors import ApplicationError

if TYPE_CHECKING:
    from fairpool.modules.checkout.shipping import ShippingCipher


async def fulfillment_rows(
    session: AsyncSession, *, lot_id: UUID, cipher: ShippingCipher
) -> list[dict[str, Any]]:
    orders = (
        await session.execute(
            select(
                BuyerOrder.id,
                BuyerOrder.total_cents,
                BuyerOrder.breakdown,
                BuyerOrder.shipping_enc,
            )
            .where(
                BuyerOrder.lot_id == lot_id,
                BuyerOrder.status == BuyerOrderStatus.CAPTURED,
            )
            .order_by(BuyerOrder.created_at, BuyerOrder.id)
        )
    ).all()
    if not orders:
        return []
    captures: dict[UUID, str] = {}
    for buyer_order_id, capture_id in (
        await session.execute(
            select(PayPalCapture.buyer_order_id, PayPalCapture.paypal_capture_id)
            .join(BuyerOrder, BuyerOrder.id == PayPalCapture.buyer_order_id)
            .where(
                BuyerOrder.lot_id == lot_id,
                BuyerOrder.status == BuyerOrderStatus.CAPTURED,
                PayPalCapture.status == "COMPLETED",
            )
            .order_by(PayPalCapture.created_at, PayPalCapture.paypal_capture_id)
        )
    ).all():
        captures[buyer_order_id] = str(capture_id)

    rows: list[dict[str, Any]] = []
    for order_id, total_cents, breakdown, shipping_enc in orders:
        if shipping_enc is None or order_id not in captures:
            raise ApplicationError("INTEGRITY_ERROR")
        address = cipher.open(bytes(shipping_enc))
        values = breakdown if isinstance(breakdown, dict) else {}
        try:
            item_cents = int(values["item_cents"])
            shipping_cents = int(values["shipping_cents"])
            tax_cents = int(values["tax_cents"])
        except (KeyError, TypeError, ValueError):
            raise ApplicationError("INTEGRITY_ERROR") from None
        rows.append(
            {
                "buyer_order_id": order_id,
                "name": address["name"],
                "line1": address["line1"],
                "line2": address.get("line2") or None,
                "city": address["city"],
                "region": address["region"],
                "postal_code": address["postal_code"],
                "country_code": address["country_code"],
                "item_cents": item_cents,
                "shipping_cents": shipping_cents,
                "tax_cents": tax_cents,
                "total_cents": int(total_cents),
                "paypal_capture_id": captures[order_id],
            }
        )
    return rows


__all__ = ["fulfillment_rows"]
