"""T04X01: the admin force-award helper and the reconciler run (api.md section 3).

The helper is deliberately gated: ``FEATURE_DISABLED`` outside ``local``/``test``
unless ``MOCK_TOGGLES_ENABLED`` is set. Where it is allowed it writes the immutable
award with ``bid_revision_id = NULL``, stamps the router and mode (N8), prices out
seats whose cap cannot cover the total, and applies LS-14 through the whitelist.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain import hashing
from tests.integration.test_join_receipts import login, settings_for
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration


async def client_for(db_session: AsyncSession, **settings: Any) -> httpx.AsyncClient:
    app = create_app(settings_for(**settings))

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="https://api.test")


async def admin_login(client: httpx.AsyncClient, db: AsyncSession) -> str:
    """Register, promote to admin in the database, and return the CSRF token."""
    csrf = await login(client, "force-award@example.test")
    await db.execute(
        text("UPDATE users SET role = 'admin' WHERE email = :email"),
        {"email": "force-award@example.test"},
    )
    return csrf


def body(merchant_id: UUID) -> dict[str, Any]:
    return {
        "merchant_id": str(merchant_id),
        "item_cents": 47_000,
        "tier_index": 0,
        "moq": 2,
        "valid_minutes": 60,
    }


async def test_force_award_writes_the_award_and_applies_ls14(
    db_session: AsyncSession,
) -> None:
    """T04X01 acceptance: the award row, the hash, the stamp and LS-14's effects."""
    world = await build_world(
        db_session, lot_status="PLANNED", seated=2, waitlisted=0, with_award=False
    )
    settings = settings_for(app_env="local")
    async with await client_for(db_session, app_env="local") as client:
        csrf = await admin_login(client, db_session)
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )

    assert response.status_code == 201, response.text
    payload = response.json()
    award = payload["award"]
    assert payload["lot_id"] == str(world.lot_id)
    assert payload["lot_status"] == "AWARDED"
    assert award["item_cents"] == 47_000 and award["moq"] == 2
    assert award["tier_index"] == 0

    row = (
        await db_session.execute(
            text(
                "SELECT bid_revision_id, totals, valid_until, award_hash, rule_version "
                "FROM awards WHERE lot_id = :lot"
            ),
            {"lot": world.lot_id},
        )
    ).one()
    assert row.bid_revision_id is None
    assert row.rule_version == "ranking_v1"
    totals = row.totals
    assert set(totals) == {str(entry) for entry in world.entry_ids}
    assert all(values["total_cents"] == 47_000 for values in totals.values())
    document = {
        "v": 1,
        "lot_id": str(world.lot_id),
        "bid_revision_id": None,
        "merchant_id": str(world.merchant_id),
        "tier_index": 0,
        "item_cents": 47_000,
        "moq": 2,
        "totals": totals,
        "valid_until": row.valid_until.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "rule_version": "ranking_v1",
    }
    assert row.award_hash == hashing.award_hash(document)
    assert award["award_hash"] == row.award_hash

    lot = (
        await db_session.execute(
            text("SELECT status, payment_router, payment_mode FROM lots WHERE id = :lot"),
            {"lot": world.lot_id},
        )
    ).one()
    assert str(lot.status) == "AWARDED"
    # N8: the router and mode are stamped from configuration at award time.
    assert str(lot.payment_router) == settings.payment_router
    assert str(lot.payment_mode) == settings.payment_mode
    jobs = (
        (
            await db_session.execute(
                text("SELECT kind FROM jobs WHERE payload->>'lot_id' = :lot"),
                {"lot": str(world.lot_id)},
            )
        )
        .scalars()
        .all()
    )
    assert "lot.open_checkout" in jobs
    actions = (
        (
            await db_session.execute(
                text(
                    "SELECT action FROM audit_log WHERE subject_type = 'lot' "
                    "AND subject_id = :lot ORDER BY seq"
                ),
                {"lot": str(world.lot_id)},
            )
        )
        .scalars()
        .all()
    )
    assert "lot.awarded" in actions


async def test_force_award_prices_out_a_seat_below_the_total(
    db_session: AsyncSession,
) -> None:
    """LS-14 guard: priced-out seats are released at award time."""
    world = await build_world(
        db_session, lot_status="PLANNED", seats=3, seated=2, waitlisted=1, with_award=False
    )
    cheap_entry = world.entry_ids[1]
    await db_session.execute(
        text("UPDATE pool_entries SET cap_cents = 40000 WHERE id = :entry"),
        {"entry": cheap_entry},
    )
    async with await client_for(db_session, app_env="local") as client:
        csrf = await admin_login(client, db_session)
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 201, response.text
    status = await db_session.scalar(
        text("SELECT status FROM allocations WHERE entry_id = :entry"), {"entry": cheap_entry}
    )
    assert str(status) == "PRICED_OUT"


async def test_force_award_is_feature_disabled_outside_local_and_test(
    db_session: AsyncSession,
) -> None:
    """api.md: ``FEATURE_DISABLED`` unless APP_ENV is local/test or mock toggles are on."""
    world = await build_world(
        db_session, lot_status="PLANNED", seated=1, waitlisted=0, with_award=False
    )
    async with await client_for(db_session, app_env="render", mock_toggles_enabled=False) as client:
        csrf = await admin_login(client, db_session)
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM awards WHERE lot_id = :lot"), {"lot": world.lot_id}
        )
        == 0
    )


async def test_force_award_is_allowed_when_mock_toggles_are_enabled(
    db_session: AsyncSession,
) -> None:
    """The gated demo toggle is the second way the helper is enabled."""
    world = await build_world(
        db_session, lot_status="PLANNED", seated=1, waitlisted=0, with_award=False
    )
    async with await client_for(db_session, app_env="render", mock_toggles_enabled=True) as client:
        csrf = await admin_login(client, db_session)
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 201, response.text


async def test_force_award_refuses_a_lot_past_its_forced_states(
    db_session: AsyncSession,
) -> None:
    """LS-14 starts at PLANNED, BIDDING or BID_CLOSED; an awarded lot is 409."""
    world = await build_world(db_session, lot_status="AWARDED", seated=1, waitlisted=0)
    async with await client_for(db_session, app_env="local") as client:
        csrf = await admin_login(client, db_session)
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_STATE_INVALID"


async def test_force_award_requires_an_admin(db_session: AsyncSession) -> None:
    """api.md: the helper is an admin route."""
    world = await build_world(
        db_session, lot_status="PLANNED", seated=1, waitlisted=0, with_award=False
    )
    async with await client_for(db_session, app_env="local") as client:
        csrf = await login(client, "plain-buyer@example.test")
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/force-award",
            json=body(world.merchant_id),
            headers={"X-CSRF-Token": csrf},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_reconciler_run_enqueues_the_stale_orders(db_session: AsyncSession) -> None:
    """api.md: ``POST /admin/reconciler/run`` answers 202 with the count."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0)
    await db_session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, current_attempt, "
            "offer_expires_at, total_cents, breakdown) VALUES (:id, :lot, :entry, 'APPROVED', "
            "0, now() + interval '5 minutes', 50000, CAST(:breakdown AS jsonb))"
        ),
        {
            "id": UUID(int=77),
            "lot": world.lot_id,
            "entry": world.entry_ids[0],
            "breakdown": json.dumps(
                {"item_cents": 47000, "shipping_cents": 1500, "tax_cents": 1500}
            ),
        },
    )
    async with await client_for(db_session, app_env="local") as client:
        csrf = await admin_login(client, db_session)
        response = await client.post("/api/v1/admin/reconciler/run", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 202
    assert response.json() == {"enqueued": 1}
