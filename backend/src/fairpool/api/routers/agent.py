"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_agent, require_session

router = APIRouter()


@router.post(
    "/api/v1/me/delegations",
    response_model=schemas.DelegationCreated,
    operation_id="delegations_create",
    dependencies=[Security(require_session)],
)
async def delegations_create(payload: schemas.DelegationCreateRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/me/delegations",
    response_model=schemas.DelegationList,
    operation_id="delegations_list",
    dependencies=[Security(require_session)],
)
async def delegations_list() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/api/v1/me/delegations/{delegation_id}",
    operation_id="delegations_delete",
    dependencies=[Security(require_session)],
)
async def delegations_delete(delegation_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/agent/v1/pools",
    response_model=list[schemas.AgentPool],
    operation_id="agent_pools",
    dependencies=[Security(require_agent)],
)
async def agent_pools(q: str | None = Query(None), limit: int | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/agent/v1/entries",
    response_model=schemas.AgentEntryResponse,
    operation_id="agent_entries_create",
    dependencies=[Security(require_agent)],
)
async def agent_entries_create(payload: schemas.AgentEntryCreateRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/agent/v1/entries/withdraw",
    response_model=schemas.AgentWithdrawResponse,
    operation_id="agent_entries_withdraw",
    dependencies=[Security(require_agent)],
)
async def agent_entries_withdraw(payload: schemas.AgentWithdrawRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/agent/v1/entries/{entry_id}",
    response_model=schemas.AgentEntryResponse,
    operation_id="agent_entry_get",
    dependencies=[Security(require_agent)],
)
async def agent_entry_get(entry_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/agent/v1/entries/{entry_id}",
    operation_id="agent_entry_delete",
    dependencies=[Security(require_agent)],
)
async def agent_entry_delete(entry_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/agent/v1/entries",
    response_model=schemas.AgentEntryList,
    operation_id="agent_entries_list",
    dependencies=[Security(require_agent)],
)
async def agent_entries_list(
    pool_id: UUID | None = Query(None), entry_id: UUID | None = Query(None)
) -> None:
    raise NotImplementedError("route arrives in a later phase")
