"""F2, F3 and F4: webhooks accelerate, a GET confirms, and neither can move state alone.

``docs/testing-strategy.md`` names these three fault cases and the invariants they
protect. They run against the real ``webhook.process`` handler with the settle and approve
paths recorded rather than executed, because the point of all three is what a webhook is
*not* allowed to do:

* **F2** (I4) -- a delivery that never arrives costs nothing: the reconciler reaches the
  same handler, so the lost event leaves no stuck row behind;
* **F3** (I9) -- the same event delivered twice resolves once;
* **F4** (I10) -- events that arrive out of order cannot walk a row backwards, because
  the handler writes no buyer-order state at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.enums import WebhookStatus
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.modules.reconciler.resolve import Reconciler
from fairpool.modules.webhooks.handlers import WebhookProcessor
from tests.integration.test_authorize_flow import open_offers
from tests.integration.test_open_checkout import build_world
from tests.unit.test_checkout_engine import insert_capture, insert_paypal_order

pytestmark = pytest.mark.faults


class Recorder:
    """What the processor was told to re-read, and nothing else."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, session: Any, buyer_order_id: UUID) -> None:
        self.calls.append(str(buyer_order_id))


async def event(
    session: AsyncSession,
    *,
    now: datetime,
    event_type: str,
    resource_id: str,
    paypal_event_id: str | None = None,
    verified: bool = True,
    status: WebhookStatus = WebhookStatus.RECEIVED,
    related_order: str | None = None,
) -> UUID:
    """Store a webhook row the way ingest would, and return its id."""
    row_id = uuid4()
    resource: dict[str, Any] = {"id": resource_id}
    if related_order is not None:
        resource["supplementary_data"] = {"related_ids": {"order_id": related_order}}
    await session.execute(
        text(
            "INSERT INTO webhook_events (id, paypal_event_id, event_type, raw_body, verified, "
            "verification_detail, status, received_at) VALUES (:id, :event_id, :type, :body, "
            ":verified, 'test', CAST(:status AS webhook_status), :now)"
        ),
        {
            "id": row_id,
            "event_id": paypal_event_id or f"WH-{uuid4()}",
            "type": event_type,
            "body": json.dumps({"event_type": event_type, "resource": resource}),
            "verified": verified,
            "status": str(status),
            "now": now,
        },
    )
    await session.flush()
    return row_id


def processor(settle: Recorder, approve: Recorder, now: datetime) -> WebhookProcessor:
    clock = FakeClock(now)
    return WebhookProcessor(
        clock=clock, jobs=FakeJobQueue(clock=clock), settle=settle, approve=approve
    )


async def stored_row(session: AsyncSession, row_id: UUID) -> Any:
    return (
        await session.execute(
            text("SELECT status::text, processed_at FROM webhook_events WHERE id = :id"),
            {"id": row_id},
        )
    ).one()


async def order_status(session: AsyncSession, order_id: UUID) -> str:
    return str(
        await session.scalar(
            text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": order_id}
        )
    )


