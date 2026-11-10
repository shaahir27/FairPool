"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.api import schemas
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.enums import EntryStatus, PoolMode, PoolStatus
from fairpool.db.session import create_engine
from fairpool.modules.intake.pipeline import latest_delivery
from fairpool.modules.pools.events import stream_pool_events
from fairpool.modules.pools.service import rules_document, summary

router = APIRouter()


def _entry_count():
    """The public entry count behind FR-UI-01's "trending".

    Not ``pools.entries_count``: that column is only written when the pool closes
    (``pool.close``), and a trending list is read while pools are open.
    """
    return (
        select(func.count())
        .select_from(PoolEntry)
        .where(PoolEntry.pool_id == Pool.id, PoolEntry.status != EntryStatus.WITHDRAWN)
        .correlate(Pool)
        .scalar_subquery()
    )


def _search_service(request: Request):
    """One routing search service per app: Postgres always, Elastic only if configured."""
    from fairpool.modules.search.service import build_search_service

    cached = getattr(request.app.state, "search_service", None)
    if cached is not None:
        return cached
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    built = build_search_service(settings)
    request.app.state.search_service = built
    return built


@router.get(
    "/api/v1/pools",
    response_model=list[schemas.PoolSummary],
    operation_id="pools_list",
)
async def pools_list(
    request: Request,
    q: str | None = Query(None, max_length=200),
    status: str | None = Query(None),
    sort: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=100),
    db: AsyncSession = Depends(database_session),
):
    # FR-SM-01: a SIMULATION pool is isolated by mode and never a public pool.
    entry_count = _entry_count().label("entry_count")
    query = select(Pool, entry_count).where(
        Pool.status != PoolStatus.DRAFT, Pool.mode == PoolMode.LIVE_SANDBOX
    )
    if status:
        if status not in PoolStatus.__members__ or status == "DRAFT":
            raise HTTPException(422, "VALIDATION_ERROR")
        query = query.where(Pool.status == PoolStatus(status))
    hits = None
    if q:
        # FR-IG-01: a `q` search goes through the search service, not a keyword LIKE.
        # The service has already chosen its backend and fallen back to the Postgres
        # trigram path if the configured one failed; retrieval never gates a result
        # (INT-1), so an empty answer here means nothing matched, not that search broke.
        hits = await _search_service(request).search(
            db, q=q, kinds=["pool"], status=None, limit=limit or 20
        )
        ids = [UUID(hit.doc_id) for hit in hits]
        if not ids:
            return []
        query = query.where(Pool.id.in_(ids))
    if sort not in (None, "closing", "title", "trending"):
        raise HTTPException(422, "VALIDATION_ERROR")
    if sort == "trending":
        # FR-UI-01 defines "trending" as the public entry count, so that is the whole
        # score: no invented weighting and no new field on the card. A withdrawn entry
        # has given up its place, so it does not count; the tie-break is the same
        # closing-then-id order the other sorts use, because a list that changes order
        # between two identical refreshes cannot be scanned.
        query = query.order_by(
            entry_count.desc(),
            Pool.timeline["close_at"].astext,
            Pool.id,
        )
    else:
        query = query.order_by(
            Pool.title if sort == "title" else Pool.timeline["close_at"].astext, Pool.id
        )
    rows = list((await db.execute(query.limit(limit or 20))).all())
    if hits is not None:
        # Keep the retrieval ranking the service produced; the SQL order above exists
        # to make the unranked paths deterministic.
        by_id = {row[0].id: row for row in rows}
        rows = [by_id[UUID(hit.doc_id)] for hit in hits if UUID(hit.doc_id) in by_id]
    return [summary(pool, entry_count=int(count)) for pool, count in rows]


@router.get(
    "/api/v1/pools/{pool_id}",
    response_model=schemas.PoolDetail,
    operation_id="pools_get",
)
async def pools_get(pool_id: UUID, db: AsyncSession = Depends(database_session)):
    pool = await public_pool(db, pool_id)
    entry_count = await db.scalar(
        select(func.count())
        .select_from(PoolEntry)
        .where(PoolEntry.pool_id == pool_id, PoolEntry.status != EntryStatus.WITHDRAWN)
    )
    return {
        **summary(pool, entry_count=entry_count),
        "template": pool.template,
        "lot_plan": pool.lot_plan,
        "timeline": pool.timeline,
        "rules_hash": pool.rules_hash,
        "latest_delivery": latest_delivery(pool.template),
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
            text("SELECT status FROM pools WHERE id = :id AND mode = 'LIVE_SANDBOX'"),
            {"id": pool_id},
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
    if pool is None or pool.status == PoolStatus.DRAFT or pool.mode != PoolMode.LIVE_SANDBOX:
        # FR-SM-01: a simulation answers exactly like an unknown id.
        raise HTTPException(404, "NOT_FOUND")
    return pool
