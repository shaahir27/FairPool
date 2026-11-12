"""CR-17: demand demo data is opt-in, repeatable, and never published automatically."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_demand_formation import service
from tests.integration.test_triggers import add_user

pytestmark = pytest.mark.integration


async def test_demo_demand_requires_opt_in_and_reuses_signals(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "tools"))
    demo = importlib.import_module("demo_seed")
    seed = getattr(demo, "seed_demand", None)
    assert seed is not None, "the demo must include an opt-in forming-demand story"
    svc = service(threshold=3)
    monkeypatch.delenv("DEMO_SEED_DEMAND", raising=False)
    assert await seed(db_session, service=svc) == 0
    for email in demo.BUYER_EMAILS:
        await add_user(db_session, email=email)
    monkeypatch.setenv("DEMO_SEED_DEMAND", "1")
    assert await seed(db_session, service=svc) == 1
    assert await seed(db_session, service=svc) == 0
    clusters = await svc.forming(db_session)
    assert {(row["status"], row["interested"]) for row in clusters} == {
        ("COLLECTING", 2),
        ("PROPOSED", 3),
    }
    pools = await db_session.execute(
        text("SELECT p.status FROM pools p JOIN demand_clusters d ON d.pool_id = p.id")
    )
    assert [str(row[0]) for row in pools] == ["DRAFT"]
    assert await db_session.scalar(text("SELECT count(*) FROM demand_signals")) == 5
