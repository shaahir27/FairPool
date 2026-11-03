"""PayPal webhook receiver: store first, verify second, process only what verified.

Contract: ``docs/contracts/paypal-adapter.md`` section 8 and ``api.md`` "Webhook". The
body is stored whatever the signature says, because an unverified delivery is still
evidence that something was sent; a verified row is the only one that may enqueue work,
and processing never changes money state by itself (I4, P4).

Three states, and they are the states S5 actually recorded:

* ``WEBHOOKS_ENABLED=false`` -- the shipped default. Nothing is processed and every row
  stays unverified, which is why the reconciler remains the only path that moves money
  (IT-6's "or the reconciler is the only path").
* enabled with ``PAYPAL_WEBHOOK_ID`` empty -- the row is stored unverified, the answer is
  200, and no job is written. S5 could only verify a signature with an id registered on
  the dashboard, so this is the state a fresh deployment starts in.
* enabled with the id set -- verify through the adapter. Failure is a 400 and is never
  processed; success marks the row verified and enqueues ``webhook.process``.

A duplicate ``paypal_event_id`` is answered 200 and stops there: S5 proved duplicate
delivery is real, and the unique insert is the dedupe, not an option (I9).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool import wiring
from fairpool.api import schemas
from fairpool.config import Settings
from fairpool.db.session import get_session
from fairpool.domain.payments import PaymentError
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.webhooks.handlers import json_object

router = APIRouter()
logger = logging.getLogger("fairpool.webhooks")

#: The verification fields plus the content type. The signature header belongs here:
#: without it ``verify_webhook`` cannot be called at all, and it is PayPal's own
#: transmission signature, not one of our credentials (I14 is about ours).
_ALLOWED_HEADERS = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-cert-url",
    "paypal-auth-algo",
    "paypal-transmission-sig",
    "content-type",
)


def _sanitized_headers(request: Request) -> dict[str, str]:
    return {name: request.headers[name] for name in _ALLOWED_HEADERS if name in request.headers}


def _settings(request: Request) -> Settings | None:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings


async def _verifier(request: Request, settings: Settings) -> Any:
    """The adapter that verifies signatures, or the injected test double.

    ``app.state.webhook_gateway`` is the seam: the S5 evidence was produced against the
    real listener, and no automated run may call PayPal.
    """
    injected = getattr(request.app.state, "webhook_gateway", None)
    if injected is not None:
        return injected
    return wiring.payment_router(settings).gateway


async def _verification(
    request: Request, settings: Settings | None, headers: dict[str, str], raw: bytes
) -> tuple[str, str]:
    """``(outcome, detail)``: ``verified``, ``rejected`` or ``not-attempted``.

    A deployment that has not switched webhooks on, has no listener id registered, or has
    no settings at all is not rejecting anything: its row keeps the ``RECEIVED`` status and
    the header record the ingest stored, because S5's evidence is that record. Only an
    attempted verification writes a detail of its own.
    """
    if settings is None or not settings.webhooks_enabled:
        return "not-attempted", "disabled:WEBHOOKS_ENABLED=false"
    if not settings.paypal_webhook_id:
        return "not-attempted", "unverified:PAYPAL_WEBHOOK_ID unset"
    try:
        verified = await (await _verifier(request, settings)).verify_webhook(headers, raw)
    except PaymentError as exc:
        # A verification call that failed says nothing about the signature (F21/F22):
        # the row stays unverified and the reconciler remains the authority.
        logger.error("webhooks.verify.error class=%s code=%s", exc.category, exc.code)
        return "not-attempted", f"verify_error:{exc.category}"
    except ValueError:
        # The adapter parses the body inside the signature call, so a delivery of broken
        # JSON arrives as a ValueError and cannot be verified. The traceback is logged
        # because wiring a bad router raises this class too, and the responder must be
        # able to tell the two apart rather than being told it was PayPal's body.
        logger.error("webhooks.verify.value_error", exc_info=True)
        return "not-attempted", "verify_error:value_error"
    return ("verified", "verified") if verified else ("rejected", "rejected:signature")


@router.post(
    "/webhooks/paypal",
    response_model=schemas.WebhookAck,
    operation_id="webhooks_paypal",
)
async def webhooks_paypal(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> schemas.WebhookAck:
    raw = await request.body()
    headers = _sanitized_headers(request)
    payload = json_object(raw.decode("utf-8", errors="replace"))
    settings = _settings(request)
    event_id = str(payload.get("id") or headers.get("paypal-transmission-id") or uuid.uuid4())
    event_type = str(payload.get("event_type") or "UNKNOWN")
    stored = await session.scalar(
        text(
            "INSERT INTO webhook_events "
            "(id, paypal_event_id, event_type, raw_body, verified, verification_detail) "
            "VALUES (:id, :event_id, :event_type, :raw_body, false, :detail) "
            "ON CONFLICT (paypal_event_id) DO NOTHING RETURNING id"
        ),
        {
            "id": uuid.uuid4(),
            "event_id": event_id,
            "event_type": event_type,
            "raw_body": raw.decode("utf-8", errors="replace"),
            "detail": "received_headers=" + json.dumps(headers, sort_keys=True),
        },
    )
    if stored is None:
        # A duplicate delivery: already stored, already answered for. 200, no re-processing.
        # The early commit below narrows this: if the process died between the commit and
        # the enqueue, the redelivery is absorbed here and that one acceleration hint is
        # lost. Webhooks accelerate and a GET confirms (P4), so the reconciler still
        # settles the money -- which is why absorbing is allowed to stop.
        logger.info("webhooks.duplicate event_id=%s", event_id)
        return schemas.WebhookAck()
    # The raw body and sanitised headers are stored first, and the row is on its way
    # before anything can fail: S5's evidence survives a later 500 or a refused
    # signature (``paypal-adapter.md`` section 8).
    await session.commit()

    row_id = uuid.UUID(str(stored))
    outcome, detail = await _verification(request, settings, headers, raw)
    if outcome == "not-attempted":
        # The row keeps exactly what ingest stored, including the header record S5's
        # evidence depends on. The reconciler stays the only path that moves money
        # (P4, and IT-6's "or the reconciler is the only path").
        return schemas.WebhookAck()
    if outcome == "rejected":
        # Configured and refused: the body and headers stay, nothing is processed, and
        # the answer is api.md's 400. No webhook error code exists in
        # config-and-errors.md, so the generic request-failure code carries it rather
        # than an invented one.
        await session.execute(
            text(
                "UPDATE webhook_events SET status = 'REJECTED'::webhook_status, "
                "verification_detail = verification_detail || ' verify=' || :detail "
                "WHERE id = :id"
            ),
            {"detail": detail, "id": row_id},
        )
        logger.error("webhooks.rejected event_id=%s type=%s", event_id, event_type)
        await session.commit()
        raise HTTPException(400, "VALIDATION_ERROR")

    await session.execute(
        text(
            "UPDATE webhook_events SET verified = true, "
            "verification_detail = verification_detail || ' verify=' || :detail "
            "WHERE id = :id"
        ),
        {"detail": detail, "id": row_id},
    )
    await PostgresJobQueue().enqueue(
        session,
        "webhook.process",
        {"webhook_event_id": str(row_id)},
        concurrency_key=f"wh:{row_id}",
    )
    return schemas.WebhookAck()
