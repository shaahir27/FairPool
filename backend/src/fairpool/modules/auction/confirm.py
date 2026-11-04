"""Confirm then reconcile, one body for the console and the Merchant API (T07A06).

R1 to R9, BS-02/03/05 and the RECONCILE step must not depend on which door a
merchant came through (PT-15): both ``POST /api/v1/merchant/bids/{id}/confirm``
and ``PUT /merchant-api/v1/lots/{id}/bid`` call this function, so a bid can never
be CONFIRMED by one edge and left unreconciled by the other.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Bid, BidRevision, Merchant
from fairpool.db.models.catalog import Pool
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError
from fairpool.modules.auction.bids import BidService
from fairpool.modules.auction.reconcile import OfferReconciler


async def confirm_and_reconcile(
    session: AsyncSession,
    *,
    bid_service: BidService,
    reconciler: OfferReconciler,
    merchant_id: UUID,
    bid_id: UUID,
    revision: int,
    merchant_user_id: UUID | None = None,
) -> Bid:
    """Confirm the revision, then reconcile it, before the caller commits."""
    bid = await bid_service.confirm(
        session, merchant_id=merchant_id, bid_id=bid_id, revision=revision
    )
    lot = await session.get(Lot, bid.lot_id)
    if lot is None:
        return bid
    pool = await session.get(Pool, lot.pool_id)
    row = await session.scalar(
        select(BidRevision).where(
            BidRevision.bid_id == bid.id,
            BidRevision.revision == int(bid.current_revision),
        )
    )
    if pool is None or row is None:
        return bid
    if merchant_user_id is None:
        # The key path has a merchant id but no session user; the notifier still
        # needs the human behind it, so it is read from the merchant row.
        merchant_user_id = await session.scalar(
            select(Merchant.user_id).where(Merchant.id == merchant_id)
        )
        if merchant_user_id is None:
            raise ApplicationError("NOT_FOUND")
    await reconciler.reconcile(
        session,
        bid=bid,
        revision=row,
        lot=lot,
        pool=pool,
        merchant_user_id=merchant_user_id,
    )
    return bid
