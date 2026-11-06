"""Public surfaces: the close-time audit snapshot and the receipt signing key (T03B04).

``GET /api/v1/public/pools/{pool_id}/audit`` publishes, once the pool has closed,
exactly what the close transaction wrote: ``rules_hash``, ``rules_document``,
``pool_status``, ``entries_root``, ``entries_count``, the sorted commitments and the
audit checkpoints (``api.md`` "Public audit"; I11: the list is published before any
seed exists). It also carries the ``lots`` with their awards, the announced ``beacon``
and the ``seed_hex``/``seed_is_demo`` pair, the per-lot ``bids_root`` written at
``lot.bid_close`` and a signed ``checkpoint`` over the chain head (CR-11).

Two gates apply. ``commitments``, ``entries_root`` and ``lots`` follow the close,
because a seed or an allocation that predates the published commitment list would
describe a pool buyers are still entering. ``beacon``, ``seed_hex``,
``audit_checkpoints`` and ``checkpoint`` additionally wait until no lot is still
``PLANNED`` or ``BIDDING``: the tie-break is hash(seed, lot, merchant), so revealing
the seed mid-auction hands every merchant its exact tie-break position for free, and
the bid rows in the chain disclose how many bids a lot received and when.

Nothing personal crosses this route. It returns hashes and public catalog data only:
no salts, no caps, no user or entry ids, no addresses, no bid contents, and no entry
ranks beyond the lot's own range (FR-SL-06, I13). Before the pool closes, the
commitment list, the checkpoints, the lots and the seed are withheld entirely, because
publishing any of them early would let anyone read the pool's internals while buyers
are still entering it.
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
from fairpool.db.models.enums import EntryStatus, PoolMode, PoolStatus
from fairpool.domain import hashing
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


async def _chain_rows(db: AsyncSession, pool_id: UUID) -> list[tuple[int, str, str]]:
    """``(seq, action, hash)`` for this pool's audit rows across three subjects.

    CR-11 widened the pool-only filter. A bid or lot row that a privileged writer
    inserted after the deadline was invisible while the published chain covered only
    ``subject_type='pool'``, which made "tamper-evident to someone holding a published
    checkpoint" uncheckable for exactly the rows an award depends on. Bid contents are
    still never read here: only the action name and the chain hash cross the wire.
    """
    rows = await db.execute(
        text(
            # subject_id is TEXT while lots.id and bids.id are UUID, so each id is
            # cast before the comparison; Postgres has no text = uuid operator.
            "SELECT seq, action, hash FROM audit_log "
            "WHERE (subject_type = 'pool' AND subject_id = :pool) "
            "   OR (subject_type = 'lot' AND subject_id IN "
            "        (SELECT id::text FROM lots WHERE pool_id = CAST(:pool AS uuid))) "
            "   OR (subject_type = 'bid' AND subject_id IN "
            "        (SELECT id::text FROM bids WHERE lot_id IN "
            "         (SELECT id FROM lots WHERE pool_id = CAST(:pool AS uuid)))) "
            "ORDER BY seq"
        ),
        {"pool": str(pool_id)},
    )
    return [(int(seq), str(action), str(chain_hash)) for seq, action, chain_hash in rows]


async def _checkpoints(db: AsyncSession, pool_id: UUID) -> list[dict[str, Any]]:
    """Action plus chain hash for this pool's audit rows (fairness-and-hashing.md §8)."""
    return [
        {"action": action, "hash": chain_hash}
        for _, action, chain_hash in await _chain_rows(db, pool_id)
    ]


async def _bid_closes(db: AsyncSession, pool_id: UUID) -> dict[str, dict[str, Any]]:
    """Each lot's LS-02 payload, keyed by lot id, or absent while bidding is open.

    ``lot.bid_close`` writes ``bids_root`` and ``bids_count`` into its audit payload
    (CR-11), so the commitment over the bid set is read back from the same row that
    the chain already hashes. Force-award never writes LS-02, so such a lot simply
    has no entry here and the page reports nothing rather than an empty set.
    """
    rows = await db.execute(
        text(
            "SELECT subject_id, payload FROM audit_log "
            "WHERE subject_type = 'lot' AND action = 'lot.bid_closed' "
            "AND subject_id IN (SELECT id::text FROM lots WHERE pool_id = CAST(:pool AS uuid)) "
            "ORDER BY seq"
        ),
        {"pool": str(pool_id)},
    )
    return {str(subject_id): dict(payload or {}) for subject_id, payload in rows}


