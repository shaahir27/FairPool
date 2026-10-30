"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_session

router = APIRouter()


@router.get(
    "/api/v1/paypal/login/start",
    response_model=schemas.PayPalLoginStartResponse,
    operation_id="paypal_login_start",
    dependencies=[Security(require_session)],
)
async def paypal_login_start() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/paypal/login/callback",
    response_model=schemas.PayPalLoginCallbackResponse,
    operation_id="paypal_login_callback",
    dependencies=[Security(require_session)],
)
async def paypal_login_callback(
    code: str | None = Query(None), state: str | None = Query(None)
) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.delete(
    "/api/v1/paypal/link",
    operation_id="paypal_link_delete",
    dependencies=[Security(require_session)],
)
async def paypal_link_delete() -> None:
    raise NotImplementedError("route arrives in a later phase")
