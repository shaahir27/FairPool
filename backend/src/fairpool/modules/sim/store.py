"""Bulk persistence for one simulation run (T08B04; I12).

Every write is a set-based statement: synthetic users come from one
``INSERT ... SELECT generate_series``, entries, receipts, lots and seats come from
``jsonb_to_recordset``. No ORM object is flushed per row, which is what keeps 10,000
entries inside the IT-8 ten-second budget on a loopback Postgres.

The simulation is a Member B module, so it may not import ``fairpool.infra`` (the
import checker's rule 5). The one audit row a run writes therefore repeats the
three-line chained-append primitive from ``infra/audit.py`` rather than importing its
Postgres implementation; the advisory key is the same, so the chain cannot fork.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import PoolMode, PoolStatus
from fairpool.domain import hashing
from fairpool.modules.sim.generator import PoolMeta, SimPlan, owner_id

#: The same advisory key as ``infra/audit.py``; one chain writer at a time.
AUDIT_LOCK = 0x46414952504F4F4C
ZERO_HASH = "0" * 64
RECEIPT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class SeatRow:
    id: UUID
    entry_id: UUID
    zone_id: str
    rank: int
    rank_hash: str
    lot_id: UUID | None
    status: str


def _payload(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, separators=(",", ":"), ensure_ascii=False)


async def insert_owner(session: AsyncSession, pool_id: UUID) -> UUID:
    """Insert the synthetic admin who owns the pool row (``created_by`` is NOT NULL)."""
    owner = owner_id(pool_id)
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'simulation-only', 'admin'::user_role, 'Simulation owner') "
            "ON CONFLICT DO NOTHING"
        ),
        {"id": owner, "email": f"sim-owner@{pool_id}.invalid"},
    )
    return owner


async def insert_pool(session: AsyncSession, *, pool_id: UUID, owner: UUID, meta: PoolMeta) -> Pool:
    """Create the SIMULATION pool in DRAFT; ``run_sim`` walks it to ALLOCATED."""
    pool = Pool(
        id=pool_id,
        mode=PoolMode.SIMULATION,
        status=PoolStatus.DRAFT,
        title=meta.title,
        template=meta.template,
        lot_plan=meta.lot_plan,
        timeline=meta.timeline,
        require_paypal_link=False,
        rule_version="allocation_v1",
        created_by=owner,
    )
    session.add(pool)
    await session.flush()
    return pool


async def insert_users(
    session: AsyncSession,
    ids: tuple[UUID, ...],
    *,
    email_prefix: str,
    email_suffix: str,
    role: str,
    display_prefix: str,
) -> None:
    """One ``generate_series`` statement for a whole synthetic identity population."""
    if not ids:
        return
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "SELECT (CAST(:ids AS jsonb) ->> (i - 1))::uuid, "
            ":prefix || (i - 1) || :suffix, 'simulation-only', "
            "CAST(:role AS user_role), :display || ' ' || i "
            "FROM generate_series(1, :count) AS i "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "ids": json.dumps([str(identifier) for identifier in ids]),
            "prefix": email_prefix,
            "suffix": email_suffix,
            "role": role,
            "display": display_prefix,
            "count": len(ids),
        },
    )


async def insert_identities(session: AsyncSession, plan: SimPlan) -> None:
    await insert_users(
        session,
        tuple(buyer.id for buyer in plan.buyers),
        email_prefix="sim-buyer-",
        email_suffix=f"@{plan.pool_id}.invalid",
        role="buyer",
        display_prefix="Simulated buyer",
    )
    await insert_users(
        session,
        tuple(merchant.user_id for merchant in plan.merchants),
        email_prefix="sim-merchant-",
        email_suffix=f"@{plan.pool_id}.invalid",
        role="merchant",
        display_prefix="Simulated seller",
    )
    merchant_rows = [
        {
            "id": str(merchant.id),
            "user_id": str(merchant.user_id),
            "display_name": merchant.display_name,
        }
        for merchant in plan.merchants
    ]
    await session.execute(
        text(
            "INSERT INTO merchants (id, user_id, display_name) "
            "SELECT x.id, x.user_id, x.display_name "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
            "AS x(id uuid, user_id uuid, display_name text) "
            "ON CONFLICT DO NOTHING"
        ),
        {"rows": _payload(merchant_rows)},
    )


async def insert_entries(session: AsyncSession, plan: SimPlan, *, received_at: datetime) -> None:
    """Entries and their signed receipts in two set-based statements."""
    received_text = received_at.astimezone(UTC).strftime(RECEIPT_FORMAT)
    entries: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for entry in plan.entries:
        entries.append(
            {
                "id": str(entry.id),
                "user_id": str(entry.user_id),
                "canonical_request": entry.canonical_request,
                "request_hash": entry.request_hash,
                "cap_cents": entry.cap_cents,
                "zone_id": entry.zone_id,
                "submitted_via": entry.submitted_via,
            }
        )
        payload = hashing.receipt_payload(
            str(plan.pool_id), str(entry.id), entry.commitment, received_text
        )
        receipts.append(
            {
                "entry_id": str(entry.id),
                "commitment": entry.commitment,
                "salt": entry.salt,
                "signature": hashing.sign_ed25519(payload, plan.signing_seed),
            }
        )
    await session.execute(
        text(
            "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, "
            "request_hash, cap_cents, zone_id, status, submitted_via, synthetic, received_at) "
            "SELECT x.id, :pool, x.user_id, x.canonical_request, x.request_hash, "
            "x.cap_cents, x.zone_id, 'ELIGIBLE'::entry_status, "
            "CAST(x.submitted_via AS submitted_via), true, :received_at "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x("
            "id uuid, user_id uuid, canonical_request jsonb, request_hash text, "
            "cap_cents bigint, zone_id text, submitted_via text)"
        ),
        {"pool": plan.pool_id, "rows": _payload(entries), "received_at": received_at},
    )
    await session.execute(
        text(
            "INSERT INTO entry_receipts (entry_id, commitment, salt, signature, signed_at) "
            "SELECT x.entry_id, x.commitment, x.salt, x.signature, :received_at "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) "
            "AS x(entry_id uuid, commitment text, salt text, signature text)"
        ),
        {"rows": _payload(receipts), "received_at": received_at},
    )


async def insert_lots(
    session: AsyncSession,
    *,
    pool_id: UUID,
    lots: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Lots are data from ``fairness.assign_lots``; this only persists them."""
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, "
            "min_seats, status, payment_router, bid_open_at, bid_close_at) "
            "SELECT x.id, :pool, x.zone_id, x.lot_index, x.lot_order, x.seats, "
            "x.min_seats, CAST(x.status AS lot_status), 'fake'::payment_router, "
            ":now, :now "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x("
            "id uuid, zone_id text, lot_index int, lot_order int, seats int, "
            "min_seats int, status text)"
        ),
        {"pool": pool_id, "rows": _payload(lots), "now": now},
    )


