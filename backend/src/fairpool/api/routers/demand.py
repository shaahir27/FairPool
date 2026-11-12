"""Demand formation routes (CR-17, FR-DM-01 to FR-DM-06).

A buyer consents to a signal, anyone may read the forming-demand aggregates, and an
operator publishes or rejects the draft pool the threshold rule proposed. No route
here creates a PayPal order or moves money (I1, I2, rule 22).
"""

from __future__ import annotations

import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_admin, require_session
from fairpool.api.routers.entries import UserRateLimiter, _settings
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.demand.service import DemandService
from fairpool.modules.identity.service import Principal
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.wiring import pool_service

router = APIRouter()

SIGNAL_LIMIT = 10
SIGNAL_WINDOW_S = 60.0


def _demand(request: Request) -> DemandService:
    settings = _settings(request)
    return DemandService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        notifier=PostgresNotifier(),
        pools=pool_service(settings),
        jobs=PostgresJobQueue(),
        threshold=settings.demand_threshold,
        signal_ttl_days=settings.demand_signal_ttl_days,
    )


@router.post(
    "/api/v1/me/demand-signals",
    response_model=schemas.DemandSignalView,
    operation_id="demand_signal_create",
    status_code=201,
)
async def demand_signal_create(
    payload: schemas.DemandSignalRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.DemandSignalView:
    settings = _settings(request)
    if settings.rate_limit_enabled:
        limiter: UserRateLimiter | None = getattr(request.app.state, "demand_limiter", None)
        if limiter is None:
            limiter = UserRateLimiter(limit=SIGNAL_LIMIT, window_s=SIGNAL_WINDOW_S)
            request.app.state.demand_limiter = limiter
        limiter.check(str(principal.user_id), time.monotonic())
    service = _demand(request)
    row = await service.signal(
        db,
        user_id=principal.user_id,
        product_key=payload.product_key,
        condition=payload.condition,
        variant=payload.variant,
        bundle_contents=payload.bundle_contents,
        region=payload.region,
        source=payload.source,
    )
    await db.commit()
    return schemas.DemandSignalView(**await service.view(db, signal=row))


@router.get(
    "/api/v1/me/demand-signals",
    response_model=list[schemas.DemandSignalView],
    operation_id="demand_signal_list",
)
async def demand_signal_list(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> list[schemas.DemandSignalView]:
    rows = await _demand(request).interests(db, user_id=principal.user_id)
    return [schemas.DemandSignalView(**row) for row in rows]


@router.delete(
    "/api/v1/me/demand-signals/{signal_id}",
    operation_id="demand_signal_cancel",
)
async def demand_signal_cancel(
    signal_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> None:
    await _demand(request).cancel(db, user_id=principal.user_id, signal_id=signal_id)
    await db.commit()


@router.get(
    "/api/v1/demand-clusters",
    response_model=list[schemas.DemandClusterView],
    operation_id="demand_clusters_forming",
)
async def demand_clusters_forming(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    limit: int = Query(20, ge=1, le=100),
) -> list[schemas.DemandClusterView]:
    rows = await _demand(request).forming(db, limit=limit)
    return [schemas.DemandClusterView(**row) for row in rows]


@router.get(
    "/api/v1/admin/demand-proposals",
    response_model=list[schemas.DemandProposalView],
    operation_id="demand_proposals_list",
)
async def demand_proposals_list(
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> list[schemas.DemandProposalView]:
    rows = await _demand(request).proposals(db)
    return [schemas.DemandProposalView(**row) for row in rows]


@router.post(
    "/api/v1/admin/demand-proposals/{cluster_key}/publish",
    operation_id="demand_proposal_publish",
)
async def demand_proposal_publish(
    cluster_key: str,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> dict[str, str]:
    pool = await _demand(request).publish(db, cluster_key=cluster_key, actor_id=principal.user_id)
    await db.commit()
    return {"pool_id": str(pool.id), "status": str(pool.status)}


@router.post(
    "/api/v1/admin/demand-proposals/{cluster_key}/reject",
    operation_id="demand_proposal_reject",
)
async def demand_proposal_reject(
    cluster_key: str,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> dict[str, str]:
    cluster = await _demand(request).reject(db, cluster_key=cluster_key, actor_id=principal.user_id)
    await db.commit()
    return {"cluster_key": cluster.cluster_key, "status": cluster.status}
