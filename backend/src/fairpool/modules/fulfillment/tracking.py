"""``shipments.submit``: one tracker per recorded shipment, through the adapter.

The handler is idempotent: it reads the rows this lot has not submitted yet, so a
retry after a partial failure re-submits the remainder. A provider failure is written
to the row (``FAILED`` plus the debug ID) and never raised; the worker must not fail a
job over a shipment, and the merchant can correct the row and resubmit, which is why a
``FAILED`` row is read again rather than treated as terminal. Tracking numbers are
never logged (they are shipping data).
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import Shipment
from fairpool.domain.payments import PaymentError, TrackerItem, TrackerResult


class TrackerGateway(Protocol):
    async def add_trackers(self, items: list[TrackerItem]) -> list[TrackerResult]: ...


_SHIPMENTS = text(
    """
    SELECT DISTINCT ON (s.id)
           s.id, s.carrier, s.tracking_number,
           c.paypal_capture_id,
           COALESCE(a.paypal_order_id, po.paypal_order_id) AS paypal_order_id
    FROM shipments s
    JOIN buyer_orders bo ON bo.id = s.buyer_order_id
    LEFT JOIN paypal_captures c
           ON c.buyer_order_id = s.buyer_order_id AND c.status = 'COMPLETED'
    LEFT JOIN paypal_authorizations a ON a.paypal_auth_id = c.paypal_auth_id
    LEFT JOIN LATERAL (
        SELECT paypal_order_id FROM paypal_orders
        WHERE buyer_order_id = s.buyer_order_id
        ORDER BY attempt DESC LIMIT 1
    ) po ON true
    WHERE s.lot_id = :lot
      AND (s.paypal_tracker_status IS NULL OR s.paypal_tracker_status = 'FAILED')
    ORDER BY s.id, c.created_at DESC NULLS LAST, c.paypal_capture_id DESC
    """
)


class ShipmentTracking:
    """The ``shipments.submit`` handler registered by ``wiring.worker_handlers``."""

    def __init__(self, *, gateway: TrackerGateway, enabled: bool) -> None:
        self.gateway = gateway
        self.enabled = enabled

    async def submit(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        lot_id = UUID(str(payload["lot_id"]))
        rows = (await session.execute(_SHIPMENTS, {"lot": lot_id})).mappings().all()
        if not rows:
            return
        items: list[TrackerItem] = []
        shipment_for: dict[str, UUID] = {}
        for row in rows:
            if row["paypal_order_id"] is None or row["paypal_capture_id"] is None:
                await self._mark(session, row["id"], "FAILED", None)
                continue
            item = TrackerItem(
                paypal_order_id=str(row["paypal_order_id"]),
                capture_id=str(row["paypal_capture_id"]),
                carrier=str(row["carrier"]),
                tracking_number=str(row["tracking_number"]),
            )
            items.append(item)
            shipment_for[item.capture_id] = row["id"]
        if not items:
            return
        try:
            results = await self.gateway.add_trackers(items)
        except PaymentError as exc:
            for item in items:
                await self._mark(session, shipment_for[item.capture_id], "FAILED", exc.debug_id)
            return
        returned = {result.capture_id: result for result in results}
        for item in items:
            result = returned.get(item.capture_id)
            ok = result is not None and result.ok
            await self._mark(
                session,
                shipment_for[item.capture_id],
                "SUBMITTED" if ok else "FAILED",
                None if result is None else result.debug_id,
            )

    async def _mark(
        self, session: AsyncSession, shipment_id: UUID, status: str, debug_id: str | None
    ) -> None:
        await session.execute(
            update(Shipment)
            .where(Shipment.id == shipment_id)
            .values(paypal_tracker_status=status, paypal_debug_id=debug_id)
        )


__all__ = ["ShipmentTracking", "TrackerGateway"]
