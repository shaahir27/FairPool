"""Backend shapes shared by the search module (T03B02).

These are internal seams for the two retrieval backends, not ports: the public
port surface stays `SearchService` and `SearchIndexer` in ``fairpool.ports``.
"""

from __future__ import annotations

from typing import Final, Protocol
from uuid import UUID

from fairpool.adapters.search.projection import PublicDocument
from fairpool.ports import AsyncSession, SearchHit

# A retrieval score is the only float in the system (domain-ports.md section 3).
MAX_SEARCH_LIMIT: Final[int] = 100


class SearchBackendError(RuntimeError):
    """A backend could not answer. The reason is a fixed code, never a URL or key."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        self.reason = reason
        self.status = status
        super().__init__(f"search backend unavailable: {reason}")


class SearchBackend(Protocol):
    """Retrieval over the public projection; the Postgres one reads through the session."""

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
        semantic_only: bool = False,
    ) -> list[SearchHit]: ...


class DocumentBackend(Protocol):
    """A backend that stores documents (only Elastic does; the Postgres row is the document)."""

    async def upsert(self, document: PublicDocument) -> None: ...

    async def delete(self, *, doc_kind: str, doc_id: UUID) -> None: ...
