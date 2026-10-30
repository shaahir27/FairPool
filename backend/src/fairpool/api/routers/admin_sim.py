"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_admin

router = APIRouter()


@router.post(
    "/api/v1/admin/sim/run",
    response_model=schemas.SimRunResponse,
    operation_id="admin_sim_run",
    dependencies=[Security(require_admin)],
)
async def admin_sim_run(payload: schemas.SimRunRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/search/reindex",
    operation_id="admin_search_reindex",
    dependencies=[Security(require_admin)],
)
async def admin_search_reindex() -> None:
    raise NotImplementedError("route arrives in a later phase")
