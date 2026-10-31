"""``SearchIndexer``: repeatable writes of the public projection, keyed by row id (T03B02).

Postgres is the source of truth, so a pool or lot row *is* its document: the only
index that needs writing is Elastic's. The projection is always re-read from the
committed row, never taken from the job payload, which carries ids only (CR-3).
An Elastic write failure is logged and swallowed: the trigram path already answers,
and no user action or publication waits on it.
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from fairpool.adapters.search.base import DocumentBackend, SearchBackendError
from fairpool.adapters.search.elastic import ElasticSearchBackend
from fairpool.adapters.search.projection import PublicDocument, read_public_document
from fairpool.config import Settings
from fairpool.ports import AsyncSession

logger = logging.getLogger("fairpool.search")

DOC_KINDS: Final[frozenset[str]] = frozenset({"pool", "lot"})


class SearchDocumentIndexer:
    """Implements the ``SearchIndexer`` port for the public document set."""

    def __init__(self, *, elastic: DocumentBackend | None = None) -> None:
        self.elastic = elastic

    async def upsert(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None:
        document = await read_public_document(session, doc_kind=doc_kind, doc_id=doc_id)
        if document is None:
            # The row is gone or private: it left the visible set, so the document goes too.
            await self._delete(doc_kind, doc_id)
            return
        await self._write(document)

    async def delete(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None:
        del session
        await self._delete(doc_kind, doc_id)

    async def _write(self, document: PublicDocument) -> None:
        if self.elastic is None:
            return
        try:
            await self.elastic.upsert(document)
        except SearchBackendError as exc:
            logger.warning(
                "search.index_skipped reason=%s doc_kind=%s doc_id_present=true",
                exc.reason,
                document.doc_kind,
            )

    async def _delete(self, doc_kind: str, doc_id: UUID) -> None:
        if doc_kind not in DOC_KINDS:
            raise ValueError(f"unknown search document kind: {doc_kind}")
        if self.elastic is None:
            return
        try:
            await self.elastic.delete(doc_kind=doc_kind, doc_id=doc_id)
        except SearchBackendError as exc:
            logger.warning(
                "search.delete_skipped reason=%s doc_kind=%s doc_id_present=true",
                exc.reason,
                doc_kind,
            )


def build_search_indexer(settings: Settings) -> SearchDocumentIndexer:
    """The composition seam for ``wiring.py``: no Elastic client unless it is selected."""
    elastic: ElasticSearchBackend | None = None
    if settings.search_backend == "elastic":
        elastic = ElasticSearchBackend(
            url=settings.elasticsearch_url,
            api_key=settings.elasticsearch_api_key.get_secret_value(),
            inference_id=settings.elastic_inference_id,
            index_prefix=settings.elastic_index_prefix,
            timeout_ms=settings.search_timeout_ms,
        )
    return SearchDocumentIndexer(elastic=elastic)
