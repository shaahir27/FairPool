"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant

router = APIRouter()


@router.post(
    "/api/v1/merchant/profile",
    response_model=schemas.MerchantProfileResponse,
    operation_id="merchant_profile",
    dependencies=[Security(require_merchant)],
)
async def merchant_profile(payload: schemas.MerchantProfileRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


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


@router.put(
    "/api/v1/merchant/lots/{lot_id}/bid",
    response_model=schemas.BidResponse,
    operation_id="merchant_bid_put",
    dependencies=[Security(require_merchant)],
)
async def merchant_bid_put(lot_id: UUID, payload: schemas.BidRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/merchant/bids/{bid_id}/confirm",
    response_model=schemas.BidConfirmResponse,
    operation_id="merchant_bid_confirm",
    dependencies=[Security(require_merchant)],
)
async def merchant_bid_confirm(bid_id: UUID, payload: schemas.BidConfirmRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/bids/{bid_id}",
    response_model=schemas.BidView,
    operation_id="merchant_bid_get",
    dependencies=[Security(require_merchant)],
)
async def merchant_bid_get(bid_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


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
