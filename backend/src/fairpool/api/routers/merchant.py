"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant, require_session
from fairpool.db.models.auction import Merchant
from fairpool.infra.clock import DbClock
from fairpool.modules.auction.bids import BidService
from fairpool.modules.identity.service import Principal
from fairpool.modules.merchants.profile import MerchantProfileService
from fairpool.modules.pools.receipts import signing_seed

router = APIRouter()


@router.post(
    "/api/v1/merchant/profile",
    response_model=schemas.MerchantProfileResponse,
    operation_id="merchant_profile",
)
async def merchant_profile(
    payload: schemas.MerchantProfileRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MerchantProfileResponse:
    """Create or update the merchant row and stamp the three attestations.

    This is the one merchant route that cannot require the row: it creates it.
    The role check stays, so a buyer still cannot call it.
    """
    if principal.role != "merchant":
        raise HTTPException(403, "FORBIDDEN")
    service = MerchantProfileService(
        clock=DbClock(),
        demo=request.app.state.settings.payment_router == "single_seller",
    )
    merchant = await service.upsert(
        db,
        user_id=principal.user_id,
        display_name=payload.display_name,
        payee_email=payload.payee_email,
        paypal_merchant_id=payload.paypal_merchant_id,
        attestations=payload.attestations,
    )
    await db.commit()
    return schemas.MerchantProfileResponse(
        merchant_id=merchant.id,
        display_name=merchant.display_name,
        onboarding_status=str(merchant.onboarding_status),
        attestations=merchant.attestations,
    )


@router.get(
    "/api/v1/merchant/lots",
    response_model=list[schemas.MerchantLotSummary],
    operation_id="merchant_lots",
    dependencies=[Security(require_merchant)],
)
async def merchant_lots(q: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/merchant/lots/{lot_id}/quote",
    response_model=schemas.QuoteResponse,
    operation_id="merchant_quote",
    dependencies=[Security(require_merchant)],
)
async def merchant_quote(lot_id: UUID, payload: schemas.QuoteRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


async def _merchant_id(db: AsyncSession, principal: Principal) -> UUID:
    value = await db.scalar(select(Merchant.id).where(Merchant.user_id == principal.user_id))
    if value is None:  # require_merchant already guarantees the row; belt and braces
        raise HTTPException(403, "FORBIDDEN")
    return value


def _bid_service(request: Request) -> BidService:
    settings = request.app.state.settings
    return BidService(
        clock=DbClock(),
        seed=signing_seed(settings.receipt_signing_key.get_secret_value()),
        flat_delivered=settings.bid_pricing_mode == "flat_delivered",
    )


@router.put(
    "/api/v1/merchant/lots/{lot_id}/bid",
    response_model=schemas.BidResponse,
    operation_id="merchant_bid_put",
)
async def merchant_bid_put(
    lot_id: UUID,
    payload: schemas.BidRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidResponse:
    """Save a new sealed revision and return its signed receipt (FR-AU-02)."""
    service = _bid_service(request)
    bid, revision = await service.save(
        db,
        merchant_id=await _merchant_id(db, principal),
        lot_id=lot_id,
        structured=payload.structured,
        quote_text=payload.quote_text,
        notes=payload.notes,
    )
    await db.commit()
    return schemas.BidResponse(
        bid_id=bid.id,
        revision=revision.revision,
        status=str(bid.status),
        receipt=schemas.BidReceipt(
            hash=revision.receipt_hash, signature=revision.receipt_signature
        ),
    )


@router.post(
    "/api/v1/merchant/bids/{bid_id}/confirm",
    response_model=schemas.BidConfirmResponse,
    operation_id="merchant_bid_confirm",
)
async def merchant_bid_confirm(
    bid_id: UUID,
    payload: schemas.BidConfirmRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidConfirmResponse:
    """Confirm the current revision; a stale revision is a validation error."""
    service = _bid_service(request)
    bid = await service.confirm(
        db,
        merchant_id=await _merchant_id(db, principal),
        bid_id=bid_id,
        revision=payload.revision,
    )
    await db.commit()
    return schemas.BidConfirmResponse(
        bid_id=bid.id, revision=int(bid.current_revision), status=str(bid.status)
    )


@router.get(
    "/api/v1/merchant/bids/{bid_id}",
    response_model=schemas.BidView,
    operation_id="merchant_bid_get",
)
async def merchant_bid_get(
    bid_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidView:
    """A merchant reads only its own bid; another merchant's id is NOT_FOUND (I11)."""
    service = _bid_service(request)
    bid, revision, flags = await service.get(
        db, merchant_id=await _merchant_id(db, principal), bid_id=bid_id
    )
    return schemas.BidView(
        bid_id=bid.id,
        lot_id=bid.lot_id,
        status=str(bid.status),
        current_revision=int(bid.current_revision),
        structured=revision.structured,
        flags=[
            schemas.BidFlagView(
                code=flag.code,
                severity=str(flag.severity),
                field=flag.field,
                evidence=flag.evidence,
            )
            for flag in flags
        ],
    )


@router.get(
    "/api/v1/merchant/events",
    operation_id="merchant_events",
    dependencies=[Security(require_merchant)],
)
async def merchant_events() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/bids",
    response_model=schemas.MerchantBidList,
    operation_id="merchant_bids",
    dependencies=[Security(require_merchant)],
)
async def merchant_bids(status: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")
