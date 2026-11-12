"""Keep frozen offline lots away from network payment gateways (I12, N8)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError


async def require_payment_router(session: AsyncSession, *, lot_id: UUID, router_name: str) -> None:
    row = (
        await session.execute(
            select(Lot.payment_router, Pool.mode)
            .join(Pool, Pool.id == Lot.pool_id)
            .where(Lot.id == lot_id)
        )
    ).first()
    if row is None:
        raise ApplicationError("NOT_FOUND")
    if router_name == "fake" and str(row[0]) == "fake":
        return
    if str(row[0]) == "fake" or str(row[1]) == "SIMULATION":
        raise ApplicationError(
            "FEATURE_DISABLED", "Simulated lots cannot use PayPal checkout or payment processing."
        )
    if str(row[0]) != router_name:
        raise ApplicationError("ORDER_STATE_INVALID", "The lot's payment router is unavailable.")
