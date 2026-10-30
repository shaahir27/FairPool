"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from fairpool.api import schemas

router = APIRouter()


@router.get(
    "/api/v1/public/pools/{pool_id}/audit",
    response_model=schemas.PublicAuditResponse,
    operation_id="public_audit",
)
async def public_audit(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/public/keys",
    response_model=schemas.PublicKeysResponse,
    operation_id="public_keys",
)
async def public_keys() -> None:
    raise NotImplementedError("route arrives in a later phase")
