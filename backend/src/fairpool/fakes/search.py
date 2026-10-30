"""Substring search fake over supplied public documents."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import UUID

from fairpool.ports import AsyncSession, SearchHit, SimilarityResult


@dataclass(frozen=True)
class SearchDocument:
    """A public pool or lot document; buyer and cap data never belong here."""

    doc_id: str
    doc_kind: str
    pool_id: UUID
    lot_id: UUID | None
    product_key: str
    title: str
    content: str
    status: str


@dataclass(frozen=True)
class SearchCall:
    q: str
    kinds: tuple[str, ...]
    status: tuple[str, ...] | None
    limit: int


@dataclass(frozen=True)
class SimilarityCall:
    lot_id: UUID
    text: str


class FakeSearch:
    """Filters documents by substring and returns scripted similarity results."""

    def __init__(
        self,
        *,
        documents: Iterable[SearchDocument] = (),
        similarity: Mapping[UUID, SimilarityResult] | None = None,
    ) -> None:
        self.documents = tuple(documents)
        self.similarity = dict(similarity or {})
        self.search_calls: list[SearchCall] = []
        self.similarity_calls: list[SimilarityCall] = []

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
    ) -> list[SearchHit]:
        self.search_calls.append(
            SearchCall(
                q=q,
                kinds=tuple(kinds),
                status=tuple(status) if status is not None else None,
                limit=limit,
            )
        )
        needle = q.casefold()
        hits: list[SearchHit] = []
        for document in self.documents:
            if document.doc_kind not in kinds:
                continue
            if status is not None and document.status not in status:
                continue
            haystack = f"{document.title} {document.content}".casefold()
            if needle and needle not in haystack:
                continue
            score = float(haystack.count(needle)) if needle else 1.0
            hits.append(
                SearchHit(
                    doc_id=document.doc_id,
                    doc_kind=document.doc_kind,
                    pool_id=document.pool_id,
                    lot_id=document.lot_id,
                    product_key=document.product_key,
                    title=document.title,
                    score=score,
                )
            )
        hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return hits[: max(limit, 0)]

    async def similarity_check(
        self,
        session: AsyncSession,
        *,
        lot_id: UUID,
        text: str,
    ) -> SimilarityResult:
        self.similarity_calls.append(SimilarityCall(lot_id=lot_id, text=text))
        return self.similarity.get(lot_id, SimilarityResult(None, None, None))

    def script_similarity(self, lot_id: UUID, result: SimilarityResult) -> None:
        self.similarity[lot_id] = result
