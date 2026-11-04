"""Advisory wrong-product check after a confirmed bid (T07B05; INT-1).

``ai-schemas.md`` section 7: the quote's own words are searched against the open
lots, and only when the bid's lot is not ranked first *and* the top hit is a
different product is a ``LOW_SIMILARITY`` WARNING written. It is advice for the
merchant and ops: it never edits a field, never changes a status and never gates
the award. A search that is down, empty text or a disabled switch means no flag.

The check runs as a background task after the confirm's response, on its own
session and behind a try/except: a retrieval outage must not fail or delay a
merchant's confirm (rule 23).
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.config import Settings
from fairpool.db.models.auction import Bid, BidFlag, BidRevision
from fairpool.db.models.pools import Lot
from fairpool.domain import hashing
from fairpool.modules.auction.flags import EVIDENCE_LIMIT, record_low_similarity
from fairpool.modules.auction.reconcile import _free_text
from fairpool.modules.intake.run_log import PostgresAiRunLogger
from fairpool.ports import AiRunLogger, SearchService

logger: Final[logging.Logger] = logging.getLogger("fairpool.search.similarity")


class LowSimilarityAdvisor:
    """Turns one ``SimilarityResult`` into at most one WARNING flag."""

    def __init__(self, *, search: SearchService, run_logger: AiRunLogger, model: str) -> None:
        self.search = search
        self.run_logger = run_logger
        self.model = model

    async def check(
        self,
        session: AsyncSession,
        *,
        bid: Bid,
        revision: BidRevision,
        lot: Lot,
    ) -> BidFlag | None:
        text = _free_text(revision)
        if not text:
            # Structured fields only: nothing to compare, so no flag (section 7).
            return None
        result = await self.search.similarity_check(session, lot_id=lot.id, text=text)
        own_product = str(revision.structured.get("product_key") or "")
        if result.own_rank == 1:
            return None
        if result.top_product_key is None or result.top_product_key == own_product:
            return None
        rank = result.own_rank if result.own_rank is not None else "outside the top hits"
        evidence = (
            f"Closest match was product {result.top_product_key!r} (lot {result.top_lot_id}); "
            f"this lot ranked {rank}."
        )[:EVIDENCE_LIMIT]
        return await record_low_similarity(
            session,
            revision=revision,
            evidence=evidence,
            run_logger=self.run_logger,
            model=self.model,
            input_hash=hashing.request_hash(
                {"task": "SIM_TEXT", "lot_id": str(lot.id), "text": text}
            ),
        )


async def advise_confirmed_bid(
    session: AsyncSession,
    *,
    settings: Settings | None,
    search: SearchService,
    bid_id: UUID,
) -> None:
    """The post-commit hook both confirm edges call; it never raises (INT-1).

    The caller hands it a fresh session (a background task), so the advisory rows
    commit on their own unit of work after the confirm is durable.
    """
    if settings is None or not settings.similarity_check_enabled:
        return
    try:
        bid = await session.get(Bid, bid_id)
        if bid is None:
            return
        revision = await session.scalar(
            select(BidRevision).where(
                BidRevision.bid_id == bid.id,
                BidRevision.revision == int(bid.current_revision),
            )
        )
        lot = await session.get(Lot, bid.lot_id)
        if revision is None or lot is None:
            return
        advisor = LowSimilarityAdvisor(
            search=search, run_logger=PostgresAiRunLogger(), model=settings.ai_model_sim
        )
        await advisor.check(session, bid=bid, revision=revision, lot=lot)
        await session.commit()
    except Exception as exc:  # noqa: BLE001 - search never fails a merchant action
        logger.warning(
            "auction.similarity_check_skipped bid_id=%s reason=%s",
            bid_id,
            type(exc).__name__,
        )
