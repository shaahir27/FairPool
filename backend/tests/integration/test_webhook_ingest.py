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
from tests.unit.test_settings import make_settings

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
    extra: dict[str, Any] | None = None,
    body: bytes | None = None,
) -> httpx.Response:
    """POST one delivery through the app, with the headers PayPal actually sends."""
    app = create_app(settings)
    if verifier is not None:
        app.state.webhook_gateway = verifier

    async def override_session() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    content = (
        body
        if body is not None
        else json.dumps(
            {
                "id": event_id or f"WH-{uuid.uuid4()}",
                "event_type": event_type,
                "resource": {"id": resource_id},
                **(extra or {}),
            },
            separators=(",", ":"),
        ).encode()
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
        return await client.post("/webhooks/paypal", content=content, headers=headers)


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


async def test_a_verifier_that_cannot_parse_the_body_keeps_the_row(
    db_session: AsyncSession,
) -> None:
    """Section 8 stores first, so a failure after the insert has nothing left to roll back.

    The adapter parses the body inside the signature call, which means a delivery of
    broken JSON raised there, the request died as a 500 and the ingest went with it.
    """
    event_id = f"WH-{uuid.uuid4()}"
    response = await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=True, paypal_webhook_id="WH-LISTENER"),
        verifier=StubVerifier(error=json.JSONDecodeError("broken", "<html>", 0)),
        event_id=event_id,
    )

    assert response.status_code == 200, "an unparseable delivery is not our failure to answer"
    stored = await row(db_session, event_id)
    assert stored.verified is False
    assert str(stored.status) == "RECEIVED", "the bytes PayPal sent are kept either way"
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


# --------------------------------------------------------------- CR-10 hardening

PAYER = {
    "payer": {
        "email_address": "payer@example.test",
        "payer_id": "PAYER-1",
        "name": {"given_name": "Ada", "surname": "Lovelace"},
    },
    "shipping": {"address": {"address_line_1": "1 Market Street", "admin_area_2": "New York"}},
}


