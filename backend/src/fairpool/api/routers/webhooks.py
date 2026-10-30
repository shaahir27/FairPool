"""PayPal webhook receiver (T01A03; signature verification arrives in T06A02).

PH1 deliberately stores the exact raw body and a sanitised header subset and
returns 200: it is the deployed listener that S5 and the later handler need.
The real handler replaces the body with signature verification and returns
400 for unverified requests.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.db.session import get_session

router = APIRouter()

_ALLOWED_HEADERS = (
    "paypal-transmission-id",
    "paypal-transmission-time",
    "paypal-cert-url",
    "paypal-auth-algo",
    "content-type",
    "user-agent",
)


def _sanitized_headers(request: Request) -> dict[str, str]:
    return {name: request.headers[name] for name in _ALLOWED_HEADERS if name in request.headers}


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
    payload: dict[str, Any] = {}
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            payload = decoded
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass

    event_id = str(payload.get("id") or headers.get("paypal-transmission-id") or uuid.uuid4())
    event_type = str(payload.get("event_type") or "UNKNOWN")
    await session.execute(
        text(
            "INSERT INTO webhook_events "
            "(id, paypal_event_id, event_type, raw_body, verified, verification_detail) "
            "VALUES (:id, :event_id, :event_type, :raw_body, false, :detail) "
            "ON CONFLICT (paypal_event_id) DO NOTHING"
        ),
        {
            "id": uuid.uuid4(),
            "event_id": event_id,
            "event_type": event_type,
            "raw_body": raw.decode("utf-8", errors="replace"),
            "detail": "stub_headers=" + json.dumps(headers, sort_keys=True),
        },
    )
    return schemas.WebhookAck()
