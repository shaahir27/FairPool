"""T01A03: the hosted webhook stub stores the exact body and safe headers."""

from __future__ import annotations

import json
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.db.session import get_session


async def test_webhook_stub_stores_raw_body_and_sanitized_headers(
    db_session: AsyncSession,
):
    app = create_app()

    async def override_session():
        yield db_session

    app.dependency_overrides[get_session] = override_session
    event_id = f"WH-{uuid.uuid4()}"
    body = json.dumps(
        {
            "id": event_id,
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {"id": "CAP-1"},
        },
        separators=(",", ":"),
    )
    headers = {
        "PayPal-Transmission-Id": "tx-123",
        "PayPal-Transmission-Time": "2026-10-30T12:00:00Z",
        "PayPal-Auth-Algo": "SHA256withRSA",
        "Authorization": "Bearer super-secret",
        "Content-Type": "application/json",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/webhooks/paypal", content=body, headers=headers)
        second = await client.post("/webhooks/paypal", content=body, headers=headers)

    assert first.status_code == 200
    assert first.json() == {}
    assert second.status_code == 200

    row = (
        await db_session.execute(
            text(
                "SELECT raw_body, verified, verification_detail, status, event_type "
                "FROM webhook_events WHERE paypal_event_id = :event_id"
            ),
            {"event_id": event_id},
        )
    ).one()
    assert row.raw_body == body
    assert row.event_type == "PAYMENT.CAPTURE.COMPLETED"
    assert row.verified is False
    assert row.status == "RECEIVED"
    detail = row.verification_detail
    assert "tx-123" in detail
    assert "SHA256withRSA" in detail
    assert "super-secret" not in detail
    assert "Bearer" not in detail

    count = await db_session.scalar(
        text("SELECT count(*) FROM webhook_events WHERE paypal_event_id = :event_id"),
        {"event_id": event_id},
    )
    assert count == 1
