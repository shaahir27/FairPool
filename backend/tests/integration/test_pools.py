from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from fairpool.domain.hashing import rules_hash
from fairpool.domain.pool_config import PoolInput
from fairpool.fakes.beacon import FakeBeacon
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.pools.service import PoolService, rules_document
from tests.integration.test_triggers import add_user


async def payload(db):
    now = await DbClock().db_now(db)
    return {
        "title": "Fictional monitor pool",
        "template": {
            "product_key": "sample-monitor",
            "variant": "black",
            "title": "Monitor",
            "condition": "NEW",
            "quantity": 1,
            "currency": "USD",
            "bundle_contents": ["monitor"],
            "delivery_sla_days": 7,
            "fund_by": "2026-12-01",
            "min_return_days": 14,
            "zones": [{"zone_id": "US-EAST", "label": "East", "regions": ["NY"]}],
        },
        "lot_plan": [{"zone_id": "US-EAST", "lots": [{"seats": 3, "min_seats": 2}]}],
        "timeline": {
            "open_at": (now + timedelta(minutes=1)).isoformat(),
            "close_at": (now + timedelta(minutes=4)).isoformat(),
        },
        "require_paypal_link": False,
        "rule_version": "allocation_v1",
    }


async def test_pool_publication_freezes_rules_and_enqueues_atomically(db_session):
    service = PoolService(DbClock(), PostgresAuditLog(), PostgresJobQueue(), FakeBeacon())
    data = await payload(db_session)
    admin = await add_user(db_session, role="admin")
    pool = await service.create(db_session, actor_id=admin, payload=PoolInput.model_validate(data))
    assert pool.status == "DRAFT"
    await service.publish(db_session, pool.id, actor_id=admin)
    assert pool.rules_hash == rules_hash(rules_document(pool))
    pool.beacon = {**pool.beacon, "randomness": "aa" * 32, "signature": "bb" * 64}
    assert pool.rules_hash == rules_hash(rules_document(pool))
    jobs = (
        (
            await db_session.execute(
                text("SELECT kind FROM jobs WHERE payload->>'pool_id'=:id"), {"id": str(pool.id)}
            )
        )
        .scalars()
        .all()
    )
    assert set(jobs) == {"pool.open", "pool.close", "search.index"}
    await service.open(db_session, {"pool_id": str(pool.id)})
    assert pool.status == "PUBLISHED"  # A timer cannot open early.
    await service.cancel(db_session, pool.id, actor_id=admin)
    assert pool.status == "CANCELLED"


async def test_pool_nested_validation_rejects_unknown_zones_overlaps_and_size(db_session):
    data = await payload(db_session)
    for mutate in [
        lambda x: x["lot_plan"][0].update(zone_id="fake"),
        lambda x: x["lot_plan"][0]["lots"][0].update(min_seats=4),
        lambda x: x["template"]["zones"].append(
            {"zone_id": "OTHER", "label": "Other", "regions": ["NY"]}
        ),
        lambda x: x["template"].update(quantity=2),
    ]:
        bad = deepcopy(data)
        mutate(bad)
        with pytest.raises(ValidationError):
            PoolInput.model_validate(bad)


async def test_funding_date_cannot_precede_close(db_session):
    data = await payload(db_session)
    data["template"]["fund_by"] = "2020-01-01"
    with pytest.raises(ValidationError):
        PoolInput.model_validate(data)
