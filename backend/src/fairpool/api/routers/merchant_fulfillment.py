"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant

router = APIRouter()


@router.get(
    "/api/v1/merchant/lots/{lot_id}/progress",
    response_model=schemas.LotProgress,
    operation_id="merchant_lot_progress",
    dependencies=[Security(require_merchant)],
)
async def merchant_lot_progress(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/lots/{lot_id}/fulfillment",
    response_model=list[schemas.FulfillmentRow],
    operation_id="merchant_lot_fulfillment",
    dependencies=[Security(require_merchant)],
)
async def merchant_lot_fulfillment(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/merchant/lots/{lot_id}/shipments",
    response_model=schemas.ShipmentsResponse,
    operation_id="merchant_lot_shipments",
    dependencies=[Security(require_merchant)],
)
async def merchant_lot_shipments(lot_id: UUID, payload: schemas.ShipmentsRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/lots/{lot_id}/verification-manifest",
    response_model=schemas.VerificationManifest,
    operation_id="merchant_lot_manifest",
    dependencies=[Security(require_merchant)],
)
async def merchant_lot_manifest(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/lots/{lot_id}/verification",
    response_model=schemas.VerificationResponse,
    operation_id="merchant_lot_verification",
    dependencies=[Security(require_merchant)],
)
async def merchant_lot_verification(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
