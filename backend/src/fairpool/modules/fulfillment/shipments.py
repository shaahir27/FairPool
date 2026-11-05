"""``POST .../shipments``: validate each row, record once, enqueue the tracker job.

A row is valid only for a CAPTURED order of this lot with a carrier and a tracking
number; invalid rows are reported per row (``SHIPMENT_INVALID``) instead of failing
the batch. The insert is ``ON CONFLICT (buyer_order_id) DO NOTHING`` so a merchant
retrying the same shipment gets the recorded answer rather than a duplicate, and
the database trigger ``trg_shipments_funded_only`` remains the last word on the
funded-lot rule (FR-IG-08).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import BuyerOrder, Shipment
from fairpool.db.models.enums import BuyerOrderStatus

if TYPE_CHECKING:
    from fairpool.modules.fulfillment.service import AwardedLot
    from fairpool.ports import AuditLog, Clock, JobQueue


class ShipmentRecorder:
    def __init__(
        self, *, audit: AuditLog, jobs: JobQueue, clock: Clock, tracking_enabled: bool
    ) -> None:
        self.audit = audit
        self.jobs = jobs
        self.clock = clock
        self.tracking_enabled = tracking_enabled

    async def record(
        self,
        session: AsyncSession,
        *,
        awarded: AwardedLot,
        merchant_id: UUID,
        shipments: list[dict[str, Any]],
        actor: str,
    ) -> dict[str, Any]:
        now = await self.clock.db_now(session)
        requested = [UUID(str(item["buyer_order_id"])) for item in shipments]
        valid = set(
            (
                await session.scalars(
                    select(BuyerOrder.id).where(
                        BuyerOrder.lot_id == awarded.id,
                        BuyerOrder.status == BuyerOrderStatus.CAPTURED,
                        BuyerOrder.id.in_(requested),
                    )
                )
            ).all()
        )
        existing = {
            row[0]: row[1]
            for row in (
                await session.execute(
                    select(Shipment.buyer_order_id, Shipment.paypal_tracker_status).where(
                        Shipment.buyer_order_id.in_(requested)
                    )
                )
            ).all()
        }

        rows: list[dict[str, Any]] = []
        accepted = 0
        inserted_any = False
        seen: set[UUID] = set()
        for item, order_id in zip(shipments, requested, strict=True):
            carrier = str(item.get("carrier") or "").strip()
            tracking = str(item.get("tracking_number") or "").strip()
            if not carrier or not tracking or order_id not in valid or order_id in seen:
                rows.append(
                    {
                        "buyer_order_id": order_id,
                        "status": "INVALID",
                        "paypal_tracker_status": None,
                    }
                )
                continue
            seen.add(order_id)
            if order_id in existing:
                rows.append(
                    {
                        "buyer_order_id": order_id,
                        "status": "RECORDED",
                        "paypal_tracker_status": existing[order_id],
                    }
                )
                accepted += 1
                continue
            tracker_status = None if self.tracking_enabled else "SKIPPED"
            shipment_id = await session.scalar(
                pg_insert(Shipment)
                .values(
                    id=uuid4(),
                    lot_id=awarded.id,
                    buyer_order_id=order_id,
                    merchant_id=merchant_id,
                    carrier=carrier,
                    tracking_number=tracking,
                    shipped_at=now,
                    paypal_tracker_status=tracker_status,
                )
                .on_conflict_do_nothing(index_elements=["buyer_order_id"])
                .returning(Shipment.id)
            )
            if shipment_id is None:
                # Lost a race with another request holding the same buyer order.
                tracker_status = await session.scalar(
                    select(Shipment.paypal_tracker_status).where(
                        Shipment.buyer_order_id == order_id
                    )
                )
            else:
                inserted_any = True
                await self.audit.append(
                    session,
                    actor=actor,
                    action="shipment.recorded",
                    subject_type="shipment",
                    subject_id=str(shipment_id),
                    payload={
                        "lot_id": str(awarded.id),
                        "buyer_order_id": str(order_id),
                        "carrier": carrier,
                    },
                )
            rows.append(
                {
                    "buyer_order_id": order_id,
                    "status": "RECORDED",
                    "paypal_tracker_status": tracker_status,
                }
            )
            accepted += 1

        if inserted_any and self.tracking_enabled:
            await self.jobs.enqueue(
                session,
                "shipments.submit",
                {"lot_id": str(awarded.id)},
                run_at=now,
                concurrency_key=f"lot:{awarded.id}",
                dedupe_key=f"shipments:{awarded.id}",
            )
        return {"accepted": accepted, "rows": rows}


__all__ = ["ShipmentRecorder"]
