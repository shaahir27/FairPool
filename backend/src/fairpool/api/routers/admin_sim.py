"""Simulation and search administration routes (T08B04, T03B02)."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.search.projection import public_documents_select
from fairpool.api import schemas
from fairpool.api.deps import database_session, require_admin
from fairpool.db.models.platform import SimRun
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.sim.run import ensure_pool

router = APIRouter()


@router.post(
    "/api/v1/admin/sim/run",
    response_model=schemas.SimRunResponse,
    operation_id="admin_sim_run",
    dependencies=[Security(require_admin)],
)
async def admin_sim_run(
    payload: schemas.SimRunRequest,
    response: Response,
    db: AsyncSession = Depends(database_session),
) -> schemas.SimRunResponse:
    # Create the labelled pool and sim_runs row, enqueue sim.run, answer 202. The
    # transaction only creates the pool shell and the job: the measured allocation
    # runs in the worker, so an admin request for 10,000 entries returns immediately.
    # The status is set on the injected Response rather than in the decorator so the
    # frozen OpenAPI snapshot (which documents the later-phase stub's 200) stays
    # untouched; api.md fixes the runtime answer at 202.
    pool_id = uuid4()
    await ensure_pool(
        db,
        pool_id=pool_id,
        entries=payload.entries,
        seed=payload.seed,
    )
    sim_run_id = uuid4()
    db.add(
        SimRun(
            id=sim_run_id,
            pool_id=pool_id,
            seed=payload.seed,
            config={
                "entries": payload.entries,
                "merchants": payload.merchants,
                "seed": payload.seed,
            },
        )
    )
    await db.flush()
    # domain-ports.md section 5: concurrency key ``sim:{sim_run_id}``, no dedupe key.
    await PostgresJobQueue().enqueue(
        db,
        "sim.run",
        {"sim_run_id": str(sim_run_id)},
        concurrency_key=f"sim:{sim_run_id}",
    )
    response.status_code = 202
    return schemas.SimRunResponse(sim_run_id=sim_run_id, pool_id=pool_id)


@router.post(
    "/api/v1/admin/search/reindex",
    response_model=schemas.SearchReindexResponse,
    operation_id="admin_search_reindex",
    dependencies=[Security(require_admin)],
)
async def admin_search_reindex(
    page: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: AsyncSession = Depends(database_session),
) -> dict[str, object]:
    # T03B02 acceptance: reindex is admin-only, pages over rows and re-enqueues one
    # search.index job per document instead of rebuilding the index in this request.
    offset = page * page_size
    rows = (await db.execute(public_documents_select().limit(page_size + 1).offset(offset))).all()
    documents = rows[:page_size]
    jobs = PostgresJobQueue()
    enqueued = 0
    for doc_kind, doc_id in documents:
        key = f"search:{doc_kind}:{doc_id}"
        if (
            await jobs.enqueue(
                db,
                "search.index",
                {"doc_kind": doc_kind, "doc_id": str(doc_id)},
                concurrency_key=key,
                dedupe_key=key,
            )
            is not None
        ):
            enqueued += 1
    return {
        "page": page,
        "page_size": page_size,
        "documents": len(documents),
        "enqueued": enqueued,
        "has_more": len(rows) > len(documents),
    }
