"""T06A02 ingest: store always, verify when configured, process only what verified.

Contract: ``paypal-adapter.md`` section 8 and ``api.md`` "Webhook". The three states are
the three the S5 spike actually reached, so each one is asserted here rather than
described:

* disabled (the shipped default) -- stored, unverified, 200, **no job**;
* enabled with no listener id -- stored, unverified, 200, no job;
* enabled with an id -- verified rows become ``verified=true`` and enqueue
  ``webhook.process``; refused rows answer 400, stay unprocessed and keep the body.

A duplicate ``paypal_event_id`` is answered 200 and stops: S5 proved duplicate delivery is
real, so the unique insert is required, not optional (I9).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.db.session import get_session
from tests.integration.test_join_receipts import settings_for

pytestmark = pytest.mark.integration


class StubVerifier:
    """The signature check, as a table of answers keyed by transmission id."""

    def __init__(self, *, verdicts: dict[str, bool] | None = None, error: Exception | None = None):
        self.verdicts = verdicts or {}
        self.error = error
        self.seen: list[dict[str, str]] = []

    async def verify_webhook(self, headers: Any, raw_body: bytes) -> bool:
        self.seen.append(dict(headers))
        if self.error is not None:
            raise self.error
        return self.verdicts.get(str(headers.get("paypal-transmission-id")), False)


async def deliver(
    db_session: AsyncSession,
    *,
    settings: Any,
    verifier: StubVerifier | None = None,
    event_id: str | None = None,
    event_type: str = "PAYMENT.CAPTURE.COMPLETED",
    resource_id: str = "CAP-1",
) -> httpx.Response:
    """POST one delivery through the app, with the headers PayPal actually sends."""
    app = create_app(settings)
    if verifier is not None:
        app.state.webhook_gateway = verifier

    async def override_session() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    body = json.dumps(
        {
            "id": event_id or f"WH-{uuid.uuid4()}",
            "event_type": event_type,
            "resource": {"id": resource_id},
        },
        separators=(",", ":"),
    )
    headers = {
        "PayPal-Transmission-Id": f"tx-{event_id or 'x'}",
        "PayPal-Transmission-Time": "2026-11-03T12:00:00Z",
        "PayPal-Cert-Url": "https://api.sandbox.paypal.com/_cert",
        "PayPal-Auth-Algo": "SHA256withRSA",
        "PayPal-Transmission-Sig": "sig-value",
        "Content-Type": "application/json",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/webhooks/paypal", content=body, headers=headers)


async def row(session: AsyncSession, event_id: str) -> Any:
    return (
        await session.execute(
            text(
                "SELECT verified, status::text, event_type, verification_detail "
                "FROM webhook_events WHERE paypal_event_id = :id"
            ),
            {"id": event_id},
        )
    ).one()


async def process_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(text("SELECT count(*) FROM jobs WHERE kind = 'webhook.process'")) or 0
    )


async def test_disabled_webhooks_store_and_answer_without_processing(
    db_session: AsyncSession,
) -> None:
    """The shipped default: nothing is verified, so nothing is ever processed (P4)."""
    event_id = f"WH-{uuid.uuid4()}"
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=False, paypal_webhook_id="WH-LISTENER"),
        verifier=StubVerifier(verdicts={f"tx-{event_id}": True}),
        event_id=event_id,
    )

    assert response.status_code == 200
    stored = await row(db_session, event_id)
    assert stored.verified is False
    assert str(stored.status) == "RECEIVED"
    # A not-attempted verification writes no verdict of its own: the row keeps exactly
    # what ingest stored, including the header record the S5 evidence is made of.
    assert f"tx-{event_id}" in str(stored.verification_detail)
    assert "verify=" not in str(stored.verification_detail)
    assert await process_count(db_session) == 0


async def test_enabled_without_a_listener_id_stays_unverified(
    db_session: AsyncSession,
) -> None:
    """The state S5 recorded: no registered id means no verification is possible."""
    event_id = f"WH-{uuid.uuid4()}"
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=True, paypal_webhook_id=""),
        verifier=StubVerifier(verdicts={f"tx-{event_id}": True}),
        event_id=event_id,
    )

    assert response.status_code == 200
    stored = await row(db_session, event_id)
    assert stored.verified is False
    assert str(stored.status) == "RECEIVED"
    assert "verify=" not in str(stored.verification_detail)
    assert await process_count(db_session) == 0


async def test_a_verified_delivery_is_marked_and_enqueued(db_session: AsyncSession) -> None:
    """The only path that enqueues: verified, and the body was stored first (P4, I4)."""
    event_id = f"WH-{uuid.uuid4()}"
    verifier = StubVerifier(verdicts={f"tx-{event_id}": True})
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=True, paypal_webhook_id="WH-LISTENER"),
        verifier=verifier,
        event_id=event_id,
    )

    assert response.status_code == 200
    stored = await row(db_session, event_id)
    assert stored.verified is True
    assert str(stored.status) == "RECEIVED"
    assert "verify=verified" in str(stored.verification_detail)
    # The header record survives: an operator can still see what was received (I14 audit).
    assert f"tx-{event_id}" in str(stored.verification_detail)
    assert await process_count(db_session) == 1
    # The verifier got PayPal's own transmission fields, not a re-serialised body.
    assert verifier.seen[0]["paypal-transmission-sig"] == "sig-value"


async def test_a_refused_signature_is_a_400_and_never_processed(
    db_session: AsyncSession,
) -> None:
    """400, kept, unprocessed: an unverified event is not evidence of anything (P4)."""
    event_id = f"WH-{uuid.uuid4()}"
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=True, paypal_webhook_id="WH-LISTENER"),
        verifier=StubVerifier(verdicts={}),
        event_id=event_id,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    stored = await row(db_session, event_id)
    assert stored.verified is False
    assert str(stored.status) == "REJECTED"
    assert "rejected:signature" in str(stored.verification_detail)
    assert await process_count(db_session) == 0


async def test_a_verification_call_failure_is_not_a_refusal(db_session: AsyncSession) -> None:
    """F21's shape: the verification call itself failing says nothing about the event."""
    from fairpool.domain.payments import PaymentError

    event_id = f"WH-{uuid.uuid4()}"
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=True, paypal_webhook_id="WH-LISTENER"),
        verifier=StubVerifier(error=PaymentError("RETRYABLE", "TIMEOUT")),
        event_id=event_id,
    )

    assert response.status_code == 200
    stored = await row(db_session, event_id)
    assert stored.verified is False
    assert str(stored.status) == "RECEIVED", "not refused: never processed, never dead-lettered"
    assert await process_count(db_session) == 0


