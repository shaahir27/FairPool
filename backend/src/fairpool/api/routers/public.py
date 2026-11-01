"""Public surfaces: the close-time audit snapshot and the receipt signing key (T03B04).

``GET /api/v1/public/pools/{pool_id}/audit`` publishes, once the pool has closed,
exactly what the close transaction wrote: ``rules_hash``, ``rules_document``,
``pool_status``, ``entries_root``, ``entries_count``, the sorted commitments and the
audit checkpoints (``api.md`` "Public audit"; I11: the list is published before any
seed exists). It also carries the ``lots`` with their awards, the announced ``beacon``
and the ``seed_hex``/``seed_is_demo`` pair once the seed exists (T04A06); all of them
are gated on the close, because a seed or an allocation that predates the published
commitment list would describe a pool buyers are still entering.

Nothing personal crosses this route. It returns hashes and public catalog data only:
no salts, no caps, no user or entry ids, no addresses, and no entry ranks beyond the
lot's own range (FR-SL-06, I13). Before the pool closes, the commitment list, the
checkpoints, the lots and the seed are withheld entirely, because publishing any of
them early would let anyone read the pool's internals while buyers are still
entering it.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session
from fairpool.db.models.catalog import EntryReceipt, Pool, PoolEntry
from fairpool.db.models.enums import EntryStatus, PoolStatus
from fairpool.modules.pools.receipts import public_key_b64url, signing_seed
from fairpool.modules.pools.service import rules_document

router = APIRouter()

#: PS-03 and the states after it. The close is what makes the checkpoint chain and the
#: commitment list a published record (api.md "Public audit", CR-3 review m4);
#: CANCELLED is deliberately absent - a cancelled pool never reached that record.
AFTER_CLOSE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        str(PoolStatus.CLOSED),
        str(PoolStatus.SEEDED),
        str(PoolStatus.ALLOCATED),
        str(PoolStatus.RUNNING),
        str(PoolStatus.COMPLETED),
    }
)


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


async def _lots(db: AsyncSession, pool_id: UUID) -> list[dict[str, Any]]:
    """The pool's lots with their award, and the rank span each lot covers.

    ``rank_range`` is ``[lowest, highest]`` of the ranks the lot's allocations hold
    and is empty for a lot that holds none (a cancelled lot, or one allocated before
    its zone filled). The ranks are the pool's own ordering, not buyer data: no entry
    id, cap or user is readable from them.
    """
    lots = (
        await db.execute(
            text(
                "SELECT l.id, l.zone_id, l.lot_order, l.seats, l.status::text AS status, "
                "a.item_cents, a.tier_index, a.award_hash, a.valid_until, m.display_name "
                "FROM lots l "
                "LEFT JOIN awards a ON a.id = l.award_id "
                "LEFT JOIN merchants m ON m.id = a.merchant_id "
                "WHERE l.pool_id = :pool ORDER BY l.lot_order"
            ),
            {"pool": str(pool_id)},
        )
    ).all()
    spans = (
        await db.execute(
            text(
                "SELECT lot_id, min(rank), max(rank) FROM allocations "
                "WHERE pool_id = :pool AND lot_id IS NOT NULL GROUP BY lot_id"
            ),
            {"pool": str(pool_id)},
        )
    ).all()
    by_lot = {row[0]: [int(row[1]), int(row[2])] for row in spans}
    return [
        {
            "lot_id": row.id,
            "zone_id": str(row.zone_id),
            "lot_order": int(row.lot_order),
            "seats": int(row.seats),
            "status": str(row.status),
            "rank_range": by_lot.get(row.id, []),
            "award": (
                None
                if row.award_hash is None
                else {
                    "merchant_display_name": str(row.display_name or ""),
                    "item_cents": int(row.item_cents),
                    "tier_index": int(row.tier_index),
                    "award_hash": str(row.award_hash),
                    "valid_until": row.valid_until,
                }
            ),
        }
        for row in lots
    ]


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
        # The seed and the lots exist only after the close (pool.seed and
        # pool.allocate run after the published list), so they follow the same gate.
        "beacon": pool.beacon if closed else None,
        "seed_hex": pool.seed_hex if closed else None,
        "seed_is_demo": bool(pool.seed_is_demo) if closed else False,
        "lots": await _lots(db, pool_id) if closed else [],
        # After close only, and on the status rather than on a column (api.md "Public
        # audit" frames both as what the close publishes): the checkpoint chain of a
        # pool that is still open is a running internal log, not an audit surface, and
        # publishing it as soon as ``rules_hash`` existed leaked the pool's action
        # history to anonymous readers during its own open window.
        "audit_checkpoints": (
            await _checkpoints(db, pool_id) if str(pool.status) in AFTER_CLOSE_STATUSES else []
        ),
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
