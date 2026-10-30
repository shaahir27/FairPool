"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_admin

router = APIRouter()


@router.post(
    "/api/v1/admin/pools",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_create",
    dependencies=[Security(require_admin)],
)
async def admin_pools_create(payload: schemas.PoolCreateRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/pools/{pool_id}/publish",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_publish",
    dependencies=[Security(require_admin)],
)
async def admin_pools_publish(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/pools/{pool_id}/cancel",
    response_model=schemas.AdminPoolResponse,
    operation_id="admin_pools_cancel",
    dependencies=[Security(require_admin)],
)
async def admin_pools_cancel(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
