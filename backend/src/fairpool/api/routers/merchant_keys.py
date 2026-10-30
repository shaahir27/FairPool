"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant

router = APIRouter()


@router.get(
    "/api/v1/merchant/api-keys",
    response_model=schemas.ApiKeyList,
    operation_id="merchant_api_keys_list",
    dependencies=[Security(require_merchant)],
)
async def merchant_api_keys_list() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/merchant/api-keys",
    response_model=schemas.ApiKeyCreated,
    operation_id="merchant_api_keys_create",
    dependencies=[Security(require_merchant)],
)
async def merchant_api_keys_create(payload: schemas.ApiKeyCreateRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/api/v1/merchant/api-keys/{key_id}",
    operation_id="merchant_api_keys_delete",
    dependencies=[Security(require_merchant)],
)
async def merchant_api_keys_delete(key_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
