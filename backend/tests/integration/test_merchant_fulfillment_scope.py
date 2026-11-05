"""T08A03: the Merchant Agent API fulfillment operations and their scopes.

The five operations are key-authenticated like the lots and bids pair: a key
without the operation's scope is ``403 API_KEY_SCOPE``, a key that resolves acts
as its own merchant, and a lot awarded to another merchant is ``404 NOT_FOUND``
with no address in the body (PT-15, api.md section 4.3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.merchant_api.app import app as merchant_api_app
from fairpool.domain.payments import PayPalCapture, PayPalOrder
from fairpool.fakes.payments import FakePayPalGateway
from tests.integration.test_fulfillment_gates import build_awarded_world
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_merchant_api_keys import create_key, merchant

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
API = "/merchant-api/v1"


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    merchant_api_app.dependency_overrides[database_session] = session
    merchant_api_app.state.fulfillment_service = None
    merchant_api_app.state.fulfillment_gateway = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as http:
            yield http
    finally:
        merchant_api_app.dependency_overrides.clear()
        merchant_api_app.state.fulfillment_gateway = None
        merchant_api_app.state.fulfillment_service = None


def seed_gateway(awarded: Any) -> FakePayPalGateway:
    """A fake whose GETs answer with the lot's own capture ids and amounts."""
    gateway = FakePayPalGateway()
    for paypal_order_id, capture_id, order_id in zip(
        awarded.paypal_order_ids, awarded.capture_ids, awarded.order_ids, strict=True
    ):
        entry_id = awarded.world.entry_ids[awarded.order_ids.index(order_id)]
        total = int(awarded.world.totals[str(entry_id)]["total_cents"])
        gateway.orders[paypal_order_id] = PayPalOrder(
            id=paypal_order_id,
            status="COMPLETED",
            intent="AUTHORIZE",
            currency="USD",
            amount_cents=total,
            payee_email=None,
            payee_merchant_id=None,
            payer_id=None,
            payer_country="US",
            approve_url=None,
            authorizations=[],
            captures=[PayPalCapture(capture_id, "COMPLETED", total, True, None)],
            debug_id=None,
            raw={},
        )
    return gateway


async def key_for(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    email: str,
    scopes: list[str],
) -> tuple[str, UUID]:
    csrf, merchant_id = await merchant(client, db_session, email)
    created = await create_key(client, csrf, scopes)
    return str(created["key"]), merchant_id


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def shipment_body(order_id: UUID) -> dict[str, Any]:
    return {
        "shipments": [
            {"buyer_order_id": str(order_id), "carrier": "UPS", "tracking_number": "1Z999"}
        ]
    }


async def test_each_operation_refuses_a_key_without_its_scope(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    key, merchant_id = await key_for(
        client, db_session, "scope-refused@example.test", ["lots:read"]
    )
    awarded = await build_awarded_world(db_session, merchant_id)
    lot_id = awarded.world.lot_id

    calls = [
        client.get(f"{API}/lots/{lot_id}/progress", headers=bearer(key)),
        client.get(f"{API}/lots/{lot_id}/fulfillment", headers=bearer(key)),
        client.post(
            f"{API}/lots/{lot_id}/shipments",
            headers=bearer(key),
            json=shipment_body(awarded.order_ids[0]),
        ),
        client.get(f"{API}/lots/{lot_id}/verification-manifest", headers=bearer(key)),
        client.get(f"{API}/lots/{lot_id}/verification", headers=bearer(key)),
    ]
    for call in calls:
        refused = await call
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "API_KEY_SCOPE"


async def test_the_five_operations_work_with_their_scopes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    key, merchant_id = await key_for(
        client,
        db_session,
        "scope-granted@example.test",
        ["fulfillment:read", "shipments:write", "manifest:read"],
    )
    awarded = await build_awarded_world(db_session, merchant_id)
    merchant_api_app.state.fulfillment_gateway = seed_gateway(awarded)
    lot_id = awarded.world.lot_id

    progress = await client.get(f"{API}/lots/{lot_id}/progress", headers=bearer(key))
    assert progress.status_code == 200, progress.text
    assert progress.json()["moq"] == 2

    fulfillment = await client.get(f"{API}/lots/{lot_id}/fulfillment", headers=bearer(key))
    assert fulfillment.status_code == 200, fulfillment.text
    assert len(fulfillment.json()) == 2

    csv_response = await client.get(
        f"{API}/lots/{lot_id}/fulfillment",
        headers={**bearer(key), "Accept": "text/csv"},
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"] == "text/csv; charset=utf-8"

    shipments = await client.post(
        f"{API}/lots/{lot_id}/shipments",
        headers=bearer(key),
        json=shipment_body(awarded.order_ids[0]),
    )
    assert shipments.status_code == 202, shipments.text
    assert shipments.json()["accepted"] == 1

    manifest = await client.get(f"{API}/lots/{lot_id}/verification-manifest", headers=bearer(key))
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["expected_captured_total_cents"] == 100_000

    verification = await client.get(f"{API}/lots/{lot_id}/verification", headers=bearer(key))
    assert verification.status_code == 200, verification.text
    assert verification.json()["all_match"] is True


async def test_a_key_reads_only_the_lot_its_merchant_won(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PT-15: a key acts as one merchant, and another merchant's award is absent."""
    key, merchant_id = await key_for(
        client,
        db_session,
        "scope-owner@example.test",
        ["fulfillment:read", "shipments:write", "manifest:read"],
    )
    awarded = await build_awarded_world(db_session, merchant_id)
    foreign_key, _foreign_id = await key_for(
        client,
        db_session,
        "scope-foreign@example.test",
        ["fulfillment:read", "shipments:write", "manifest:read"],
    )
    lot_id = awarded.world.lot_id

    for path in ("progress", "fulfillment", "verification-manifest", "verification"):
        refused = await client.get(f"{API}/lots/{lot_id}/{path}", headers=bearer(foreign_key))
        assert refused.status_code == 404, (path, refused.text)
        assert refused.json()["error"]["code"] == "NOT_FOUND"
        for value in (awarded.address["name"], awarded.address["line1"]):
            assert value not in refused.text
    refused_shipment = await client.post(
        f"{API}/lots/{lot_id}/shipments",
        headers=bearer(foreign_key),
        json={
            "shipments": [
                {
                    "buyer_order_id": str(awarded.order_ids[0]),
                    "carrier": "UPS",
                    "tracking_number": "1Z1",
                }
            ]
        },
    )
    assert refused_shipment.status_code == 404
    unknown = await client.get(f"{API}/lots/{uuid4()}/progress", headers=bearer(key))
    assert unknown.status_code == 404


async def test_shipment_rows_need_a_scope_and_a_real_order(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    key, merchant_id = await key_for(
        client, db_session, "ship-invalid@example.test", ["shipments:write"]
    )
    awarded = await build_awarded_world(db_session, merchant_id)
    body = {
        "shipments": [
            {
                "buyer_order_id": str(awarded.order_ids[0]),
                "carrier": "",
                "tracking_number": "1Z999",
            }
        ]
    }

    refused = await client.post(
        f"{API}/lots/{awarded.world.lot_id}/shipments", headers=bearer(key), json=body
    )

    assert refused.status_code == 202, refused.text
    assert refused.json()["rows"][0]["status"] == "INVALID"
    assert refused.json()["accepted"] == 0
    assert isinstance(awarded.order_ids[0], UUID)