async def test_f04_webhooks_out_of_order_monotonic(db_session: AsyncSession) -> None:
    """F4: a late PENDING event cannot undo a capture that already reads COMPLETED."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, mode="authorize_capture")
    (order_id,) = await open_offers(world)
    paypal_order = await insert_paypal_order(db_session, order_id)
    capture_id = await insert_capture(db_session, order_id, status="COMPLETED")
    await db_session.execute(
        text("UPDATE buyer_orders SET status = 'CAPTURED'::buyer_order_status WHERE id = :id"),
        {"id": order_id},
    )
    await db_session.flush()
    settle = Recorder()

    # The COMPLETED event arrives second, out of order with what we already stored.
    for event_type in ("PAYMENT.CAPTURE.PENDING", "PAYMENT.CAPTURE.COMPLETED"):
        row_id = await event(
            db_session,
            now=world.now,
            event_type=event_type,
            resource_id=capture_id,
            related_order=paypal_order,
        )
        await processor(settle, Recorder(), world.now).process(
            db_session, {"webhook_event_id": str(row_id)}
        )
        assert await order_status(db_session, order_id) == "CAPTURED", event_type

    assert settle.calls == [str(order_id), str(order_id)]
    assert (await stored_row(db_session, row_id)).status == "PROCESSED"


async def test_f03_duplicate_webhook_ignored(db_session: AsyncSession) -> None:
    """F3: the same event processed twice resolves the order once and writes no state."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, mode="authorize_capture")
    (order_id,) = await open_offers(world)
    capture_id = await insert_capture(db_session, order_id, status="COMPLETED")
    row_id = await event(
        db_session,
        now=world.now,
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_id=capture_id,
        paypal_event_id="WH-DUP",
    )
    settle = Recorder()
    handler = processor(settle, Recorder(), world.now)

    await handler.process(db_session, {"webhook_event_id": str(row_id)})
    await handler.process(db_session, {"webhook_event_id": str(row_id)})

    stored = await stored_row(db_session, row_id)
    assert str(stored.status) == "PROCESSED"
    assert stored.processed_at is not None
    assert settle.calls == [str(order_id)], "one event, one resolve, whatever the delivery count"
    # A row already PROCESSED is never re-driven, so a duplicate cannot double-apply (I9).
    assert await order_status(db_session, order_id) == "OFFERED"


async def test_f02_webhook_lost_reconciler_heals(db_session: AsyncSession) -> None:
    """F2: no delivery at all still resolves the order, through the same handler.

    The sweep is the authority (P4); a webhook is a timer that fires early. This asserts
    the equality that makes losing one safe: the same ``resolve_charge`` settle the webhook
    route calls is what the reconciler reaches on its own, with the same key.
    """
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, mode="authorize_capture")
    (order_id,) = await open_offers(world)
    await insert_paypal_order(db_session, order_id)
    await db_session.execute(
        text(
            "UPDATE buyer_orders SET status = 'CAPTURING'::buyer_order_status, "
            "updated_at = :old WHERE id = :id"
        ),
        {"id": order_id, "old": datetime.now(UTC) - timedelta(seconds=600)},
    )
    await db_session.flush()

    settle = Recorder()
    reconciler = Reconciler(clock=FakeClock(world.now), jobs=FakeJobQueue(), resolve_charge=settle)
    healed = await reconciler.resolve(db_session, {"buyer_order_id": str(order_id)})

    assert healed is None
    assert settle.calls == [str(order_id)], "the reconciler reaches the same settle path"
    assert await order_status(db_session, order_id) == "CAPTURING", "it only asked for a GET"


async def test_an_unverified_row_is_never_processed(db_session: AsyncSession) -> None:
    """P4: verification is the gate, and the row's own flag is what the handler reads."""
    world = await build_world(db_session, seats=1, seated=1, waitlisted=0, mode="authorize_capture")
    (order_id,) = await open_offers(world)
    capture_id = await insert_capture(db_session, order_id, status="COMPLETED")
    row_id = await event(
        db_session,
        now=world.now,
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_id=capture_id,
        verified=False,
    )
    settle = Recorder()

    await processor(settle, Recorder(), world.now).process(
        db_session, {"webhook_event_id": str(row_id)}
    )

    assert settle.calls == []
    assert (await stored_row(db_session, row_id)).status == "RECEIVED"


async def test_an_event_for_an_unknown_resource_goes_to_the_dead_letter(
    db_session: AsyncSession,
) -> None:
    """Unmappable is not the same as nothing-happened: an operator must be able to see it."""
    row_id = await event(
        db_session,
        now=datetime.now(UTC),
        event_type="PAYMENT.CAPTURE.COMPLETED",
        resource_id="CAP-NEVER-STORED",
    )
    settle = Recorder()

    await processor(settle, Recorder(), datetime.now(UTC)).process(
        db_session, {"webhook_event_id": str(row_id)}
    )

    assert settle.calls == []
    assert (await stored_row(db_session, row_id)).status == "DEAD_LETTER"
