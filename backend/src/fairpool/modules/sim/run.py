"""The measured simulation run: create, close, seed, allocate, persist (T08B04).

The measured path contains no AI call, no job enqueue and no provider traffic. It is
one transaction that:

1. creates (or reuses) a ``SIMULATION`` pool and walks it through the pool whitelist
   to ``ALLOCATED``;
2. bulk-writes synthetic users, merchants, entries, receipts and signed receipts;
3. derives the demo seed and runs the pure ``fairness.assign_lots``;
4. bulk-writes lots and seats, then writes exactly one audit row.

Point 3 is the same function the live backend uses, so the run measures the real
allocation cost rather than a simulation-only shortcut. AI text variety happens in
``handlers.py`` after the timer stops and never touches the measured path (FR-AI-03).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import PoolStatus
from fairpool.domain import fairness, hashing
from fairpool.domain.errors import ApplicationError
from fairpool.domain.states import assert_transition
from fairpool.modules.sim import store
from fairpool.modules.sim.generator import (
    SimMessage,
    allocation_id,
    build_plan,
    pool_metadata,
)

logger = logging.getLogger("fairpool.sim")


@dataclass(frozen=True)
class SimResult:
    """What one run measured and wrote; ``samples`` feed the post-measurement AI step."""

    pool_id: UUID
    seed: int
    entries: int
    merchants: int
    seated: int
    waitlisted: int
    lots: int
    duration_ms: int
    plan_sha256: str
    samples: tuple[SimMessage, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pool_id": str(self.pool_id),
            "seed": self.seed,
            "entries": self.entries,
            "merchants": self.merchants,
            "seated": self.seated,
            "waitlisted": self.waitlisted,
            "lots": self.lots,
            "measured_ms": self.duration_ms,
            "plan_sha256": self.plan_sha256,
            "label": "SIMULATED",
        }


def _config(payload: Mapping[str, Any]) -> tuple[int, int, int]:
    entries = payload.get("entries")
    if isinstance(entries, bool) or not isinstance(entries, int) or entries < 1:
        raise ApplicationError("VALIDATION_ERROR", "entries must be a positive integer")
    merchants = payload.get("merchants")
    if isinstance(merchants, bool) or not isinstance(merchants, int) or merchants < 1:
        raise ApplicationError("VALIDATION_ERROR", "merchants must be a positive integer")
    seed = payload.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ApplicationError("VALIDATION_ERROR", "seed must be an integer")
    return entries, merchants, seed


def _move(pool: Pool, to: str) -> None:
    """Walk the pool whitelist; the simulation still may not invent a transition."""
    assert_transition("pool", str(pool.status), to)
    pool.status = PoolStatus(to)


async def ensure_pool(session: AsyncSession, *, pool_id: UUID, entries: int, seed: int) -> Pool:
    """Create the pool row cheaply (route) or find the one already created."""
    existing = await session.get(Pool, pool_id, with_for_update=True)
    if existing is not None:
        return existing
    owner = await store.insert_owner(session, pool_id)
    meta = pool_metadata(entries=entries, seed=seed)
    return await store.insert_pool(session, pool_id=pool_id, owner=owner, meta=meta)


async def _existing_result(
    session: AsyncSession, *, pool: Pool, seed: int, started: float
) -> SimResult:
    """A retry after commit reads the stored result instead of writing a second run."""
    rows = (
        await session.execute(
            text(
                "SELECT status::text, count(*) FROM allocations WHERE pool_id = :pool "
                "GROUP BY status"
            ),
            {"pool": pool.id},
        )
    ).all()
    seated = sum(int(total) for status, total in rows if str(status) == "SEATED")
    waitlisted = sum(int(total) for status, total in rows if str(status) == "WAITLISTED")
    entries = await session.scalar(
        text("SELECT count(*) FROM pool_entries WHERE pool_id = :pool"), {"pool": pool.id}
    )
    lots = await session.scalar(
        text("SELECT count(*) FROM lots WHERE pool_id = :pool"), {"pool": pool.id}
    )
    return SimResult(
        pool_id=pool.id,
        seed=seed,
        entries=int(entries or 0),
        merchants=0,
        seated=seated,
        waitlisted=waitlisted,
        lots=int(lots or 0),
        duration_ms=int((time.perf_counter() - started) * 1000),
        plan_sha256="",
        samples=(),
    )


async def run_sim(
    session: AsyncSession,
    payload: Mapping[str, Any],
    *,
    pool_id: UUID | None = None,
) -> SimResult:
    """Run one seeded simulation inside the caller's transaction (no commit here)."""
    started = time.perf_counter()
    entries, merchants, seed = _config(payload)
    target = pool_id if pool_id is not None else uuid4()
    pool = await ensure_pool(session, pool_id=target, entries=entries, seed=seed)
    if pool.entries_root is not None:
        return await _existing_result(session, pool=pool, seed=seed, started=started)
    if str(pool.status) != str(PoolStatus.DRAFT):
        # A pool that left DRAFT without a published commitment root is a broken
        # snapshot; re-running would double-write, so it is never guessed at.
        raise ApplicationError("INTEGRITY_ERROR")

    plan = build_plan(pool_id=pool.id, entries=entries, merchants=merchants, seed=seed)
    now = await session.scalar(text("SELECT now()"))
    if not isinstance(now, datetime):
        raise RuntimeError("database clock returned a non-datetime value")

    pool.title = plan.meta.title
    pool.template = plan.meta.template
    pool.lot_plan = plan.meta.lot_plan
    pool.timeline = plan.meta.timeline
    await session.flush()

    _move(pool, "PUBLISHED")
    pool.published_at = now
    _move(pool, "OPEN")

    await store.insert_identities(session, plan)
    await store.insert_entries(session, plan, received_at=now)
    _move(pool, "CLOSED")
    pool.closed_at = now

    seed_hex = hashing.demo_seed(str(pool.id))
    pool.seed_hex = seed_hex
    pool.seed_is_demo = True
    pool.beacon = {"source": "demo"}
    _move(pool, "SEEDED")

    commitments = [
        fairness.EntryCommitment(
            entry_id=str(entry.id), zone_id=entry.zone_id, commitment=entry.commitment
        )
        for entry in plan.entries
    ]
    allocation = fairness.assign_lots(commitments, plan.zone_plan, seed_hex)

    lot_ids: dict[int, UUID] = {}
    lot_rows: list[dict[str, Any]] = []
    for planned in allocation.lots:
        plan_lot = plan.lots[planned.lot_order - 1]
        lot_ids[planned.lot_order] = plan_lot.id
        lot_rows.append(
            {
                "id": str(plan_lot.id),
                "zone_id": planned.zone_id,
                "lot_index": planned.lot_index,
                "lot_order": planned.lot_order,
                "seats": planned.seats,
                "min_seats": planned.min_seats,
                "status": planned.status,
            }
        )
    await store.insert_lots(session, pool_id=pool.id, lots=lot_rows, now=now)

    seats = [
        store.SeatRow(
            id=allocation_id(pool.id, UUID(seat.entry_id)),
            entry_id=UUID(seat.entry_id),
            zone_id=seat.zone_id,
            rank=seat.rank,
            rank_hash=seat.rank_hash,
            lot_id=None if seat.lot_order is None else lot_ids[seat.lot_order],
            status=seat.status,
        )
        for seat in allocation.allocations
    ]
    await store.insert_allocations(session, pool_id=pool.id, seats=seats)

    pool.entries_root = hashing.merkle_root(sorted(entry.commitment for entry in plan.entries))
    pool.entries_count = len(plan.entries)
    _move(pool, "ALLOCATED")
    seated = sum(1 for seat in seats if seat.status == "SEATED")
    waitlisted = sum(1 for seat in seats if seat.status == "WAITLISTED")
    await store.append_audit(
        session,
        actor="sim",
        action="sim.run",
        subject_type="pool",
        subject_id=str(pool.id),
        payload={
            "entries": len(plan.entries),
            "merchants": len(plan.merchants),
            "seed": seed,
            "seed_hex": seed_hex,
            "seeded_lots": len(lot_rows),
            "seated": seated,
            "waitlisted": waitlisted,
        },
    )
    await session.flush()
    duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "sim.run.completed pool_id=%s entries=%s merchants=%s seated=%s waitlisted=%s ms=%s",
        pool.id,
        len(plan.entries),
        len(plan.merchants),
        seated,
        waitlisted,
        duration_ms,
    )
    return SimResult(
        pool_id=pool.id,
        seed=seed,
        entries=len(plan.entries),
        merchants=len(plan.merchants),
        seated=seated,
        waitlisted=waitlisted,
        lots=len(lot_rows),
        duration_ms=duration_ms,
        plan_sha256=store.plan_digest(plan),
        samples=plan.messages,
    )


__all__ = ["SimResult", "ensure_pool", "run_sim"]
