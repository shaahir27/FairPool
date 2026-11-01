"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.infra.audit import PostgresAuditLog
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.manual import ManualIntakeService

router = APIRouter()


@router.post(
    "/api/v1/intake/messages",
    response_model=schemas.IntakeMessageResponse,
    operation_id="intake_messages",
    dependencies=[Security(require_session)],
)
async def intake_messages(payload: schemas.IntakeMessageRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/intake/confirm",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_confirm",
    dependencies=[Security(require_session)],
)
async def intake_confirm(payload: schemas.IntakeConfirmRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/intake/manual",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_manual",
)
async def intake_manual(
    payload: schemas.ManualIntakeRequest,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The deterministic half of intake (CR-3 pull-forward from T04B01).

    No AI is involved and nothing here depends on T02B03: the buyer's own form is
    validated against the pool's frozen template and stored as the immutable
    confirmed request the join endpoint consumes.
    """
    service = ManualIntakeService(PostgresAuditLog())
    record = await service.confirm(
        db,
        user_id=principal.user_id,
        pool_id=payload.pool_id,
        # The frozen validator accepts buyer-chosen fields only; ``pool_id`` selects
        # the pool and is not part of the request it validates.
        payload=payload.model_dump(mode="json", exclude={"pool_id"}),
    )
    # A raw Response skips FastAPI's jsonable_encoder, so every value must already
    # be JSON-native: ids are text here exactly as the join lane writes them.
    return JSONResponse(
        status_code=201,
        content={
            "confirmed_request_id": str(record.id),
            "canonical_request": record.canonical_request,
        },
    )
