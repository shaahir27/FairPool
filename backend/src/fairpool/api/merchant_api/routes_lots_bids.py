"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant_key

router = APIRouter()


@router.get(
    "/lots",
    response_model=list[schemas.MerchantLotSummary],
    operation_id="list_lots",
    dependencies=[Security(require_merchant_key)],
)
async def list_lots(q: str | None = Query(None), status: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/lots/{lot_id}",
    response_model=schemas.MerchantLotSummary,
    operation_id="get_lot",
    dependencies=[Security(require_merchant_key)],
)
async def get_lot(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.put(
    "/lots/{lot_id}/bid",
    response_model=schemas.BidResponse,
    operation_id="submit_bid",
    dependencies=[Security(require_merchant_key)],
)
async def submit_bid(lot_id: UUID, payload: schemas.MerchantApiBidRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/bids",
    response_model=schemas.MerchantBidList,
    operation_id="list_bids",
    dependencies=[Security(require_merchant_key)],
)
async def list_bids() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/bids/{bid_id}",
    response_model=schemas.BidView,
    operation_id="get_bid",
    dependencies=[Security(require_merchant_key)],
)
async def get_bid(bid_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
