"""``pool.seed``: fetch the announced beacon round, or wait (T04A04; PS-04, F27).

Contract: ``state-machines.md`` PS-04, ``fairness-and-hashing.md`` section 4,
``domain-ports.md`` section 5, ``db-schema.md`` ``pools.beacon``.

The handler is deliberately boring except for one rule: when the announced round
is not available it **waits**. It re-enqueues the same job ten seconds later and
returns; it never derives a substitute seed, because the only thing that makes
the ordering auditable is that the seed is the value the announced round
produced (I11, F27). Demo mode is the one seed FairPool itself chooses, and it is
stored with ``seed_is_demo = true`` so every surface that shows it can label it.

A replay is silent: ``seed_hex`` is written once, so a second run of the job
returns before any audit row, notification or job enqueue (I15).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import PoolStatus
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.domain.states import assert_transition
from fairpool.ports import AuditLog, BeaconClient, Clock, JobQueue

#: F27: how long the handler waits before asking the announced round again.
SEED_RETRY_DELAY_S: Final[int] = 10

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PoolSeedService:
    """The ``pool.seed`` job handler."""

    def __init__(self, clock: Clock, audit: AuditLog, jobs: JobQueue, beacon: BeaconClient) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.beacon = beacon

    async def seed(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Set ``pools.seed_hex`` from the announced round and enqueue allocation."""
        pool_id = UUID(str(payload["pool_id"]))
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        if pool.seed_hex is not None:
            # PS-04 already applied; a retry writes nothing (I15).
            return
        if str(pool.status) != str(PoolStatus.CLOSED):
            # Before close there is no published commitment list to seed over, and
            # after SEEDED the seed above is already set. No legal move exists, so
            # the handler leaves the pool alone instead of forcing PS-04.
            return

        announced: dict[str, Any] = dict(pool.beacon or {})
        if announced.get("source") == "demo":
            seed_hex = hashing.demo_seed(str(pool.id))
            seed_is_demo = True
            beacon_response = announced
        else:
            fetched = await self.beacon.fetch(announced)
            if fetched is None:
                # F27: wait, never a fallback chosen by FairPool (fairness §4).
                now = await self.clock.db_now(session)
                await self.jobs.enqueue(
                    session,
                    "pool.seed",
                    {"pool_id": str(pool.id)},
                    run_at=now + timedelta(seconds=SEED_RETRY_DELAY_S),
                    concurrency_key=f"pool:{pool.id}",
                )
                return
            randomness = fetched.get("randomness")
            if not isinstance(randomness, str) or _HEX64.fullmatch(randomness) is None:
                # A malformed beacon answer is not a seed; inventing one would
                # break auditability (I11).
                raise ApplicationError("INTERNAL_ERROR")
            seed_hex = randomness
            seed_is_demo = False
            # CR-11: merge onto the announcement, never replace it. The fetched body
            # carries round, randomness and signature only, and rules_document(pool)
            # rebuilds its beacon sub-dict from the stored value at read time -- a
            # replaced dict would lose source and chain_hash and the served document
            # would stop hashing to the stored rules_hash (db-schema.md pools.beacon).
            beacon_response = {**announced, **fetched}

        # PS-04 through the whitelist; the job is its own trigger.
        assert_transition("pool", "CLOSED", "SEEDED", trigger="job:pool.seed")
        pool.seed_hex = seed_hex
        pool.seed_is_demo = seed_is_demo
        # The announcement plus the fetched value are stored so the public audit
        # surface can show the round the seed came from (fairness §4, db-schema.md
        # pools.beacon).
        pool.beacon = beacon_response
        pool.status = PoolStatus.SEEDED
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action="pool.seeded",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={
                "seed_hex": seed_hex,
                "seed_is_demo": seed_is_demo,
                "beacon": {
                    key: beacon_response[key]
                    for key in ("source", "chain_hash", "round", "signature")
                    if key in beacon_response
                },
            },
        )
        # PS-04's second effect, in this same transaction.
        now = await self.clock.db_now(session)
        await self.jobs.enqueue(
            session,
            "pool.allocate",
            {"pool_id": str(pool.id)},
            run_at=now,
            concurrency_key=f"pool:{pool.id}",
        )