async def test_a_body_over_the_cap_is_refused_before_it_is_stored(
    db_session: AsyncSession,
) -> None:
    """256 KiB is the ceiling; a 300 KiB delivery is a free write we do not take."""
    from fairpool.api.routers.webhooks import MAX_BODY_BYTES

    event_id = f"WH-{uuid.uuid4()}"
    oversized = json.dumps(
        {"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED", "pad": "x" * MAX_BODY_BYTES}
    ).encode()
    assert len(oversized) > MAX_BODY_BYTES

    response = await deliver(
        db_session, settings=settings_for(webhooks_enabled=False), body=oversized
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    stored = await db_session.scalar(
        text("SELECT count(*) FROM webhook_events WHERE paypal_event_id = :id"), {"id": event_id}
    )
    assert int(stored or 0) == 0


async def test_a_delivery_at_the_cap_is_stored(db_session: AsyncSession) -> None:
    from fairpool.api.routers.webhooks import MAX_BODY_BYTES

    event_id = f"WH-{uuid.uuid4()}"
    prefix = json.dumps({"id": event_id, "event_type": "PAYMENT.CAPTURE.COMPLETED"})[:-1]
    padding = MAX_BODY_BYTES - len(prefix) - len(',"pad":""}')
    at_cap = (prefix + ',"pad":"' + "x" * padding + '"}').encode()
    assert len(at_cap) == MAX_BODY_BYTES

    response = await deliver(db_session, settings=settings_for(webhooks_enabled=False), body=at_cap)

    assert response.status_code == 200, response.text
    stored = await db_session.scalar(
        text("SELECT count(*) FROM webhook_events WHERE paypal_event_id = :id"), {"id": event_id}
    )
    assert int(stored or 0) == 1


async def test_the_payers_identity_is_masked_before_the_insert(
    db_session: AsyncSession,
) -> None:
    """I14: the row keeps the ids, amounts and status; the person is redacted."""
    event_id = f"WH-{uuid.uuid4()}"
    await deliver(
        db_session,
        settings=settings_for(webhooks_enabled=False),
        event_id=event_id,
        extra=PAYER,
    )

    raw = await db_session.scalar(
        text("SELECT raw_body FROM webhook_events WHERE paypal_event_id = :id"), {"id": event_id}
    )
    stored = json.loads(str(raw))
    for secret in ("payer@example.test", "PAYER-1", "Ada", "Lovelace", "1 Market Street"):
        if secret == "PAYER-1":
            # The payer id is not an identity field: it is kept, exactly like resource.id.
            assert stored["payer"]["payer_id"] == secret
            continue
        assert secret not in str(raw), secret
    assert stored["resource"]["id"] == "CAP-1"
    assert stored["id"] == event_id
    assert stored["payer"]["email_address"] == "[redacted]"
    assert stored["payer"]["name"] == {"given_name": "[redacted]", "surname": "[redacted]"}
    assert stored["shipping"]["address"]["address_line_1"] == "[redacted]"


async def test_the_route_is_rate_limited(db_session: AsyncSession) -> None:
    """300/min per address (section 3); the bucket is proved with a limit of one."""
    from fairpool.api.routers.webhooks import WEBHOOK_RATE_LIMIT
    from fairpool.infra.limits import SlidingWindowLimiter

    assert WEBHOOK_RATE_LIMIT == 300
    # The limiter is the subject here, so the switch it depends on is on.
    settings = make_settings(rate_limit_enabled=True)
    app = create_app(settings)

    async def override_session() -> Any:
        yield db_session

    app.dependency_overrides[get_session] = override_session
    app.state.webhook_limiter = SlidingWindowLimiter(limit=1)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/webhooks/paypal", json={"id": f"WH-{uuid.uuid4()}"})
        second = await client.post("/webhooks/paypal", json={"id": f"WH-{uuid.uuid4()}"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "RATE_LIMITED"
    assert int(second.headers["Retry-After"]) >= 1


async def seed_delivery(db_session: AsyncSession, *, event_id: str, age_s: int) -> None:
    await db_session.execute(
        text(
            "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body, received_at) "
            "VALUES (:id, :event_id, 'PAYMENT.CAPTURE.COMPLETED', :body, "
            "now() - make_interval(secs => :age))"
        ),
        {
            "id": uuid.uuid4(),
            "event_id": event_id,
            "age": age_s,
            "body": json.dumps(
                {
                    "payer": {"email_address": "payer@example.test"},
                    "resource": {"id": "CAP-1"},
                }
            ),
        },
    )


async def raw_body_of(db_session: AsyncSession, event_id: str) -> str:
    value = await db_session.scalar(
        text("SELECT raw_body FROM webhook_events WHERE paypal_event_id = :id"), {"id": event_id}
    )
    return str(value)


def reconciler(retention_s: int):  # type: ignore[no-untyped-def]
    from fairpool.fakes.jobs import FakeJobQueue
    from fairpool.infra.clock import DbClock
    from fairpool.modules.reconciler.resolve import Reconciler

    return Reconciler(clock=DbClock(), jobs=FakeJobQueue(), webhook_raw_retention_s=retention_s)


async def test_the_sweep_replaces_a_raw_body_past_its_retention(
    db_session: AsyncSession,
) -> None:
    """The retention statement itself: one week later, the person is gone, the id stays.

    ``trg_webhook_raw_immutable`` (migration 0001) refuses this update in a real
    database, so the trigger is disabled inside this rolled-back transaction to prove
    the statement does what the setting says.
    """
    from fairpool.modules.reconciler.resolve import EXPIRED_BODY

    old_id, fresh_id = f"WH-{uuid.uuid4()}", f"WH-{uuid.uuid4()}"
    await seed_delivery(db_session, event_id=old_id, age_s=7200)
    await seed_delivery(db_session, event_id=fresh_id, age_s=0)
    await db_session.execute(
        text("ALTER TABLE webhook_events DISABLE TRIGGER trg_webhook_raw_immutable")
    )

    assert await reconciler(retention_s=3600).sweep(db_session, {}) == 0

    assert await raw_body_of(db_session, old_id) == EXPIRED_BODY
    fresh = await raw_body_of(db_session, fresh_id)
    assert "payer@example.test" in fresh, "a fresh delivery keeps its body"


async def test_a_schema_that_forbids_the_update_does_not_stop_the_sweep(
    db_session: AsyncSession,
) -> None:
    """Today's database: the update is refused, the sweep still does its real work."""
    old_id = f"WH-{uuid.uuid4()}"
    await seed_delivery(db_session, event_id=old_id, age_s=7200)

    assert await reconciler(retention_s=3600).sweep(db_session, {}) == 0

    assert "payer@example.test" in await raw_body_of(db_session, old_id)
