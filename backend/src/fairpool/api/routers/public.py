"""Public surfaces: the close-time audit snapshot and the receipt signing key (T03B04).

``GET /api/v1/public/pools/{pool_id}/audit`` publishes, once the pool has closed,
exactly what the close transaction wrote: ``rules_hash``, ``rules_document``,
``pool_status``, ``entries_root``, ``entries_count``, the sorted commitments and the
audit checkpoints (``api.md`` "Public audit"; I11: the list is published before any
seed exists). ``lots``, ``beacon``, ``seed_hex``, ``seed_is_demo`` and ``award`` stay
at their empty schema defaults until Phase 4 (``T04A06``) produces that data: they
are never invented or guessed here.

Nothing personal crosses this route. It returns hashes only: no salts, no caps, no
user or entry ids, no addresses (FR-SL-06, I13). Before the pool closes, the
commitment list is withheld entirely, because publishing it early would let anyone
rank buyers before the rules snapshot is fixed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import EntryReceipt, Pool, PoolEntry
from fairpool.db.models.enums import EntryStatus
from fairpool.modules.pools.receipts import public_key_b64url, signing_seed
from fairpool.modules.pools.service import rules_document

router = APIRouter()


async def _commitments(db: AsyncSession, pool_id: UUID) -> list[str]:
    """The published sorted commitment list: ELIGIBLE entries of a closed pool only."""
    rows = (
        (
            await db.execute(
                select(EntryReceipt.commitment)
                .join(PoolEntry, PoolEntry.id == EntryReceipt.entry_id)
                .where(
                    PoolEntry.pool_id == pool_id,
                    PoolEntry.status == EntryStatus.ELIGIBLE,
                    # fairness-and-hashing.md §3: ascending as hex strings.
                )
                .order_by(EntryReceipt.commitment)
            )
        )
        .scalars()
        .all()
    )
    return [str(row) for row in rows]


async def _checkpoints(db: AsyncSession, pool_id: UUID) -> list[dict[str, Any]]:
    """Action plus chain hash for this pool's audit rows (fairness-and-hashing.md §8)."""
    rows = (
        await db.execute(
            text(
                "SELECT action, hash FROM audit_log WHERE subject_type = 'pool' "
                "AND subject_id = :id ORDER BY seq"
            ),
            {"id": str(pool_id)},
        )
    ).all()
    return [{"action": str(action), "hash": str(chain_hash)} for action, chain_hash in rows]


@router.get(
    "/api/v1/public/pools/{pool_id}/audit",
    response_model=schemas.PublicAuditResponse,
    operation_id="public_audit",
)
async def public_audit(pool_id: UUID, db: AsyncSession = Depends(database_session)):
    pool = await db.scalar(select(Pool).where(Pool.id == pool_id))
    if pool is None or pool.rules_hash is None:
        # A DRAFT pool has no frozen rules document and is not public at all: the
        # answer is the same as for an unknown id, so nothing about it leaks.
        raise HTTPException(404, "NOT_FOUND")
    closed = pool.entries_root is not None
    return {
        "rules_hash": pool.rules_hash,
        "rules_document": rules_document(pool),
        "pool_status": str(pool.status),
        "entries_root": pool.entries_root,
        "entries_count": pool.entries_count,
        # After close only: the sorted list is the published record of who was
        # eligible, and before the snapshot exists there is nothing to publish.
        "commitments": await _commitments(db, pool_id) if closed else [],
        "audit_checkpoints": await _checkpoints(db, pool_id),
    }


@router.get(
    "/api/v1/public/keys",
    response_model=schemas.PublicKeysResponse,
    operation_id="public_keys",
)
async def public_keys(request: Request):
    # The Ed25519 public key derived from RECEIPT_SIGNING_KEY and nothing else:
    # the private seed never leaves the signing call (I14).
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    return {
        "algorithm": "ed25519",
        "public_key": public_key_b64url(
            signing_seed(settings.receipt_signing_key.get_secret_value())
        ),
    }
