"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant_key

router = APIRouter()


@router.get(
    "/lots/{lot_id}/progress",
    response_model=schemas.LotProgress,
    operation_id="get_lot_progress",
    dependencies=[Security(require_merchant_key)],
)
async def get_lot_progress(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/lots/{lot_id}/fulfillment",
    response_model=list[schemas.FulfillmentRow],
    operation_id="get_lot_fulfillment",
    dependencies=[Security(require_merchant_key)],
)
async def get_lot_fulfillment(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/lots/{lot_id}/shipments",
    response_model=schemas.ShipmentsResponse,
    operation_id="submit_shipments",
    dependencies=[Security(require_merchant_key)],
)
async def submit_shipments(lot_id: UUID, payload: schemas.ShipmentsRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/lots/{lot_id}/verification-manifest",
    response_model=schemas.VerificationManifest,
    operation_id="get_verification_manifest",
    dependencies=[Security(require_merchant_key)],
)
async def get_verification_manifest(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/lots/{lot_id}/verification",
    response_model=schemas.VerificationResponse,
    operation_id="get_lot_verification",
    dependencies=[Security(require_merchant_key)],
)
async def get_lot_verification(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
