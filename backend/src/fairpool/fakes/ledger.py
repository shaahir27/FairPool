"""Deterministic ledger fake (T01A02; I4, I5)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LedgerRow:
    lot_id: UUID
    buyer_order_id: UUID
    kind: str
    amount_cents: int
    paypal_ref: str
    idempotency_key: str
    source: str


class FakeLedger:
    def __init__(self) -> None:
        self.entries: list[LedgerRow] = []
        self.calls: list[str] = []

    async def record(
        self,
        session: AsyncSession,
        *,
        lot_id: UUID,
        buyer_order_id: UUID,
        kind: str,
        amount_cents: int,
        paypal_ref: str,
        idempotency_key: str,
        source: str,
    ) -> bool:
        self.calls.append(f"record:{kind}")
        if any(row.idempotency_key == idempotency_key for row in self.entries):
            return False
        self.entries.append(
            LedgerRow(
                lot_id=lot_id,
                buyer_order_id=buyer_order_id,
                kind=kind,
                amount_cents=amount_cents,
                paypal_ref=paypal_ref,
                idempotency_key=idempotency_key,
                source=source,
            )
        )
        return True

    async def net_paid_cents(self, session: AsyncSession, lot_id: UUID) -> int:
        captured = sum(
            row.amount_cents
            for row in self.entries
            if row.lot_id == lot_id and row.kind == "CAPTURE_COMPLETED"
        )
        refunded = sum(
            row.amount_cents
            for row in self.entries
            if row.lot_id == lot_id and row.kind == "REFUND_COMPLETED"
        )
        return captured - refunded

    async def completed_capture_count(self, session: AsyncSession, lot_id: UUID) -> int:
        return len(
            {
                row.buyer_order_id
                for row in self.entries
                if row.lot_id == lot_id and row.kind == "CAPTURE_COMPLETED"
            }
        )