async def insert_allocations(session: AsyncSession, *, pool_id: UUID, seats: list[SeatRow]) -> None:
    rows = [
        {
            "id": str(seat.id),
            "entry_id": str(seat.entry_id),
            "zone_id": seat.zone_id,
            "rank": seat.rank,
            "rank_hash": seat.rank_hash,
            "lot_id": None if seat.lot_id is None else str(seat.lot_id),
            "status": seat.status,
        }
        for seat in seats
    ]
    await session.execute(
        text(
            "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, "
            "lot_id, status) "
            "SELECT x.id, :pool, x.entry_id, x.zone_id, x.rank, x.rank_hash, x.lot_id, "
            "CAST(x.status AS allocation_status) "
            "FROM jsonb_to_recordset(CAST(:rows AS jsonb)) AS x("
            "id uuid, entry_id uuid, zone_id text, rank int, rank_hash text, "
            "lot_id uuid, status text)"
        ),
        {"pool": pool_id, "rows": _payload(rows)},
    )


async def append_audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
) -> int:
    """One chained audit row, using the same formula and lock as ``infra/audit.py``."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK})
    created_at = await session.scalar(text("SELECT now()"))
    if not isinstance(created_at, datetime):
        raise RuntimeError("database clock returned a non-datetime value")
    previous = await session.scalar(text("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1"))
    prev_hash = str(previous) if previous else ZERO_HASH
    document = {
        "actor": actor,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload,
        # Same text as ``infra/audit.py`` so ``verify_chain`` recomputes this row.
        "created_at": created_at.strftime(RECEIPT_FORMAT),
    }
    digest = hashing.audit_hash(prev_hash, document)
    seq = await session.scalar(
        text(
            "INSERT INTO audit_log (prev_hash, hash, actor, action, subject_type, "
            "subject_id, payload, created_at) "
            "VALUES (:prev, :hash, :actor, :action, :subject_type, :subject_id, "
            "CAST(:payload AS jsonb), :created_at) RETURNING seq"
        ),
        {
            "prev": prev_hash,
            "hash": digest,
            "actor": actor,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": json.dumps(payload),
            "created_at": created_at,
        },
    )
    if seq is None:
        raise RuntimeError("audit insert returned no sequence")
    return int(seq)


def plan_digest(plan: SimPlan) -> str:
    """A stable fingerprint of the plan, stored with the measured result."""
    document = {
        "pool_id": str(plan.pool_id),
        "seed": plan.seed,
        "entries": len(plan.entries),
        "merchants": len(plan.merchants),
        "commitments": sorted(entry.commitment for entry in plan.entries),
    }
    return hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()


__all__ = [
    "SeatRow",
    "append_audit",
    "insert_allocations",
    "insert_entries",
    "insert_identities",
    "insert_lots",
    "insert_owner",
    "insert_pool",
    "insert_users",
    "plan_digest",
]