async def _lots(
    db: AsyncSession,
    pool_id: UUID,
    closes: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
    closes = closes or {}
    return [
        {
            "lot_id": row.id,
            "zone_id": str(row.zone_id),
            "lot_order": int(row.lot_order),
            "seats": int(row.seats),
            "status": str(row.status),
            "rank_range": by_lot.get(row.id, []),
            "bids_root": closes.get(str(row.id), {}).get("bids_root"),
            "bids_count": closes.get(str(row.id), {}).get("bids_count"),
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
async def public_audit(
    pool_id: UUID,
    request: Request,
    db: AsyncSession = Depends(database_session),
):
    # FR-SM-01: a SIMULATION pool has an audit trail only inside the simulation; its
    # id answers exactly like an unknown one on every public surface.
    pool = await db.scalar(
        select(Pool).where(Pool.id == pool_id, Pool.mode == PoolMode.LIVE_SANDBOX)
    )
    if pool is None or pool.rules_hash is None:
        # A DRAFT pool has no frozen rules document and is not public at all: the
        # answer is the same as for an unknown id, so nothing about it leaks.
        raise HTTPException(404, "NOT_FOUND")
    closed = pool.entries_root is not None
    # CR-11 reveal gate. tiebreak_hash(seed_hex, lot_id, merchant_id) is pure
    # arithmetic, so publishing the seed while any lot was still PLANNED or BIDDING
    # let a merchant read their own tie-break position before pricing anything. The
    # checkpoint chain is held to the same gate because its bid rows disclose how many
    # bids a lot received and when.
    # Two different leaks, two different windows. The seed feeds
    # tiebreak_hash(seed, lot, merchant), so it waits until no lot can still be bid on
    # (PLANNED or BIDDING). The checkpoint chain carries bid rows, which disclose how
    # many bids landed and when -- those exist only once bidding is open, so the chain
    # waits for BIDDING alone and keeps publishing the close subset that T04A06
    # requires while lots are still PLANNED.
    # execute().one(), not scalar(): db.scalar() returns only the first column, so
    # reading .pre/.open off it would silently evaluate to zero and reveal everything.
    waiting = (
        await db.execute(
            text(
                "SELECT count(*) FILTER (WHERE status::text IN ('PLANNED','BIDDING')) AS pre, "
                "count(*) FILTER (WHERE status::text = 'BIDDING') AS open "
                "FROM lots WHERE pool_id = :pool"
            ),
            {"pool": str(pool_id)},
        )
    ).one()
    seed_revealed = closed and int(waiting.pre or 0) == 0
    chain_revealed = int(waiting.open or 0) == 0
    closes = await _bid_closes(db, pool_id) if closed else {}
    after_close = str(pool.status) in AFTER_CLOSE_STATUSES
    return {
        "rules_hash": pool.rules_hash,
        "rules_document": rules_document(pool),
        "pool_status": str(pool.status),
        "entries_root": pool.entries_root,
        "entries_count": pool.entries_count,
        # After close only: the sorted list is the published record of who was
        # eligible, and before the snapshot exists there is nothing to publish.
        "commitments": await _commitments(db, pool_id) if closed else [],
        "beacon": pool.beacon if seed_revealed else None,
        "seed_hex": pool.seed_hex if seed_revealed else None,
        "seed_is_demo": bool(pool.seed_is_demo) if seed_revealed else False,
        "lots": await _lots(db, pool_id, closes) if closed else [],
        # After close only, and on the status rather than on a column (api.md "Public
        # audit" frames both as what the close publishes): the checkpoint chain of a
        # pool that is still open is a running internal log, not an audit surface, and
        # publishing it as soon as ``rules_hash`` existed leaked the pool's action
        # history to anonymous readers during its own open window.
        "audit_checkpoints": await _checkpoints(db, pool_id)
        if after_close and chain_revealed
        else [],
        "checkpoint": (
            await _checkpoint_proof(request, db, pool, closes)
            if after_close and chain_revealed
            else None
        ),
    }


async def _checkpoint_proof(
    request: Request,
    db: AsyncSession,
    pool: Pool,
    closes: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """CR-11: the chain head plus the published roots, signed at read time.

    ``audit_hash`` uses no secret and the append-only trigger blocks UPDATE and DELETE
    but not INSERT, so a self-consistent chain proves nothing on its own. The signature
    is what turns "these rows hash together" into "FairPool published this head at the
    moment it was read". Nothing is stored: recomputing per read means the proof cannot
    fall out of step with the rows it describes.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    settings = getattr(state, "settings", None)
    if settings is None:
        # No signing context, so no proof: an unsigned checkpoint would claim more than
        # it can support, and the route is also callable outside HTTP by tests.
        return None
    chain = await _chain_rows(db, pool.id)
    head_seq, head_hash = (chain[-1][0], chain[-1][2]) if chain else (None, None)
    payload = {
        "v": 1,
        "pool_id": str(pool.id),
        "entries_root": pool.entries_root,
        "bids_roots": {
            str(lot_id): close.get("bids_root") for lot_id, close in sorted(closes.items())
        },
        "head_seq": head_seq,
        "head_hash": head_hash,
    }
    seed = signing_seed(settings.receipt_signing_key.get_secret_value())
    # sign_ed25519 canonicalises internally; passing canonical_json's string here would
    # make it dict() a str.
    return {**payload, "signature": hashing.sign_ed25519(payload, seed)}


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
