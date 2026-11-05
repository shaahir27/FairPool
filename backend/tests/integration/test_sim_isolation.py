"""FR-SM-01: a SIMULATION pool never reaches a public list, detail or audit surface.

The live pool is built by the shared checkout world builder; the simulated one is a
real ``run_sim`` result. Both share the same public functions the routers call, so
this test proves the isolation filter rather than a hand-built query.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.routers.pools import pools_get, pools_list, pools_rules, public_pool
from fairpool.api.routers.public import public_audit
from fairpool.modules.sim.run import run_sim
from tests.integration.test_open_checkout import build_world

ROOT = Path(__file__).resolve().parents[3]


def _postgres_configured() -> bool:
    if not (os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")):
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    try:
        from tests.conftest import database_url

        database_url()
    except Exception:
        return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_configured(), reason="Postgres is not configured"),
]


async def test_a_simulation_pool_is_invisible_to_public_surfaces(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session, seats=3, min_seats=2, seated=1, waitlisted=1)
    simulation = await run_sim(db_session, {"entries": 40, "merchants": 2, "seed": 5})

    listed = await pools_list(
        request=None, q=None, status=None, sort=None, limit=None, db=db_session
    )
    listed_ids = {str(item["pool_id"]) for item in listed}
    assert str(world.pool_id) in listed_ids
    assert str(simulation.pool_id) not in listed_ids

    for surface in (
        lambda: public_pool(db_session, simulation.pool_id),
        lambda: pools_get(simulation.pool_id, db=db_session),
        lambda: pools_rules(simulation.pool_id, db=db_session),
        lambda: public_audit(simulation.pool_id, db=db_session),
    ):
        with pytest.raises(HTTPException) as caught:
            await surface()
        assert caught.value.status_code == 404

    # The live pool still answers: the filter is isolation, not a blanket 404.
    live = await public_audit(world.pool_id, db=db_session)
    assert live["pool_status"] == "ALLOCATED"
    summary = await pools_get(world.pool_id, db=db_session)
    assert summary["pool_id"] == world.pool_id