async def test_a_duplicate_delivery_is_stored_once_and_answered_again(
    db_session: AsyncSession,
) -> None:
    """S5 proved duplicate delivery is real; the unique insert is the dedupe (I9)."""
    settings = settings_for(webhooks_enabled=True, paypal_webhook_id="WH-LISTENER")
    event_id = f"WH-{uuid.uuid4()}"
    verifier = StubVerifier(verdicts={f"tx-{event_id}": True})

    first = await deliver(db_session, settings=settings, verifier=verifier, event_id=event_id)
    second = await deliver(db_session, settings=settings, verifier=verifier, event_id=event_id)

    assert first.status_code == 200
    assert second.status_code == 200
    count = await db_session.scalar(
        text("SELECT count(*) FROM webhook_events WHERE paypal_event_id = :id"), {"id": event_id}
    )
    assert int(count or 0) == 1
    # One event, one job: the replay was answered from the stored row, not re-processed.
    assert await process_count(db_session) == 1


async def test_the_raw_body_is_stored_verbatim(db_session: AsyncSession) -> None:
    """Verification is over the bytes sent, so the row must hold exactly those bytes."""
    event_id = f"WH-{uuid.uuid4()}"
    await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=False),
        event_id=event_id,
        event_type="PAYMENT.AUTHORIZATION.CREATED",
        resource_id="AUTH-9",
    )

    stored = (
        await db_session.execute(
            text("SELECT raw_body, event_type FROM webhook_events WHERE paypal_event_id = :id"),
            {"id": event_id},
        )
    ).one()
    payload = json.loads(str(stored.raw_body))
    assert payload["id"] == event_id
    assert payload["resource"]["id"] == "AUTH-9"
    assert str(stored.event_type) == "PAYMENT.AUTHORIZATION.CREATED"
