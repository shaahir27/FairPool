"""Agent API and delegation routes (T07A05; api.md sections 2, 4.4 and 4.5).

The bearer token is a buyer delegation (``fpd_``), never a payment credential:
every handler here lists, joins, reads or withdraws an entry. No route in this
file creates an order, authorizes, captures, voids or refunds (I1, I2, rule 22).

``/agent/v1/entries/withdraw`` is registered before ``/agent/v1/entries/{id}``
because the flat form exists for tool bridges that cannot set a path variable
(api.md §4.4); ``test_api_contract`` asserts the order.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_agent, require_session
from fairpool.api.routers.entries import _join_service, _settings
from fairpool.api.routers.pools import _search_service
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.modules.agentapi.service import AgentService
from fairpool.modules.identity.delegations import AgentPrincipal, DelegationService
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.manual import ManualIntakeService

router = APIRouter()


def _delegations(request: Request) -> DelegationService:
    settings = _settings(request)
    return DelegationService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        hmac_key=settings.hmac_key.get_secret_value(),
    )


def _agent_service(request: Request) -> AgentService:
    """One agent service per call; the join service itself is cached on the app."""
    settings = _settings(request)
    return AgentService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        idempotency=PostgresIdempotencyStore(),
        join=_join_service(request),
        manual=ManualIntakeService(PostgresAuditLog()),
        frontend_base_url=settings.frontend_base_url,
    )


# ------------------------------------------------------------- delegations


@router.post(
    "/api/v1/me/delegations",
    response_model=schemas.DelegationCreated,
    operation_id="delegations_create",
    status_code=201,
)
async def delegations_create(
    payload: schemas.DelegationCreateRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.DelegationCreated:
    """Issue a delegation token and show it here and only here (rule 25)."""
    row, token = await _delegations(request).create(
        db,
        user_id=principal.user_id,
        scope=payload.scope.model_dump(mode="json"),
        max_cap_cents=payload.max_cap_cents,
        expires_at=payload.expires_at,
    )
    await db.commit()
    return schemas.DelegationCreated(
        id=row.id,
        scope=row.scope,
        max_cap_cents=row.max_cap_cents,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        token=token,
    )


@router.get(
    "/api/v1/me/delegations",
    response_model=schemas.DelegationList,
    operation_id="delegations_list",
)
async def delegations_list(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.DelegationList:
    rows = await _delegations(request).list(db, user_id=principal.user_id)
    return schemas.DelegationList(
        items=[
            schemas.DelegationView(
                id=row.id,
                scope=row.scope,
                max_cap_cents=row.max_cap_cents,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
    )


@router.delete(
    "/api/v1/me/delegations/{delegation_id}",
    operation_id="delegations_delete",
)
async def delegations_delete(
    delegation_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> None:
    """Revoke; another buyer's delegation id answers 404 like an unknown one."""
    await _delegations(request).revoke(db, user_id=principal.user_id, delegation_id=delegation_id)
    await db.commit()


# --------------------------------------------------------------- agent API


@router.get(
    "/agent/v1/pools",
    response_model=list[schemas.AgentPool],
    operation_id="agent_pools",
)
async def agent_pools(
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
    q: str | None = Query(None, max_length=200),
    limit: int | None = Query(None, ge=1, le=20),
) -> list[dict[str, object]]:
    return await _agent_service(request).list_pools(
        db, principal=principal, q=q, limit=limit or 20, search=_search_service(request)
    )


@router.post(
    "/agent/v1/entries",
    response_model=schemas.AgentEntryResponse,
    operation_id="agent_entries_create",
)
async def agent_entries_create(
    payload: schemas.AgentEntryCreateRequest,
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Create the buyer's entry through the web flow's validator (FR-SL-03)."""
    key = _idempotency_key(idempotency_key, payload.idempotency_key)
    status_code, body = await _agent_service(request).create_entry(
        db,
        principal=principal,
        pool_id=payload.pool_id,
        request=payload.request.model_dump(),
        idempotency_key=key,
    )
    return JSONResponse(status_code=status_code, content=body)


@router.post(
    "/agent/v1/entries/withdraw",
    response_model=schemas.AgentWithdrawResponse,
    operation_id="agent_entries_withdraw",
)
async def agent_entries_withdraw(
    payload: schemas.AgentWithdrawRequest,
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    return await _withdraw(request, db, principal, payload.entry_id)


@router.get(
    "/agent/v1/entries/{entry_id}",
    response_model=schemas.AgentEntryResponse,
    operation_id="agent_entry_get",
)
async def agent_entry_get(
    entry_id: UUID,
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> dict[str, object]:
    return await _agent_service(request).get_entry(db, principal=principal, entry_id=entry_id)


@router.delete(
    "/agent/v1/entries/{entry_id}",
    response_model=schemas.AgentWithdrawResponse,
    operation_id="agent_entry_delete",
)
async def agent_entry_delete(
    entry_id: UUID,
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> JSONResponse:
    return await _withdraw(request, db, principal, entry_id)


@router.get(
    "/agent/v1/entries",
    response_model=schemas.AgentEntryList,
    operation_id="agent_entries_list",
)
async def agent_entries_list(
    request: Request,
    principal: Annotated[AgentPrincipal, Security(require_agent)],
    db: Annotated[AsyncSession, Depends(database_session)],
    pool_id: UUID | None = Query(None),
    entry_id: UUID | None = Query(None),
) -> schemas.AgentEntryList:
    items = await _agent_service(request).list_entries(
        db, principal=principal, pool_id=pool_id, entry_id=entry_id
    )
    return schemas.AgentEntryList(
        items=[schemas.AgentEntryResponse.model_validate(item) for item in items]
    )


def _idempotency_key(header: str | None, body: str | None) -> str:
    """Resolve the two accepted forms; a mismatch is a conflict (api.md §4.4)."""
    if header is None and body is None:
        raise HTTPException(400, "IDEMPOTENCY_KEY_REQUIRED")
    if header is not None and body is not None and header != body:
        raise HTTPException(409, "IDEMPOTENCY_CONFLICT")
    key = header if header is not None else body
    assert key is not None
    if not key or len(key) > 128:
        raise HTTPException(422, "VALIDATION_ERROR")
    return key


async def _withdraw(
    request: Request,
    db: AsyncSession,
    principal: AgentPrincipal,
    entry_id: UUID,
) -> JSONResponse:
    """Withdraw the entry, exactly like ``DELETE .../entries/me`` minus the vault leg.

    Rule 22: no AI-callable route performs a PayPal write, so the saved permission
    is left to the buyer's settings page and this route never calls the provider.
    A repeated call answers the same body, so the tool form is idempotent.
    """
    service = _agent_service(request)
    entry = await service.owned_entry(db, principal=principal, entry_id=entry_id)
    outcome = await _join_service(request).withdraw(
        db, pool_id=entry.pool_id, user_id=principal.user_id
    )
    await db.commit()
    return JSONResponse(
        status_code=200,
        content={
            "entry_id": str(outcome.body["entry_id"]),
            "entry_status": str(outcome.body["entry_status"]),
        },
    )
