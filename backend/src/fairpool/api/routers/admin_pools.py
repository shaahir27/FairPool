"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_admin
from fairpool.modules.identity.service import Principal
from fairpool.wiring import pool_service

router = APIRouter()


@router.post(
    "/api/v1/admin/pools",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_create",
    dependencies=[Security(require_admin)],
)
async def admin_pools_create(
    payload: schemas.PoolCreateRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: AsyncSession = Depends(database_session),
):
    if payload.require_paypal_link and request.app.state.settings.dedupe_mode == "checkout_only":
        from fairpool.domain.errors import ApplicationError

        raise ApplicationError("VALIDATION_ERROR")
    from fairpool.domain.pool_config import TIMING_PROFILES, Timeline

    payload.timeline = Timeline.model_validate(
        {
            **TIMING_PROFILES[request.app.state.settings.timing_profile],
            **payload.timeline.model_dump(exclude_unset=True),
        }
    )
    result = await pool_service(request.app.state.settings).create(
        db, actor_id=principal.user_id, payload=payload
    )
    return {"pool_id": result.id, "status": result.status}


@router.post(
    "/api/v1/admin/pools/{pool_id}/publish",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_publish",
    dependencies=[Security(require_admin)],
)
async def admin_pools_publish(
    pool_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: AsyncSession = Depends(database_session),
):
    result = await pool_service(request.app.state.settings).publish(
        db, pool_id, actor_id=principal.user_id
    )
    return {"pool_id": result.id, "status": result.status}


@router.post(
    "/api/v1/admin/pools/{pool_id}/cancel",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_cancel",
    dependencies=[Security(require_admin)],
)
async def admin_pools_cancel(
    pool_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: AsyncSession = Depends(database_session),
):
    result = await pool_service(request.app.state.settings).cancel(
        db, pool_id, actor_id=principal.user_id
    )
    return {"pool_id": result.id, "status": result.status}
