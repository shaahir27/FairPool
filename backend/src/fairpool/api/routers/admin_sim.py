"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.search.projection import public_documents_select
from fairpool.api import schemas
from fairpool.api.deps import database_session, require_admin
from fairpool.infra.jobs import PostgresJobQueue

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
