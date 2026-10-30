"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Security

from fairpool.api import schemas
from fairpool.api.deps import require_merchant, require_session

router = APIRouter()


@router.post(
    "/api/v1/merchant/onboarding/start",
    operation_id="merchant_onboarding_start",
    dependencies=[Security(require_merchant)],
)
async def merchant_onboarding_start() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/onboarding/return",
    operation_id="merchant_onboarding_return",
    dependencies=[Security(require_merchant)],
)
async def merchant_onboarding_return(
    code: str | None = Query(None), state: str | None = Query(None)
) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/offers/{buyer_order_id}",
    response_model=schemas.OfferResponse,
    operation_id="offers_get",
    dependencies=[Security(require_session)],
)
async def offers_get(buyer_order_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/offers/{buyer_order_id}/continue",
    response_model=schemas.ContinueResponse,
    operation_id="offers_continue",
    dependencies=[Security(require_session)],
)
async def offers_continue(buyer_order_id: UUID, payload: schemas.ContinueRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/offers/{buyer_order_id}/decline",
    operation_id="offers_decline",
    dependencies=[Security(require_session)],
)
async def offers_decline(buyer_order_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/checkout/return",
    operation_id="checkout_return",
    dependencies=[Security(require_session)],
)
async def checkout_return(
    token: str | None = Query(None), payer_id: str | None = Query(None, alias="PayerID")
) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/checkout/cancel",
    operation_id="checkout_cancel",
    dependencies=[Security(require_session)],
)
async def checkout_cancel(token: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/orders/{buyer_order_id}",
    response_model=schemas.OrderStatusResponse,
    operation_id="orders_get",
    dependencies=[Security(require_session)],
)
async def orders_get(buyer_order_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/orders/{buyer_order_id}/withdraw",
    operation_id="orders_withdraw",
    dependencies=[Security(require_session)],
)
async def orders_withdraw(buyer_order_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/checkout/config",
    response_model=schemas.CheckoutConfigResponse,
    operation_id="checkout_config",
)
async def checkout_config() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/checkout/client-token",
    response_model=schemas.ClientTokenResponse,
    operation_id="checkout_client_token",
    dependencies=[Security(require_session)],
)
async def checkout_client_token() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/offers/{buyer_order_id}/approved",
    response_model=schemas.ApprovedResponse,
    operation_id="offers_approved",
    dependencies=[Security(require_session)],
)
async def offers_approved(buyer_order_id: UUID, payload: schemas.ApprovedRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/offers/{buyer_order_id}/cancelled",
    operation_id="offers_cancelled",
    dependencies=[Security(require_session)],
)
async def offers_cancelled(buyer_order_id: UUID, payload: schemas.CancelledRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/me/orders",
    response_model=schemas.MeOrderList,
    operation_id="me_orders",
    dependencies=[Security(require_session)],
)
async def me_orders() -> None:
    raise NotImplementedError("route arrives in a later phase")
