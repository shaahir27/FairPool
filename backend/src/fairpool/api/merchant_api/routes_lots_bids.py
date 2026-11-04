"""Merchant Agent API: lots and bids (T07A06; api.md section 4.3).

The five operations here call the same services the merchant console calls:
``BidService`` for sealing and receipts, ``confirm_and_reconcile`` for BS-02/03/05
plus RECONCILE, and the one search service for the Demand Board. A key resolves to
the same ``MerchantPrincipal`` a session does, so ``bids:read``/``lots:read`` and
the merchant-scoped reads seal exactly as the console's do (PT-15).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant_key
from fairpool.api.routers.merchant import (
    _bid_service,
    _offer_reconciler,
    advise_similarity,
    bid_view,
    list_open_lots,
    lot_summary_for,
)
from fairpool.api.routers.pools import _search_service
from fairpool.db.models.auction import Bid
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.modules.auction.confirm import confirm_and_reconcile
from fairpool.modules.merchants.auth import require_scope
from fairpool.ports import IdemNew, IdemReplay, MerchantPrincipal

router = APIRouter()

_IDEM_SCOPE = "merchant_api.submit_bid"


@router.get(
    "/lots",
    response_model=list[schemas.MerchantLotSummary],
    operation_id="list_lots",
)
async def list_lots(
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
    q: str | None = Query(None),
    status: str | None = Query(None),
) -> list[schemas.MerchantLotSummary]:
    require_scope(principal, "lots:read")
    search = _search_service(request) if q else None
    return await list_open_lots(db, search=search, q=q, status=status)


@router.get(
    "/lots/{lot_id}",
    response_model=schemas.MerchantLotSummary,
    operation_id="get_lot",
)
async def get_lot(
    lot_id: UUID,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MerchantLotSummary:
    require_scope(principal, "lots:read")
    return await lot_summary_for(db, lot_id)


@router.put(
    "/lots/{lot_id}/bid",
    response_model=schemas.BidResponse,
    operation_id="submit_bid",
)
async def submit_bid(
    lot_id: UUID,
    payload: schemas.MerchantApiBidRequest,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> schemas.BidResponse:
    require_scope(principal, "bids:write")
    # api.md section 1: required, any string up to 128 characters.
    if idempotency_key is None or not idempotency_key:
        raise ApplicationError("IDEMPOTENCY_KEY_REQUIRED")
    if len(idempotency_key) > 128:
        raise ApplicationError("VALIDATION_ERROR")
    store = PostgresIdempotencyStore()
    # The merchant id is part of the key itself, not only the scope: two merchants
    # may pick the same header value, and one must never replay the other's answer.
    key = f"merchant-api-bid:{principal.merchant_id}:{idempotency_key}"
    request_hash = hashing.request_hash(
        {"lot_id": str(lot_id), "structured": payload.structured, "notes": payload.notes}
    )
    idem = await store.begin(db, key=key, scope=_IDEM_SCOPE, request_hash=request_hash)
    if isinstance(idem, IdemReplay):
        return schemas.BidResponse(**idem.response)
    if not isinstance(idem, IdemNew):
        # A different body under the same key, or an in-flight key with no stored answer.
        raise ApplicationError("IDEMPOTENCY_CONFLICT")

    # The bot's structured submission is its confirmation (api.md section 4.3), so the
    # save and the confirm land in one transaction with one receipt.
    service = _bid_service(request)
    bid, revision = await service.save(
        db,
        merchant_id=principal.merchant_id,
        lot_id=lot_id,
        structured=payload.structured,
        notes=payload.notes,
    )
    bid = await confirm_and_reconcile(
        db,
        bid_service=service,
        reconciler=_offer_reconciler(request),
        merchant_id=principal.merchant_id,
        bid_id=bid.id,
        revision=revision.revision,
    )
    response = schemas.BidResponse(
        bid_id=bid.id,
        revision=int(bid.current_revision),
        status=str(bid.status),
        receipt=schemas.BidReceipt(
            hash=revision.receipt_hash, signature=revision.receipt_signature
        ),
    )
    await store.complete(db, key=key, response=response.model_dump(mode="json"))
    await db.commit()
    await advise_similarity(request, db, bid.id)
    return response


@router.get(
    "/bids",
    response_model=schemas.MerchantBidList,
    operation_id="list_bids",
)
async def list_bids(
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MerchantBidList:
    require_scope(principal, "bids:read")
    service = _bid_service(request)
    ids = list(
        await db.scalars(
            select(Bid.id)
            .where(Bid.merchant_id == principal.merchant_id)
            .order_by(Bid.created_at, Bid.id)
        )
    )
    items: list[schemas.BidView] = []
    for bid_id in ids:
        bid, revision, flags = await service.get(
            db, merchant_id=principal.merchant_id, bid_id=bid_id
        )
        items.append(bid_view(bid, revision, flags))
    return schemas.MerchantBidList(items=items)


@router.get(
    "/bids/{bid_id}",
    response_model=schemas.BidView,
    operation_id="get_bid",
)
async def get_bid(
    bid_id: UUID,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidView:
    require_scope(principal, "bids:read")
    bid, revision, flags = await _bid_service(request).get(
        db, merchant_id=principal.merchant_id, bid_id=bid_id
    )
    return bid_view(bid, revision, flags)
