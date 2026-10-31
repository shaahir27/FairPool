"""F26: deadlines come from the database clock only, and the wall read is the one
that decides an admission (I15, CR-3).

Named for the fault matrix row it closes. The join-level behaviour has its own test
in `test_join_receipts.py`; this file proves the two things underneath it: that
`now()` is fixed for the whole transaction while `clock_timestamp()` moves, and that
the `pool_entries` insert trigger refuses a late join even when the transaction
started inside the window. With the pre-CR-3 trigger the second test would pass the
insert, which is exactly the defect CR-3 closed.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.infra.clock import DbClock
from tests.integration.test_triggers import add_pool, add_user, expect_error

pytestmark = pytest.mark.integration

ENTRY_INSERT_SQL = (
    "INSERT INTO pool_entries (id, pool_id, user_id, canonical_request, request_hash, "
    "cap_cents, zone_id, submitted_via) "
    "VALUES (:id, :pool, :user, CAST(:request AS jsonb), :hash, 60000, 'US-EAST', 'human')"
)


async def test_transaction_clock_is_stable_and_the_wall_clock_moves(
    db_session: AsyncSession,
) -> None:
    """The distinction every deadline guard now depends on, proved on the real clock."""
    clock = DbClock()
    transaction_first = await clock.db_now(db_session)
    wall_first = await clock.db_wall_now(db_session)
    await asyncio.sleep(0.05)
    transaction_second = await clock.db_now(db_session)
    wall_second = await clock.db_wall_now(db_session)

    assert transaction_first == transaction_second, "now() must not move inside a transaction"
    assert wall_second > wall_first, "clock_timestamp() must read the real time"


async def test_a_join_that_starts_before_close_and_inserts_after_is_refused(
    db_session: AsyncSession,
) -> None:
    """The lock-wait boundary: the trigger decides on wall time, not transaction start."""
    pool_id = await add_pool(db_session, status="OPEN", close_in=1)
    buyer = await add_user(db_session)
    params: dict[str, Any] = {
        "id": uuid.uuid4(),
        "pool": pool_id,
        "user": buyer,
        "request": '{"currency": "USD"}',
        "hash": "0" * 64,
    }

    # This transaction opened before close_at. The deadline passes while it is still
    # open, which is the situation a pool-lock wait creates in production.
    await asyncio.sleep(1.2)
    error = await expect_error(db_session, ENTRY_INSERT_SQL, params)
    assert "POOL_CLOSED" in str(error)
