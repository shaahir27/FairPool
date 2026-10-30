"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_session

router = APIRouter()


@router.post(
    "/api/v1/pools/{pool_id}/entries",
    response_model=schemas.EntryCreateResponse,
    operation_id="entries_join",
    dependencies=[Security(require_session)],
)
async def entries_join(pool_id: UUID, payload: schemas.EntryCreateRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/pools/{pool_id}/entries/me",
    response_model=schemas.EntryStatusResponse,
    operation_id="entries_me_get",
    dependencies=[Security(require_session)],
)
async def entries_me_get(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/api/v1/pools/{pool_id}/entries/me",
    operation_id="entries_me_delete",
    dependencies=[Security(require_session)],
)
async def entries_me_delete(pool_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/entries/{entry_id}/vault",
    response_model=schemas.VaultStartResponse,
    operation_id="vault_start",
    dependencies=[Security(require_session)],
)
async def vault_start(entry_id: UUID, payload: schemas.VaultStartRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/entries/{entry_id}/vault/return",
    operation_id="vault_return",
    dependencies=[Security(require_session)],
)
async def vault_return(
    entry_id: UUID,
    token: str | None = Query(None),
    payer_id: str | None = Query(None, alias="PayerID"),
) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/api/v1/entries/{entry_id}/vault",
    operation_id="vault_delete",
    dependencies=[Security(require_session)],
)
async def vault_delete(entry_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/me/entries",
    response_model=schemas.MeEntryList,
    operation_id="me_entries",
    dependencies=[Security(require_session)],
)
async def me_entries() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/entries/{entry_id}/status",
    response_model=schemas.EntryStatusResponse,
    operation_id="entry_status",
    dependencies=[Security(require_session)],
)
async def entry_status(entry_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
