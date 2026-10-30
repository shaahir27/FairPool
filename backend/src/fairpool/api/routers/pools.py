"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from fairpool.api import schemas

router = APIRouter()


@router.get(
    "/api/v1/pools",
    response_model=list[schemas.PoolSummary],
    operation_id="pools_list",
)
async def pools_list(
    q: str | None = Query(None),
    status: str | None = Query(None),
    sort: str | None = Query(None),
    limit: int | None = Query(None),
) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/pools/{pool_id}",
    response_model=schemas.PoolDetail,
    operation_id="pools_get",
)
async def pools_get(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/pools/{pool_id}/rules",
    response_model=schemas.RulesDocument,
    operation_id="pools_rules",
)
async def pools_rules(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/pools/{pool_id}/events",
    operation_id="pools_events",
)
async def pools_events(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
