"""Webhook ingest and processing: a PayPal event is a hint that something needs a GET.

Contract: ``docs/contracts/paypal-adapter.md`` section 8, ``api.md`` "Webhook", the
``webhook_events`` table in ``db-schema.md``, and invariants I4 and P4. Three rules:

* **A webhook never changes money state.** The raw body is stored, and processing only
  ever hands a buyer order to the handler that owns its provider call. "Paid" is still a
  capture that reads ``COMPLETED`` from a GET, never event text (I4).
* **Only a verified row may enqueue work.** The raw body and a sanitised header subset are
  stored whatever the signature says, because an unverified delivery is still evidence
  that something was sent; ``PAYPAL_WEBHOOK_ID`` unset means every row stays unverified and
  nothing is processed, which is the state the S5 spike recorded (P4).
* **A duplicate is absorbed, an unmappable event is not lost.** The unique
  ``paypal_event_id`` insert is the dedupe (S5 proved duplicate delivery is real), and a
  row that cannot be tied to a stored resource goes to the dead-letter list where the ops
  route can see and re-drive it, instead of being dropped.

Seven event types are registered (``paypal-adapter.md`` section 8). ``CHECKOUT.ORDER.APPROVED``
is never *awaited*: S5 saw no delivery inside its window and V4 treats an unapproved order
as a wait, so the approval path stays the return URL and the reconciler.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import WebhookEvent
from fairpool.db.models.enums import WebhookStatus
from fairpool.domain.errors import ApplicationError
from fairpool.ports import Clock, JobQueue

logger: Final[logging.Logger] = logging.getLogger("fairpool.webhooks")

#: An order event carries its own id; a capture event names its order under
#: ``supplementary_data.related_ids.order_id`` (``paypal-adapter.md`` section 8).
ORDER_EVENT: Final[str] = "CHECKOUT.ORDER.APPROVED"

#: ``settle`` and ``approve`` are the handlers that own the provider call for one order.
type Settle = Callable[[AsyncSession, UUID], Awaitable[None]]


class WebhookProcessor:
    """``webhook.process``: map one stored event to one buyer order, then get it confirmed."""

    def __init__(self, *, clock: Clock, jobs: JobQueue, settle: Settle, approve: Settle) -> None:
        self.clock = clock
        self.jobs = jobs
        self.settle = settle
        self.approve = approve

    async def process(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        event = await session.scalar(
            select(WebhookEvent).where(WebhookEvent.id == UUID(str(payload["webhook_event_id"])))
        )
        if event is None:
            raise ApplicationError("NOT_FOUND")
        if not bool(event.verified):
            # Defence in depth: ingest only enqueues for a verified row, and an
            # unverified one must never move anything even if it were re-driven (P4).
            logger.warning("webhooks.process.unverified event_id=%s", event.id)
            return
        if str(event.status) != str(WebhookStatus.RECEIVED):
            return

        body = json_object(event.raw_body)
        event_type = str(event.event_type or body.get("event_type") or "")
        order_id = await self._buyer_order(session, event_type=event_type, body=body)
        if order_id is None:
            await self._mark(session, event, WebhookStatus.DEAD_LETTER)
            logger.warning(
                "webhooks.process.dead_letter event_id=%s event_type=%s", event.id, event_type
            )
            return

        await self._mark(session, event, WebhookStatus.PROCESSED)
        if event_type == ORDER_EVENT:
            await self.approve(session, order_id)
            return
        # An authorization or capture event says "read this order again", nothing more.
        await self.settle(session, order_id)

    async def _buyer_order(
        self, session: AsyncSession, *, event_type: str, body: dict[str, Any]
    ) -> UUID | None:
        """The order this event is about, found only through resources we stored.

        The event's own amount, status and payer fields are never read here: they are the
        thing a later GET proves (I4), and a body that names a resource we never created
        maps to nothing.
        """
        raw_resource = body.get("resource")
        resource: dict[str, Any] = raw_resource if isinstance(raw_resource, dict) else {}
        resource_id = str(resource.get("id") or "")
        if event_type == ORDER_EVENT:
            if not resource_id:
                return None
            found = await session.scalar(
                text(
                    "SELECT buyer_order_id FROM paypal_orders WHERE paypal_order_id = :id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": resource_id},
            )
            return None if found is None else UUID(str(found))
        if resource_id:
            for table, column in (
                ("paypal_authorizations", "paypal_auth_id"),
                ("paypal_captures", "paypal_capture_id"),
                ("paypal_refunds", "paypal_refund_id"),
            ):
                found = await session.scalar(
                    text(f"SELECT buyer_order_id FROM {table} WHERE {column} = :id LIMIT 1"),
                    {"id": resource_id},
                )
                if found is not None:
                    return UUID(str(found))
        raw_related = resource.get("supplementary_data")
        related: dict[str, Any] = raw_related if isinstance(raw_related, dict) else {}
        related_ids = related.get("related_ids")
        related_order = ""
        if isinstance(related_ids, dict):
            related_order = str(related_ids.get("order_id") or "")
        if related_order:
            found = await session.scalar(
                text(
                    "SELECT buyer_order_id FROM paypal_orders WHERE paypal_order_id = :id "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": related_order},
            )
            return None if found is None else UUID(str(found))
        return None

    async def _mark(
        self, session: AsyncSession, event: WebhookEvent, status: WebhookStatus
    ) -> None:
        event.status = status
        event.processed_at = await self.clock.db_now(session)
        await session.flush()


def json_object(raw: str) -> dict[str, Any]:
    """The stored body as a mapping, or empty when it is not one.

    The row keeps the bytes PayPal sent; this only reads them back, and an unparseable
    body maps to nothing and lands in the dead letter rather than raising.
    """
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


async def retry_dead_letter(
    session: AsyncSession,
    clock: Clock,
    jobs: JobQueue,
    *,
    event_id: UUID,
) -> None:
    """Re-arm one dead-lettered event: back to RECEIVED, and the job goes in again.

    The ops route needs this because a dead letter is a mapping gap, not a bad event: once
    the resource is stored by a later capture, the same row becomes processable. The
    re-arm time is the database clock, never the host's (I15).
    """
    event = await session.scalar(select(WebhookEvent).where(WebhookEvent.id == event_id))
    if event is None:
        raise ApplicationError("NOT_FOUND")
    event.status = WebhookStatus.RECEIVED
    event.processed_at = None
    await session.flush()
    await jobs.enqueue(
        session,
        "webhook.process",
        {"webhook_event_id": str(event_id)},
        run_at=await clock.db_now(session),
        concurrency_key=f"wh:{event_id}",
    )
