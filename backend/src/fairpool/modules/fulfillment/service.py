"""Fulfillment: progress, shipping rows, shipments, manifest and verification (T08A01).

Everything here starts from the award: a lot belongs to a merchant only when
``awards.merchant_id`` says so, so an unknown lot and another merchant's lot are
the same ``404 NOT_FOUND`` (I11, PT-15). Fulfillment rows, shipments and the
manifest open only once the lot is FUNDED or CLOSED (``LOT_NOT_FUNDED``); progress
is readable while checkout is still running.

The address lives only on the buyer order, sealed under ``ADDRESS_ENCRYPTION_KEY``
(N14, BD-11). It is opened in exactly one place, :mod:`fairpool.modules.fulfillment.rows`,
and never enters a log record, an audit payload or the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Award
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError
from fairpool.modules.checkout.shipping import ShippingCipher
from fairpool.modules.fulfillment import manifest as manifest_module
from fairpool.modules.fulfillment import progress as progress_module
from fairpool.modules.fulfillment import rows as rows_module
from fairpool.modules.fulfillment import verification as verification_module
from fairpool.modules.fulfillment.shipments import ShipmentRecorder
from fairpool.ports import AuditLog, Clock, JobQueue, Ledger

#: Only a lot whose money is settled exposes addresses and shipments (I4, FR-IG-08).
FUNDED_STATUSES = frozenset({"FUNDED", "CLOSED"})


@dataclass(frozen=True)
class AwardedLot:
    """The lot and the winning merchant's MOQ, as the award froze them."""

    lot: Lot
    moq: int

    @property
    def id(self) -> UUID:
        return self.lot.id

    @property
    def status(self) -> str:
        return str(self.lot.status)

    @property
    def funded(self) -> bool:
        return self.status in FUNDED_STATUSES


class FulfillmentService:
    """The five merchant operations over one awarded lot."""

    def __init__(
        self,
        *,
        cipher: ShippingCipher,
        ledger: Ledger,
        jobs: JobQueue,
        audit: AuditLog,
        clock: Clock,
        gateway: Any,
        tracking_enabled: bool,
    ) -> None:
        self.cipher = cipher
        self.ledger = ledger
        self.gateway = gateway
        self.clock = clock
        self.recorder = ShipmentRecorder(
            audit=audit, jobs=jobs, clock=clock, tracking_enabled=tracking_enabled
        )

    async def awarded_lot(
        self, session: AsyncSession, *, lot_id: UUID, merchant_id: UUID
    ) -> AwardedLot:
        row = (
            await session.execute(
                select(Lot, Award)
                .join(Award, Award.lot_id == Lot.id)
                .where(Lot.id == lot_id, Award.merchant_id == merchant_id)
            )
        ).first()
        if row is None:
            raise ApplicationError("NOT_FOUND")
        return AwardedLot(lot=row[0], moq=int(row[1].moq))

    @staticmethod
    def require_funded(awarded: AwardedLot) -> None:
        if not awarded.funded:
            raise ApplicationError("LOT_NOT_FUNDED")

    async def progress(
        self, session: AsyncSession, *, lot_id: UUID, merchant_id: UUID
    ) -> dict[str, Any]:
        awarded = await self.awarded_lot(session, lot_id=lot_id, merchant_id=merchant_id)
        return await progress_module.lot_progress(session, awarded=awarded, ledger=self.ledger)

    async def fulfillment_rows(
        self, session: AsyncSession, *, lot_id: UUID, merchant_id: UUID
    ) -> list[dict[str, Any]]:
        awarded = await self.awarded_lot(session, lot_id=lot_id, merchant_id=merchant_id)
        self.require_funded(awarded)
        return await rows_module.fulfillment_rows(session, lot_id=awarded.id, cipher=self.cipher)

    async def record_shipments(
        self,
        session: AsyncSession,
        *,
        lot_id: UUID,
        merchant_id: UUID,
        shipments: list[dict[str, Any]],
        actor: str,
    ) -> dict[str, Any]:
        awarded = await self.awarded_lot(session, lot_id=lot_id, merchant_id=merchant_id)
        self.require_funded(awarded)
        return await self.recorder.record(
            session,
            awarded=awarded,
            merchant_id=merchant_id,
            shipments=shipments,
            actor=actor,
        )

    async def verification_manifest(
        self, session: AsyncSession, *, lot_id: UUID, merchant_id: UUID
    ) -> dict[str, Any]:
        awarded = await self.awarded_lot(session, lot_id=lot_id, merchant_id=merchant_id)
        self.require_funded(awarded)
        return await manifest_module.verification_manifest(session, awarded=awarded)

    async def verification(
        self, session: AsyncSession, *, lot_id: UUID, merchant_id: UUID
    ) -> dict[str, Any]:
        awarded = await self.awarded_lot(session, lot_id=lot_id, merchant_id=merchant_id)
        return await verification_module.verify_lot(
            session,
            awarded=awarded,
            merchant_id=merchant_id,
            gateway=self.gateway,
            clock=self.clock,
        )


__all__ = ["AwardedLot", "FUNDED_STATUSES", "FulfillmentService"]
