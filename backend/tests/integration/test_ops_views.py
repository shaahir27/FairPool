"""T07A04: the ops console backend (lot view, abort, alerts, mock toggles, audit).

Every lot status change is asserted through the whitelist and its audit row, not
through a direct ``UPDATE`` (I10): the AWARDED branch is LS-13 with no follow-up
job, the live branch is LS-08 or LS-09 into FAILING with the ``lot.finalize_fail``
job those transitions declare. Mock toggles are gated, TTL-bounded and labelled
``MOCK``; the wrapper is the only place that names ``PayPal-Mock-Response``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.payments import (
    CreateOrderRequest,
    Payee,
    PayPalCapture,
    PayPalOrder,
)
from fairpool.modules.checkout import mock_gateway, ops
from tests.integration.test_checkout_routes import seated_world
from tests.integration.test_join_receipts import login, settings_for
from tests.integration.test_open_checkout import build_world, open_handler

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _clear_toggles() -> Iterator[None]:
    """The toggle store is process-global; no test may leak one into another."""
    mock_gateway.reset()
    yield
    mock_gateway.reset()


def app_for(db_session: AsyncSession, **overrides: Any):
    app = create_app(settings_for(**overrides))

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    return app


def http_for(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


async def admin_login(client: httpx.AsyncClient, db: AsyncSession, email: str) -> str:
    csrf = await login(client, email)
    await db.execute(text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": email})
    return csrf


async def lot_status(db: AsyncSession, lot_id: UUID) -> str:
    return str(
        await db.scalar(text("SELECT status::text FROM lots WHERE id = :lot"), {"lot": lot_id})
    )


async def audit_payload(db: AsyncSession, lot_id: UUID, action: str) -> dict[str, Any] | None:
    value = await db.scalar(
        text(
            "SELECT payload FROM audit_log WHERE subject_type = 'lot' "
            "AND subject_id = :lot AND action = :action ORDER BY seq DESC LIMIT 1"
        ),
        {"lot": str(lot_id), "action": action},
    )
    return None if value is None else dict(value)


async def finalize_jobs(db: AsyncSession, lot_id: UUID) -> int:
    return int(
        await db.scalar(
            text(
                "SELECT count(*) FROM jobs WHERE kind = 'lot.finalize_fail' "
                "AND payload->>'lot_id' = :lot"
            ),
            {"lot": str(lot_id)},
        )
        or 0
    )


async def test_lot_view_returns_the_declared_fields_and_money_facts(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session, seats=2, min_seats=1, seated=2, waitlisted=0)
    await open_handler(world).open(db_session, {"lot_id": str(world.lot_id)})
    buyer_order_id = await db_session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot ORDER BY id LIMIT 1"),
        {"lot": world.lot_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, "
            "intent, amount_cents, raw) VALUES (:id, :bo, 0, 'PP-LOT-VIEW', 'APPROVED', "
            "'AUTHORIZE', 50000, '{}'::jsonb)"
        ),
        {"id": uuid4(), "bo": buyer_order_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body, verified, "
            "verification_detail, status, received_at) VALUES (:id, 'EVT-LOT-VIEW', "
            "'PAYMENT.CAPTURE.COMPLETED', :body, false, 'unmappable', "
            "'DEAD_LETTER'::webhook_status, now())"
        ),
        {
            "id": uuid4(),
            "body": '{"resource":{"supplementary_data":{"related_ids":'
            '{"order_id":"PP-LOT-VIEW"}}}}',
        },
    )
    await db_session.flush()

    view = await ops.lot_view(db_session, world.lot_id)

    assert view["lot_id"] == world.lot_id
    assert view["pool_id"] == world.pool_id
    assert view["status"] == "CHECKOUT_OPEN"
    assert (view["seats"], view["min_seats"]) == (2, 1)
    assert view["award_id"] is not None
    assert view["payment_router"] == "single_seller"
    assert view["payment_mode"] == "authorize_capture"
    assert view["money"]["orders_by_status"] == {"OFFERED": 2}
    assert view["money"]["ledger"] == {"entries": 0, "net_cents": 0}
    assert [row["event_id"] for row in view["money"]["dead_letters"]] != []

    app = app_for(db_session)
    async with http_for(app) as client:
        await admin_login(client, db_session, "ops-lot-view@example.test")
        response = await client.get(f"/api/v1/admin/lots/{world.lot_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "lot_id",
        "pool_id",
        "status",
        "seats",
        "min_seats",
        "award_id",
        "payment_router",
        "payment_mode",
    }
    assert body["status"] == "CHECKOUT_OPEN"


async def test_abort_cancels_an_awarded_lot_through_ls13(db_session: AsyncSession) -> None:
    world = await build_world(db_session, seats=2, min_seats=1, seated=2, waitlisted=0)
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-abort-awarded@example.test")
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "lot_id": str(world.lot_id),
        "status": "CANCELLED",
        "transition_id": "LS-13",
    }
    assert await lot_status(db_session, world.lot_id) == "CANCELLED"
    payload = await audit_payload(db_session, world.lot_id, "lot.cancelled")
    assert payload is not None and payload["transition_id"] == "LS-13"
    assert payload["trigger"] == "admin.abort"
    assert await finalize_jobs(db_session, world.lot_id) == 0
    # LS-13 declares a notify effect; a seated buyer is told, not left silent.
    notified = await db_session.scalar(
        text("SELECT count(*) FROM notifications WHERE kind = 'lot.cancelled'")
    )
    assert int(notified or 0) >= 1


async def test_abort_fails_a_checkout_open_lot_through_ls08(db_session: AsyncSession) -> None:
    world = await seated_world(db_session)
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-abort-live@example.test")
        first = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )
        second = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )

    assert first.status_code == 200, first.text
    assert first.json()["status"] == "FAILING" and first.json()["transition_id"] == "LS-08"
    assert await lot_status(db_session, world.lot_id) == "FAILING"
    payload = await audit_payload(db_session, world.lot_id, "lot.failing")
    assert payload is not None and payload["transition_id"] == "LS-08"
    assert payload["aborted"] is True
    assert await finalize_jobs(db_session, world.lot_id) == 1
    # An abort that already happened answers with the state it reached, once.
    assert second.status_code == 200
    assert second.json() == {
        "lot_id": str(world.lot_id),
        "status": "FAILING",
        "transition_id": None,
    }
    assert await finalize_jobs(db_session, world.lot_id) == 1


async def test_abort_fails_a_funding_lot_through_ls09(db_session: AsyncSession) -> None:
    world = await build_world(
        db_session, lot_status="FUNDING", seats=1, min_seats=1, seated=1, waitlisted=0
    )
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-abort-funding@example.test")
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 200, response.text
    assert response.json()["transition_id"] == "LS-09"
    payload = await audit_payload(db_session, world.lot_id, "lot.failing")
    assert payload is not None and payload["transition_id"] == "LS-09"
    assert await finalize_jobs(db_session, world.lot_id) == 1


async def test_abort_refuses_a_lot_that_is_already_funded(db_session: AsyncSession) -> None:
    world = await build_world(
        db_session, lot_status="FUNDED", seats=1, min_seats=1, seated=1, waitlisted=0
    )
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-abort-funded@example.test")
        response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ORDER_STATE_INVALID"
    assert await lot_status(db_session, world.lot_id) == "FUNDED"


async def test_alerts_report_dead_letters_overdue_lots_and_stuck_lots(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    overdue = await build_world(
        db_session, lot_status="CHECKOUT_OPEN", seats=1, min_seats=1, seated=1, waitlisted=0
    )
    await db_session.execute(
        text("UPDATE lots SET fund_deadline_at = :at WHERE id = :lot"),
        {"at": now - timedelta(seconds=60), "lot": overdue.lot_id},
    )
    failing = await build_world(
        db_session, lot_status="FAILING", seats=1, min_seats=1, seated=1, waitlisted=0
    )
    await db_session.execute(
        text(
            "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body, verified, "
            "verification_detail, status, received_at) VALUES (:id, 'EVT-ALERT', "
            "'PAYMENT.CAPTURE.COMPLETED', '{}', false, 'unmappable', "
            "'DEAD_LETTER'::webhook_status, now())"
        ),
        {"id": uuid4()},
    )
    # An authorization older than the pool's age guard, on a seat still holding it.
    awaited = await build_world(db_session, seats=1, min_seats=1, seated=1, waitlisted=0)
    await open_handler(awaited).open(db_session, {"lot_id": str(awaited.lot_id)})
    buyer_order_id = await db_session.scalar(
        text("SELECT id FROM buyer_orders WHERE lot_id = :lot"), {"lot": awaited.lot_id}
    )
    await db_session.execute(
        text(
            "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, "
            "intent, amount_cents, raw) VALUES (:id, :bo, 0, 'PP-AGED', 'APPROVED', "
            "'AUTHORIZE', 50000, '{}'::jsonb)"
        ),
        {"id": uuid4(), "bo": buyer_order_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO paypal_authorizations (id, buyer_order_id, paypal_order_id, "
            "paypal_auth_id, status, amount_cents, raw, created_at) VALUES (:id, :bo, "
            "'PP-AGED', 'AUTH-AGED', 'CREATED', 50000, '{}'::jsonb, :at)"
        ),
        {
            "id": uuid4(),
            "bo": buyer_order_id,
            "at": now - timedelta(hours=100),
        },
    )
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'AUTHORIZING' WHERE id = :id"),
        {"id": buyer_order_id},
    )
    await db_session.flush()

    report = await ops.alerts(db_session, failing_grace_s=0)
    kinds = [row["kind"] for row in report["alerts"]]

    assert "webhook_dead_letter" in kinds
    assert "lot_past_fund_deadline" in kinds
    assert "lot_failing" in kinds
    assert "authorization_aged" in kinds
    assert report["count"] == len(report["alerts"])

    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-alerts@example.test")
        response = await client.get("/api/v1/admin/alerts")
        dead_letter_route = await client.get("/api/v1/admin/webhooks/dead-letter")

        event_id = dead_letter_route.json()["events"][0]["id"]
        retried = await client.post(
            f"/api/v1/admin/webhooks/{event_id}/retry", headers={"X-CSRF-Token": csrf}
        )

    assert response.status_code == 200, response.text
    http_kinds = [row["kind"] for row in response.json()["alerts"]]
    assert "webhook_dead_letter" in http_kinds and "lot_past_fund_deadline" in http_kinds
    assert dead_letter_route.status_code == 200
    assert retried.status_code == 202 and retried.json() == {"enqueued": True}
    status = await db_session.scalar(
        text("SELECT status::text FROM webhook_events WHERE paypal_event_id = 'EVT-ALERT'")
    )
    assert str(status) == "RECEIVED"
    # The stuck failing lot aborts cleanly while alerts stay read-only.
    assert await lot_status(db_session, failing.lot_id) == "FAILING"


async def test_mock_toggle_is_gated_and_labels_the_affected_response(
    db_session: AsyncSession,
) -> None:
    disabled = app_for(db_session, mock_toggles_enabled=False)
    async with http_for(disabled) as client:
        csrf = await admin_login(client, db_session, "ops-mock-off@example.test")
        refused = await client.post(
            "/api/v1/admin/mock",
            json={"kind": "paypal_mock_response", "value": "DUPLICATE_INVOICE_ID", "ttl_s": 300},
            headers={"X-CSRF-Token": csrf},
        )

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FEATURE_DISABLED"
    assert not mock_gateway.is_active()

    enabled = app_for(db_session, mock_toggles_enabled=True)
    async with http_for(enabled) as client:
        csrf = await admin_login(client, db_session, "ops-mock-on@example.test")
        armed = await client.post(
            "/api/v1/admin/mock",
            json={"kind": "paypal_mock_response", "value": "DUPLICATE_INVOICE_ID", "ttl_s": 300},
            headers={"X-CSRF-Token": csrf},
        )
        config = await client.get("/api/v1/checkout/config")

    assert armed.status_code == 200, armed.text
    assert armed.json()["labels"] == ["MOCK"]
    assert mock_gateway.active_kinds() == ["paypal_mock_response"]
    assert config.json()["labels"][-1] == "MOCK"


async def test_mock_toggle_expires_with_its_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1_000.0]
    monkeypatch.setattr(mock_gateway, "_clock", lambda: now[0])

    mock_gateway.set_toggle(kind="delay_webhooks", value=None, ttl_s=5, enabled=True)
    assert mock_gateway.is_active()
    assert mock_gateway.label() == "MOCK"

    now[0] += 6.0
    assert not mock_gateway.is_active()
    assert mock_gateway.label() is None


class RecordingGateway:
    """The inner gateway of the wrapper test: it records and never calls a host."""

    def __init__(self) -> None:
        self.requests: list[CreateOrderRequest] = []
        self.captures = 0

    async def create_order(self, req: CreateOrderRequest) -> PayPalOrder:
        self.requests.append(req)
        return PayPalOrder(
            "PP-RECORDED",
            "APPROVED",
            "AUTHORIZE",
            "USD",
            req.amount_cents,
            req.payee.email,
            None,
            "PAYER",
            "US",
            "https://www.sandbox.paypal.com/checkoutnow?token=PP-RECORDED",
            [],
            [],
            None,
            {},
        )

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> PayPalCapture:
        self.captures += 1
        return PayPalCapture("CAPTURE", "COMPLETED", amount_cents, True, auth_id)


def create_request() -> CreateOrderRequest:
    return CreateOrderRequest(
        buyer_order_id=str(uuid4()),
        attempt=0,
        amount_cents=50_000,
        breakdown={},
        description="Monitor",
        reference_id="lot",
        payee=Payee("seller@example.test", None),
        return_url="https://api.test/api/v1/checkout/return",
        cancel_url="https://api.test/api/v1/checkout/cancel",
        shipping=None,
        payload_level=0,
        extra_headers={},
    )


async def test_fault_gateway_injects_one_header_and_simulates_a_decline() -> None:
    inner = RecordingGateway()
    wrapper = mock_gateway.FaultInjectingGateway(inner)

    mock_gateway.set_toggle(
        kind="paypal_mock_response",
        value="DUPLICATE_INVOICE_ID",
        ttl_s=60,
        enabled=True,
    )
    first = await wrapper.create_order(create_request())
    second = await wrapper.create_order(create_request())

    assert first.id == second.id == "PP-RECORDED"
    assert inner.requests[0].extra_headers == {"PayPal-Mock-Response": "DUPLICATE_INVOICE_ID"}
    assert inner.requests[1].extra_headers == {}
    assert not mock_gateway.is_active()

    mock_gateway.set_toggle(kind="force_capture_failure", value=None, ttl_s=60, enabled=True)
    capture = await wrapper.capture_authorization(
        "AUTH-1", amount_cents=50_000, request_key="cap:AUTH-1"
    )

    assert capture.status == "DECLINED"
    assert capture.id.startswith(mock_gateway.SIMULATED_CAPTURE_PREFIX)
    assert inner.captures == 0

    mock_gateway.set_toggle(kind="delay_webhooks", value="5", ttl_s=60, enabled=True)
    assert mock_gateway.active_kinds() == ["delay_webhooks"]
    assert mock_gateway.label() == "MOCK"


async def test_audit_export_returns_the_chained_rows_with_hashes(
    db_session: AsyncSession,
) -> None:
    world = await build_world(db_session, seats=1, min_seats=1, seated=1, waitlisted=0)
    before_seq = int(
        await db_session.scalar(text("SELECT COALESCE(max(seq), 0) FROM audit_log")) or 0
    )
    app = app_for(db_session)
    async with http_for(app) as client:
        csrf = await admin_login(client, db_session, "ops-audit@example.test")
        abort_response = await client.post(
            f"/api/v1/admin/lots/{world.lot_id}/abort", headers={"X-CSRF-Token": csrf}
        )
        response = await client.get("/api/v1/admin/audit/export", params={"since_seq": before_seq})

    assert abort_response.status_code == 200, abort_response.text
    assert response.status_code == 200, response.text
    checkpoints = response.json()["checkpoints"]
    assert checkpoints, "the abort wrote an audit row"
    assert all(len(item["hash"]) == 64 for item in checkpoints)
    assert any(item["action"] == "lot.cancelled" for item in checkpoints)

    rows = await ops.audit_export(db_session, before_seq)
    assert [row["seq"] for row in rows] == sorted(row["seq"] for row in rows)
    assert all(len(row["prev_hash"]) == 64 and len(row["hash"]) == 64 for row in rows)
    assert rows[-1]["hash"] == checkpoints[-1]["hash"]
    assert all(rows[index]["prev_hash"] == rows[index - 1]["hash"] for index in range(1, len(rows)))

    app = app_for(db_session)
    async with http_for(app) as client:
        await admin_login(client, db_session, "ops-audit-since@example.test")
        tail = await client.get("/api/v1/admin/audit/export", params={"since_seq": rows[-1]["seq"]})
        invalid = await client.get("/api/v1/admin/audit/export", params={"since_seq": "x"})

    assert tail.status_code == 200 and tail.json() == {"checkpoints": []}
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
