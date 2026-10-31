"""``SearchService``: one backend at a time, always the same shape, never an error (T03B02).

Retrieval only (rule 23, FR-IG-01): the result is advisory, an outage answers with
the Postgres trigram path, and nothing here can fail a user action or gate an
award. A hit is returned only after it is hydrated against current Postgres
visibility, so a stale or private document is dropped rather than shown, and the
fallback tops the page up so the caller still gets ``limit`` results where they
exist (CR-3 "Sync details", OD-P3-3). The one exception is the semantic-only
advisory leg: with a semantic backend configured and down it is skipped, never
measured by a trigram stand-in.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Final
from uuid import UUID

from fairpool.adapters.search.base import SearchBackend
from fairpool.adapters.search.elastic import ElasticSearchBackend
from fairpool.adapters.search.postgres import PostgresSearchBackend
from fairpool.adapters.search.projection import (
    LOT_DOC,
    OPEN_LOT_STATUSES,
    read_public_document,
)
from fairpool.config import Settings
from fairpool.ports import AsyncSession, SearchHit, SimilarityResult

logger = logging.getLogger("fairpool.search")

# The advisory check compares a quote against the lots still open for bidding.
SIMILARITY_TOP_N: Final[int] = 5


class SearchRoutingService:
    """Implements the ``SearchService`` port over the configured backend plus the fallback."""

    def __init__(
        self,
        *,
        postgres: PostgresSearchBackend,
        elastic: ElasticSearchBackend | None = None,
        backend: str = "postgres",
        similarity_check_enabled: bool = True,
    ) -> None:
        self.postgres = postgres
        self.elastic = elastic
        self.backend = backend
        self.similarity_check_enabled = similarity_check_enabled

    @property
    def _primary(self) -> SearchBackend:
        if self.backend == "elastic" and self.elastic is not None:
            return self.elastic
        return self.postgres

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
    ) -> list[SearchHit]:
        return await self._retrieve(
            session, q=q, kinds=kinds, status=status, limit=limit, semantic_only=False
        )

    async def similarity_check(
        self, session: AsyncSession, *, lot_id: UUID, text: str
    ) -> SimilarityResult:
        if not self.similarity_check_enabled or not text.strip():
            # Skipped: no flag, no error (ai-schemas.md section 7).
            return SimilarityResult(None, None, None)
        hits = await self._retrieve(
            session,
            q=text,
            kinds=[LOT_DOC],
            status=list(OPEN_LOT_STATUSES),
            limit=SIMILARITY_TOP_N,
            semantic_only=True,
        )
        own_rank = next((index + 1 for index, hit in enumerate(hits) if hit.lot_id == lot_id), None)
        top = hits[0] if hits else None
        return SimilarityResult(
            own_rank,
            top.lot_id if top else None,
            top.product_key if top else None,
        )

    async def _retrieve(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
        semantic_only: bool,
    ) -> list[SearchHit]:
        primary = self._primary
        hits = await self._query(
            session,
            primary,
            q=q,
            kinds=kinds,
            status=status,
            limit=limit,
            semantic_only=semantic_only,
        )
        kept = await self._hydrate(session, hits, status=status)
        # ai-schemas.md section 7: the advisory check "runs a semantic-only query" and is
        # "skipped (no flag) if search is unavailable". A trigram stand-in would raise a
        # LOW_SIMILARITY WARNING measured by a different metric, so this leg tops up from
        # the fallback only when the fallback is the configured semantic path (OD-P3-3).
        if not semantic_only and len(kept) < limit and primary is not self.postgres:
            extra = await self._query(
                session,
                self.postgres,
                q=q,
                kinds=kinds,
                status=status,
                limit=limit,
                semantic_only=False,
            )
            seen = {hit.doc_id for hit in kept}
            kept += [
                hit
                for hit in await self._hydrate(session, extra, status=status)
                if hit.doc_id not in seen
            ]
        return kept[: max(limit, 0)]

    async def _query(
        self,
        session: AsyncSession,
        backend: SearchBackend,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
        semantic_only: bool,
    ) -> list[SearchHit]:
        try:
            return await backend.search(
                session, q=q, kinds=kinds, status=status, limit=limit, semantic_only=semantic_only
            )
        except Exception as exc:
            # A search outage is never a user-facing error: log, answer without it.
            # The query text stays out of the log: it can carry untrusted quote text.
            logger.warning(
                "search.backend_failed backend=%s reason=%s kinds=%s limit=%s",
                type(backend).__name__,
                getattr(exc, "reason", type(exc).__name__),
                ",".join(kinds),
                limit,
            )
            return []

    async def _hydrate(
        self, session: AsyncSession, hits: list[SearchHit], *, status: list[str] | None
    ) -> list[SearchHit]:
        kept: list[SearchHit] = []
        for hit in hits:
            try:
                document = await read_public_document(
                    session, doc_kind=hit.doc_kind, doc_id=UUID(hit.doc_id)
                )
            except (ValueError, TypeError):
                continue  # not a document id this service knows: drop it
            if document is None:
                continue  # stale or private: dropped, never shown (CR-3)
            if status is not None and document.status not in status:
                continue  # its status moved since it was indexed
            kept.append(replace(hit, product_key=document.product_key, title=document.title))
        return kept


def build_search_service(settings: Settings) -> SearchRoutingService:
    """The composition seam for ``wiring.py``: Postgres always, Elastic only when configured."""
    elastic: ElasticSearchBackend | None = None
    if settings.search_backend == "elastic":
        elastic = ElasticSearchBackend(
            url=settings.elasticsearch_url,
            api_key=settings.elasticsearch_api_key.get_secret_value(),
            inference_id=settings.elastic_inference_id,
            index_prefix=settings.elastic_index_prefix,
            timeout_ms=settings.search_timeout_ms,
        )
    return SearchRoutingService(
        postgres=PostgresSearchBackend(),
        elastic=elastic,
        backend=settings.search_backend,
        similarity_check_enabled=settings.similarity_check_enabled,
    )
