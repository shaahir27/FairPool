"""Merchant console fulfillment routes (T08A01; api.md sections 2 and 4.2).

Thin bodies over ``FulfillmentService``; the Merchant Agent API calls the same
service with the same shapes and only differs in how the merchant is resolved.
The CSV branch reads the ``Accept`` header from the request rather than declaring
it as a parameter, so the JSON response model stays the documented one while the
wire can still answer ``text/csv``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant
from fairpool.api.routers.merchant import _merchant_id
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.fulfillment import csv as fulfillment_csv
from fairpool.modules.fulfillment.service import FulfillmentService
from fairpool.modules.fulfillment.verification import RateLimited
from fairpool.modules.identity.service import Principal
from fairpool.modules.ledger.service import PostgresLedger
from fairpool.wiring import payment_router, shipping_cipher

router = APIRouter()


def _service(request: Request) -> FulfillmentService:
    """One service per app; ``app.state.fulfillment_gateway`` is the test seam."""
    cached: FulfillmentService | None = getattr(request.app.state, "fulfillment_service", None)
    if cached is not None:
        return cached
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    gateway = getattr(request.app.state, "fulfillment_gateway", None)
    if gateway is None:
        gateway = payment_router(settings).gateway
    built = FulfillmentService(
        cipher=shipping_cipher(settings),
        ledger=PostgresLedger(),
        jobs=PostgresJobQueue(),
        audit=PostgresAuditLog(),
        clock=DbClock(),
        gateway=gateway,
        tracking_enabled=settings.shipment_tracking_enabled,
    )
    request.app.state.fulfillment_service = built
    return built


def _wants_csv(request: Request) -> bool:
    return "text/csv" in request.headers.get("accept", "").lower()


def _csv_response(lot_id: UUID, rows: list[dict[str, object]]) -> Response:
    return Response(
        content=fulfillment_csv.render(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="fulfillment-{lot_id}.csv"'},
    )


def _rate_limited(exc: RateLimited) -> HTTPException:
    return HTTPException(429, "RATE_LIMITED", headers={"Retry-After": str(exc.retry_after)})


@router.get(
    "/api/v1/merchant/lots/{lot_id}/progress",
    response_model=schemas.LotProgress,
    operation_id="merchant_lot_progress",
)
async def merchant_lot_progress(
    lot_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.LotProgress:
    data = await _service(request).progress(
        db, lot_id=lot_id, merchant_id=await _merchant_id(db, principal)
    )
    return schemas.LotProgress(**data)


@router.get(
    "/api/v1/merchant/lots/{lot_id}/fulfillment",
    response_model=list[schemas.FulfillmentRow],
    operation_id="merchant_lot_fulfillment",
)
async def merchant_lot_fulfillment(
    lot_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> list[schemas.FulfillmentRow] | Response:
    rows = await _service(request).fulfillment_rows(
        db, lot_id=lot_id, merchant_id=await _merchant_id(db, principal)
    )
    if _wants_csv(request):
        return _csv_response(lot_id, rows)
    return [schemas.FulfillmentRow(**row) for row in rows]


@router.post(
    "/api/v1/merchant/lots/{lot_id}/shipments",
    response_model=schemas.ShipmentsResponse,
    operation_id="merchant_lot_shipments",
)
async def merchant_lot_shipments(
    lot_id: UUID,
    payload: schemas.ShipmentsRequest,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.ShipmentsResponse:
    data = await _service(request).record_shipments(
        db,
        lot_id=lot_id,
        merchant_id=await _merchant_id(db, principal),
        shipments=[item.model_dump() for item in payload.shipments],
        actor="merchant",
    )
    response.status_code = 202
    return schemas.ShipmentsResponse(**data)


@router.get(
    "/api/v1/merchant/lots/{lot_id}/verification-manifest",
    response_model=schemas.VerificationManifest,
    operation_id="merchant_lot_manifest",
)
async def merchant_lot_manifest(
    lot_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.VerificationManifest:
    data = await _service(request).verification_manifest(
        db, lot_id=lot_id, merchant_id=await _merchant_id(db, principal)
    )
    return schemas.VerificationManifest(**data)


@router.get(
    "/api/v1/merchant/lots/{lot_id}/verification",
    response_model=schemas.VerificationResponse,
    operation_id="merchant_lot_verification",
)
async def merchant_lot_verification(
    lot_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.VerificationResponse:
    try:
        data = await _service(request).verification(
            db, lot_id=lot_id, merchant_id=await _merchant_id(db, principal)
        )
    except RateLimited as exc:
        raise _rate_limited(exc) from None
    return schemas.VerificationResponse(**data)


__all__ = ["router"]
