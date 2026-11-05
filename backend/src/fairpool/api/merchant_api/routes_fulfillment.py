"""Merchant Agent API fulfillment operations (T08A03; api.md section 4.3).

The same five bodies as the console, with the key's scope as the only difference:
``fulfillment:read`` for progress and rows, ``shipments:write`` for shipments and
``manifest:read`` for the manifest and the live verification. The service is the
console's, so a key can never see a lot its merchant did not win (PT-15).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant_key
from fairpool.api.routers.merchant_fulfillment import (
    _csv_response,
    _rate_limited,
    _service,
    _wants_csv,
)
from fairpool.modules.fulfillment.verification import RateLimited
from fairpool.modules.merchants.auth import require_scope
from fairpool.ports import MerchantPrincipal

router = APIRouter()


@router.get(
    "/lots/{lot_id}/progress",
    response_model=schemas.LotProgress,
    operation_id="get_lot_progress",
)
async def get_lot_progress(
    lot_id: UUID,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.LotProgress:
    require_scope(principal, "fulfillment:read")
    data = await _service(request).progress(db, lot_id=lot_id, merchant_id=principal.merchant_id)
    return schemas.LotProgress(**data)


@router.get(
    "/lots/{lot_id}/fulfillment",
    response_model=list[schemas.FulfillmentRow],
    operation_id="get_lot_fulfillment",
)
async def get_lot_fulfillment(
    lot_id: UUID,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> list[schemas.FulfillmentRow] | Response:
    require_scope(principal, "fulfillment:read")
    rows = await _service(request).fulfillment_rows(
        db, lot_id=lot_id, merchant_id=principal.merchant_id
    )
    if _wants_csv(request):
        return _csv_response(lot_id, rows)
    return [schemas.FulfillmentRow(**row) for row in rows]


@router.post(
    "/lots/{lot_id}/shipments",
    response_model=schemas.ShipmentsResponse,
    operation_id="submit_shipments",
)
async def submit_shipments(
    lot_id: UUID,
    payload: schemas.ShipmentsRequest,
    request: Request,
    response: Response,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.ShipmentsResponse:
    require_scope(principal, "shipments:write")
    data = await _service(request).record_shipments(
        db,
        lot_id=lot_id,
        merchant_id=principal.merchant_id,
        shipments=[item.model_dump() for item in payload.shipments],
        actor="merchant_key",
    )
    response.status_code = 202
    return schemas.ShipmentsResponse(**data)


@router.get(
    "/lots/{lot_id}/verification-manifest",
    response_model=schemas.VerificationManifest,
    operation_id="get_verification_manifest",
)
async def get_verification_manifest(
    lot_id: UUID,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.VerificationManifest:
    require_scope(principal, "manifest:read")
    data = await _service(request).verification_manifest(
        db, lot_id=lot_id, merchant_id=principal.merchant_id
    )
    return schemas.VerificationManifest(**data)


@router.get(
    "/lots/{lot_id}/verification",
    response_model=schemas.VerificationResponse,
    operation_id="get_lot_verification",
)
async def get_lot_verification(
    lot_id: UUID,
    request: Request,
    principal: Annotated[MerchantPrincipal, Security(require_merchant_key)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.VerificationResponse:
    require_scope(principal, "manifest:read")
    try:
        data = await _service(request).verification(
            db, lot_id=lot_id, merchant_id=principal.merchant_id
        )
    except RateLimited as exc:
        raise _rate_limited(exc) from None
    return schemas.VerificationResponse(**data)


__all__ = ["router"]
