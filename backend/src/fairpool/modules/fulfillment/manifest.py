"""The verification manifest: PayPal order and capture IDs, amounts, no buyer data.

INT-6 lets a merchant's AI client check the lot's captured orders against PayPal
one order ID at a time. The manifest therefore carries only what such a check
needs: the order ID, the capture ID, the amount and when it was recorded. Buyer
names, addresses and even the FairPool buyer-order id stay out.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError

if TYPE_CHECKING:
    from fairpool.modules.fulfillment.service import AwardedLot

#: api.md section 4.2 fixes this sentence verbatim; the merchant UI renders it as-is.
HOW_TO_VERIFY = (
    "In your AI client connected to the PayPal MCP server, look up each order ID "
    "with a read-only get-order tool and confirm the capture amounts add up to "
    "expected_captured_total_cents."
)

_ITEMS = text(
    """
    SELECT DISTINCT ON (bo.id)
           c.paypal_capture_id,
           c.amount_cents,
           c.created_at,
           COALESCE(a.paypal_order_id, po.paypal_order_id) AS paypal_order_id
    FROM buyer_orders bo
    JOIN paypal_captures c
      ON c.buyer_order_id = bo.id AND c.status = 'COMPLETED'
    LEFT JOIN paypal_authorizations a ON a.paypal_auth_id = c.paypal_auth_id
    LEFT JOIN LATERAL (
        SELECT paypal_order_id FROM paypal_orders
        WHERE buyer_order_id = bo.id
        ORDER BY attempt DESC LIMIT 1
    ) po ON true
    WHERE bo.lot_id = :lot AND bo.status = 'CAPTURED'
    ORDER BY bo.id, c.created_at DESC, c.paypal_capture_id DESC
    """
)


async def manifest_items(session: AsyncSession, lot_id: UUID) -> list[dict[str, Any]]:
    rows = (await session.execute(_ITEMS, {"lot": lot_id})).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        if row["paypal_order_id"] is None:
            # A captured order with no PayPal order identity cannot be verified.
            raise ApplicationError("INTEGRITY_ERROR")
        captured_at = row["created_at"]
        if not isinstance(captured_at, datetime):
            raise ApplicationError("INTEGRITY_ERROR")
        items.append(
            {
                "paypal_order_id": str(row["paypal_order_id"]),
                "paypal_capture_id": str(row["paypal_capture_id"]),
                "amount_cents": int(row["amount_cents"]),
                "captured_at": captured_at,
            }
        )
    items.sort(key=lambda item: (item["captured_at"], item["paypal_capture_id"]))
    return items


async def verification_manifest(session: AsyncSession, *, awarded: AwardedLot) -> dict[str, Any]:
    items = await manifest_items(session, awarded.id)
    return {
        "lot_id": awarded.id,
        "currency": "USD",
        "funded": awarded.funded,
        "expected_captured_total_cents": sum(item["amount_cents"] for item in items),
        "items": items,
        "how_to_verify": HOW_TO_VERIFY,
    }


__all__ = ["HOW_TO_VERIFY", "manifest_items", "verification_manifest"]
