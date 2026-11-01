"""Postgres ``pg_trgm`` search backend (T03B02; the always-runnable path and the fallback).

Covers both document kinds over the one public projection, so a pool hit and a
lot hit carry the same ``SearchHit`` shape as the Elastic backend returns.

shortcut: the pool and lot text is a computed expression, so the trigram GIN
index on ``pools.search_text`` cannot serve it and these queries scan the
catalog. Pool and lot counts are demo-scale (hundreds). A generated column with
its own GIN index is a migration and therefore a contract change request.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import desc, func, select

from fairpool.adapters.search.projection import (
    LOT_DOC,
    POOL_DOC,
    PUBLIC_LOT_STATUSES,
    PUBLIC_POOL_STATUSES,
    lot_content,
    pool_content,
)
from fairpool.db.models.catalog import Pool
from fairpool.db.models.pools import Lot
from fairpool.ports import AsyncSession, SearchHit

# ``word_similarity`` is the trigram measure for a short query inside a long
# document: ``similarity`` alone scores a one-word query against the whole pool
# and lot text at about 0.09. 0.1 keeps the unrelated matches S8 logged as noise
# (a wrong-product query scored 0.067 or less) and keeps the real ones (1.0).
MIN_SIMILARITY: Final = 0.1


def _score(content: object, q: str) -> Any:
    return func.greatest(func.similarity(content, q), func.word_similarity(q, content))


class PostgresSearchBackend:
    """Trigram retrieval over public pool and lot documents."""

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
        semantic_only: bool = False,
    ) -> list[SearchHit]:
        # semantic_only is an Elastic leg; trigrams are the fallback and answer either way.
        del semantic_only
        if not q.strip() or limit <= 0:
            return []
        hits: list[SearchHit] = []
        if POOL_DOC in kinds:
            hits += await self._pools(session, q, status, limit)
        if LOT_DOC in kinds:
            hits += await self._lots(session, q, status, limit)
        hits.sort(key=lambda hit: (-hit.score, hit.doc_id))
        return hits[:limit]

    async def _pools(
        self, session: AsyncSession, q: str, status: list[str] | None, limit: int
    ) -> list[SearchHit]:
        score = _score(pool_content(), q)
        statuses = _visible(status, PUBLIC_POOL_STATUSES)
        if not statuses:
            return []
        rows = (
            await session.execute(
                select(
                    Pool.id,
                    Pool.title,
                    func.coalesce(Pool.template["product_key"].astext, ""),
                    score.label("score"),
                )
                .where(Pool.status.in_(statuses), score > MIN_SIMILARITY)
                .order_by(desc("score"), Pool.id)
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(
                doc_id=str(pool_id),
                doc_kind=POOL_DOC,
                pool_id=UUID(str(pool_id)),
                lot_id=None,
                product_key=product_key,
                title=title,
                score=float(score),
            )
            for pool_id, title, product_key, score in rows
        ]

    async def _lots(
        self, session: AsyncSession, q: str, status: list[str] | None, limit: int
    ) -> list[SearchHit]:
        score = _score(lot_content(), q)
        statuses = _visible(status, PUBLIC_LOT_STATUSES)
        if not statuses:
            return []
        rows = (
            await session.execute(
                select(
                    Lot.id,
                    Lot.pool_id,
                    Pool.title,
                    func.coalesce(Pool.template["product_key"].astext, ""),
                    score.label("score"),
                )
                .join(Pool, Pool.id == Lot.pool_id)
                .where(
                    Lot.status.in_(statuses),
                    # A lot is public only while its pool is; DRAFT and CANCELLED never leak.
                    Pool.status.in_(sorted(PUBLIC_POOL_STATUSES)),
                    score > MIN_SIMILARITY,
                )
                .order_by(desc("score"), Lot.id)
                .limit(limit)
            )
        ).all()
        return [
            SearchHit(
                doc_id=str(lot_id),
                doc_kind=LOT_DOC,
                pool_id=UUID(str(pool_id)),
                lot_id=UUID(str(lot_id)),
                product_key=product_key,
                title=title,
                score=float(score),
            )
            for lot_id, pool_id, title, product_key, score in rows
        ]


def _visible(status: list[str] | None, public: frozenset[str]) -> list[str]:
    """The caller's status filter, never wider than the public set (rule 23)."""
    if status is None:
        return sorted(public)
    return sorted(set(status) & public)
