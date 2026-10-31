"""The ``search.index`` job body (T03B02; domain-ports.md section 5).

Payloads carry ids only, so the handler re-reads the projection from the
committed row; it upserts, and the indexer deletes when the row has left the
visible set. Phase 2's publish enqueues ``{"pool_id", "doc_kind", "doc_id"}``,
so ``doc_id`` falls back to ``pool_id`` for a pool document.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fairpool.ports import AsyncSession, SearchIndexer

JobHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


def search_index_handler(indexer: SearchIndexer) -> JobHandler:
    """Build the handler the worker registers under the ``search.index`` kind."""

    async def handle(session: AsyncSession, payload: dict[str, Any]) -> None:
        doc_kind = str(payload["doc_kind"])
        raw_id = payload.get("doc_id") or payload.get("pool_id")
        if raw_id is None:
            raise ValueError("search.index payload carries no document id")
        await indexer.upsert(session, doc_kind=doc_kind, doc_id=UUID(str(raw_id)))

    return handle
