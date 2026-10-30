"""Recording search indexer fake."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fairpool.ports import AsyncSession


@dataclass(frozen=True)
class IndexOperation:
    doc_kind: str
    doc_id: UUID


class FakeSearchIndexer:
    """Records upserts and deletes without a search backend."""

    def __init__(self) -> None:
        self.upserts: list[IndexOperation] = []
        self.deletes: list[IndexOperation] = []

    async def upsert(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None:
        self.upserts.append(IndexOperation(doc_kind=doc_kind, doc_id=doc_id))

    async def delete(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None:
        self.deletes.append(IndexOperation(doc_kind=doc_kind, doc_id=doc_id))
