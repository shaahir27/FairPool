"""Append-only payment facts; transactions belong to the caller."""

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.money import to_paypal_string


class PostgresLedger:
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
        to_paypal_string(amount_cents)
        if not idempotency_key or not paypal_ref:
            raise ValueError("Payment identity required")
        actual_lot = await session.scalar(
            text("SELECT lot_id FROM buyer_orders WHERE id=:id FOR KEY SHARE"),
            {"id": buyer_order_id},
        )
        if actual_lot != lot_id:
            raise ValueError("Buyer order must belong to ledger lot")
        values = dict(
            id=uuid4(),
            lot=lot_id,
            buyer=buyer_order_id,
            kind=kind,
            amount=amount_cents,
            ref=paypal_ref,
            key=idempotency_key,
            source=source,
        )
        inserted = await session.scalar(
            text(
                "INSERT INTO ledger_entries(id,lot_id,buyer_order_id,kind,amount_cents,pa"
                "ypal_ref,idempotency_key,source) "
                "VALUES(:id,:lot,:buyer,:kind,:amount,:ref,:key,:source) "
                "ON CONFLICT(idempotency_key) DO NOTHING RETURNING id"
            ),
            values,
        )
        if inserted is None:
            row = (
                await session.execute(
                    text(
                        "SELECT lot_id,buyer_order_id,kind,amount_cents,paypal_ref FROM "
                        "ledger_entries WHERE idempotency_key=:key"
                    ),
                    {"key": idempotency_key},
                )
            ).one()
            if tuple(row) != (lot_id, buyer_order_id, kind, amount_cents, paypal_ref):
                raise ValueError("Idempotency key reused with a different payment fact")
        return inserted is not None

    async def net_paid_cents(self, session: AsyncSession, lot_id: UUID) -> int:
        value = await session.scalar(
            text(
                "SELECT COALESCE(sum(CASE WHEN kind='CAPTURE_COMPLETED' THEN amount_cents"
                " WHEN kind='REFUND_COMPLETED' THEN -amount_cents ELSE 0 END),0) FROM "
                "ledger_entries WHERE lot_id=:lot"
            ),
            {"lot": lot_id},
        )
        return int(value or 0)

    async def completed_capture_count(self, session: AsyncSession, lot_id: UUID) -> int:
        value = await session.scalar(
            text(
                "SELECT count(DISTINCT e.user_id) FROM ledger_entries l JOIN buyer_orders"
                " b ON b.id=l.buyer_order_id JOIN pool_entries e ON e.id=b.entry_id WHERE"
                " l.lot_id=:lot AND l.kind='CAPTURE_COMPLETED'"
            ),
            {"lot": lot_id},
        )
        return int(value or 0)
