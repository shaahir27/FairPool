"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.api import schemas
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import PoolStatus
from fairpool.db.session import create_engine
from fairpool.modules.pools.events import stream_pool_events
from fairpool.modules.pools.service import rules_document, summary

router = APIRouter()


@router.get(
    "/api/v1/pools",
    response_model=list[schemas.PoolSummary],
    operation_id="pools_list",
)
async def pools_list(
    q: str | None = Query(None, max_length=200),
    status: str | None = Query(None),
    sort: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=100),
    db: AsyncSession = Depends(database_session),
):
    query = select(Pool).where(Pool.status != PoolStatus.DRAFT)
    if status:
        if status not in PoolStatus.__members__ or status == "DRAFT":
            raise HTTPException(422, "VALIDATION_ERROR")
        query = query.where(Pool.status == PoolStatus(status))
    if q:
        query = query.where(
            Pool.search_text.ilike("%" + q.replace("%", "\\%").replace("_", "\\_") + "%")
        )
    if sort not in (None, "closing", "title"):
        raise HTTPException(422, "VALIDATION_ERROR")
    query = query.order_by(
        Pool.title if sort == "title" else Pool.timeline["close_at"].astext, Pool.id
    )
    return [summary(p) for p in (await db.scalars(query.limit(limit or 20))).all()]


@router.get(
    "/api/v1/pools/{pool_id}",
    response_model=schemas.PoolDetail,
    operation_id="pools_get",
)
async def pools_get(pool_id: UUID, db: AsyncSession = Depends(database_session)):
    pool = await public_pool(db, pool_id)
    return {
        **summary(pool),
        "template": pool.template,
        "lot_plan": pool.lot_plan,
        "timeline": pool.timeline,
        "rules_hash": pool.rules_hash,
    }


@router.get(
    "/api/v1/pools/{pool_id}/rules",
    response_model=schemas.RulesResponse,
    operation_id="pools_rules",
)
async def pools_rules(pool_id: UUID, db: AsyncSession = Depends(database_session)):
    pool = await public_pool(db, pool_id)
    if not pool.rules_hash:
        raise HTTPException(404, "NOT_FOUND")
    return {"rules_document": rules_document(pool), "rules_hash": pool.rules_hash}


@router.get(
    "/api/v1/pools/{pool_id}/events",
    operation_id="pools_events",
)
async def pools_events(pool_id: UUID, request: Request):
    # Public feed (api.md "Server-sent events"): pool_status, lot_status and
    # tick only; the generator opens short read sessions and holds no lock.
    if not hasattr(request.app.state, "session_factory"):
        settings = request.app.state.settings
        if settings is None:
            raise HTTPException(500, "INTERNAL_ERROR")
        request.app.state.engine = create_engine(settings)
        request.app.state.session_factory = async_sessionmaker(
            request.app.state.engine, expire_on_commit=False
        )
    factory = request.app.state.session_factory
    async with factory() as probe:
        exists = await probe.scalar(
            text("SELECT status FROM pools WHERE id = :id"), {"id": pool_id}
        )
    if exists is None or str(exists) == PoolStatus.DRAFT.value:
        raise HTTPException(404, "NOT_FOUND")
    return StreamingResponse(
        stream_pool_events(factory, pool_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def public_pool(db: AsyncSession, pool_id: UUID) -> Pool:
    pool = await db.get(Pool, pool_id)
    if pool is None or pool.status == PoolStatus.DRAFT:
        raise HTTPException(404, "NOT_FOUND")
    return pool
