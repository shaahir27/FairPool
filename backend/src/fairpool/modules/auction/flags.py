"""The only writer of the advisory ``LOW_SIMILARITY`` flag (T07B05; INT-1).

``bid_flags.ai_run_id`` is NOT NULL (``db-schema.md``), so the row is written with
the ``ai_runs`` record that documents the retrieval it came from. No model runs:
the contract's similarity check is a search query, so the run row carries the
configured retrieval model name, zero tokens and the hash of what was searched.
An advisory flag is never a status change (``ai-schemas.md`` section 7): nothing
here may touch ``bid.status``.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import BidFlag, BidRevision
from fairpool.db.models.enums import FlagCode, FlagSeverity
from fairpool.ports import AiRunLogger

LOW_SIMILARITY: Final[str] = FlagCode.LOW_SIMILARITY.value
WARNING: Final[str] = FlagSeverity.WARNING.value

#: The evidence column's limit in ``db-schema.md``.
EVIDENCE_LIMIT: Final[int] = 200

#: ``ai_runs.prompt_version`` for a retrieval check that has no prompt. The task value
#: is ``SIM_TEXT``: it is the only ``ai_task`` the frozen enum offers for a similarity
#: run (``db-schema.md`` "ai_task").
TASK: Final[str] = "SIM_TEXT"
PROMPT_VERSION: Final[str] = "similarity_v1"


async def record_low_similarity(
    session: AsyncSession,
    *,
    revision: BidRevision,
    evidence: str,
    run_logger: AiRunLogger,
    model: str,
    input_hash: str,
) -> BidFlag:
    """One WARNING row per revision: a re-run of the check returns the row it wrote."""
    existing = await session.scalar(
        select(BidFlag).where(
            BidFlag.bid_revision_id == revision.id, BidFlag.code == FlagCode.LOW_SIMILARITY
        )
    )
    if existing is not None:
        return existing
    run_id: UUID = await run_logger.log(
        session,
        task=TASK,
        model=model,
        prompt_version=PROMPT_VERSION,
        input_hash=input_hash,
        output=None,
        ok=True,
        error=None,
        latency_ms=0,
        tokens_in=0,
        tokens_out=0,
    )
    row = BidFlag(
        id=uuid4(),
        bid_revision_id=revision.id,
        ai_run_id=run_id,
        code=FlagCode.LOW_SIMILARITY,
        severity=FlagSeverity.WARNING,
        field="product_key",
        evidence=evidence[:EVIDENCE_LIMIT],
    )
    session.add(row)
    await session.flush()
    return row
