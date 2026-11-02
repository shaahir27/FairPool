"""Buyer checkout: offers, approval hints, return and order status (T04A02, T04X01).

``api.md`` section 2 fixes the routes and sections 3 and 4.1 the bodies. Every route
is owner-scoped (another buyer's id answers ``NOT_FOUND``, exactly like an unknown
one), and none of them decides a transition itself: the offer and callback routes ask
the engine, and the approval/return routes call ``CheckoutAuthorizeHandlers``, which
fetches the order from PayPal and runs the FR-CK-05 checks. The return URL and the
SDK callbacks are hints; the query string and the posted order id are only used to
find a row this server already wrote (FR-CK-05, INT-7).

The graph comes from ``wiring.checkout_services`` and is cached on the app, so the
gateway a test feeds is the same object the route uses.

Phase boundary: ``POST /offers/{id}/continue`` accepts the contracted shipping body,
but storing it (``buyer_orders.shipping_enc``, N14) belongs to T05A01, which owns the
address cipher and the real PayPal payload. The simulated router sends no address,
so this phase stores nothing rather than an unencrypted one.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.config import Settings
from fairpool.db.models.auction import Award
from fairpool.db.models.catalog import EntryReceipt, Pool, PoolEntry
from fairpool.db.models.checkout import (
    BuyerOrder,
    PayPalAuthorization,
    PayPalCapture,
    PayPalOrder,
    PayPalRefund,
)
from fairpool.db.models.pools import Lot
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.modules.checkout.engine import TransitionRequest
from fairpool.modules.identity.service import Principal
from fairpool.wiring import CheckoutServices, checkout_services

router = APIRouter()

#: api.md section 4.1: the SDK v6 core script on the Sandbox checkout host.
SDK_URL = "https://www.sandbox.paypal.com/web-sdk/v6/core"
SDK_COMPONENTS = ["paypal-payments"]
SANDBOX_LABEL = "SANDBOX"
FALLBACK_LABEL = "FALLBACK: single stand-in seller"
SINGLE_SELLER_NOTICE = "Sandbox demo: one test seller stands in for the winning merchant."
CAPTURE_ONLY_NOTICE = "Sandbox demo: the lot is captured without a separate authorization hold."
HOLD_NOTICE = (
    "PayPal places a hold for the total shown only after you approve. "
    "The hold is released if this lot does not reach its minimum."
)
#: vault-charge.md section 1: no funds are reserved and PayPal's approval screen
#: shows no amount, so the hold sentence of api.md section 3 is false in this mode.
VAULT_NOTICE = (
    "Nothing is charged or held now, and PayPal's approval screen shows no amount. "
    "FairPool charges this saved account once, after the lot is awarded, for the "
    "final price if it is at or below your maximum."
)
LOTS_MAY_DIFFER_NOTICE = (
    "Separate lots in this pool can end with different winning merchants and prices."
)


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    return settings


def _services(request: Request) -> CheckoutServices:
    """The app's single checkout graph (``app.state.checkout_services`` if injected)."""
    cached: CheckoutServices | None = getattr(request.app.state, "checkout_services", None)
    if cached is not None:
        return cached
    built = checkout_services(_settings(request))
    request.app.state.checkout_services = built
    return built


async def _owned_order(db: AsyncSession, *, buyer_order_id: UUID, user_id: UUID) -> BuyerOrder:
    """Owner-scoped fetch: someone else's order id answers exactly like an unknown one."""
    row = (
        await db.execute(
            select(BuyerOrder, PoolEntry.user_id)
            .join(PoolEntry, PoolEntry.id == BuyerOrder.entry_id)
            .where(BuyerOrder.id == buyer_order_id)
        )
    ).first()
    if row is None or row[1] != user_id:
        raise HTTPException(404, "NOT_FOUND")
    return row[0]


async def _lot(db: AsyncSession, lot_id: UUID) -> Lot:
    lot = await db.scalar(select(Lot).where(Lot.id == lot_id))
    if lot is None:
        raise ApplicationError("INTEGRITY_ERROR")
    return lot


def _fallback_notice(lot: Lot) -> str | None:
    """DEP-4: the screen says so whenever the stand-in routing or the mode applies."""
    if str(lot.payment_router) == "single_seller":
        return SINGLE_SELLER_NOTICE
    if str(lot.payment_mode) == "capture_only":
        return CAPTURE_ONLY_NOTICE
    return None


def _labels(lot: Lot) -> list[str]:
    labels = [SANDBOX_LABEL]
    if _fallback_notice(lot) is not None:
        labels.append(FALLBACK_LABEL)
    return labels


def _hold_notice(lot: Lot) -> str:
    """What happens to the buyer's money, in the language of the stamped mode (M10)."""
    if str(lot.payment_mode) == "vault_charge":
        return VAULT_NOTICE
    return HOLD_NOTICE


def _redirect(request: Request, buyer_order_id: object) -> RedirectResponse:
    base = _settings(request).frontend_base_url.rstrip("/")
    return RedirectResponse(url=f"{base}/orders/{buyer_order_id}", status_code=302)


# ------------------------------------------------------------------- merchants


@router.post(
    "/api/v1/merchant/onboarding/start",
    operation_id="merchant_onboarding_start",
    dependencies=[Security(require_session)],
)
async def merchant_onboarding_start() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/onboarding/return",
    operation_id="merchant_onboarding_return",
    dependencies=[Security(require_session)],
)
async def merchant_onboarding_return(
    code: str | None = Query(None), state: str | None = Query(None)
) -> None:
    raise NotImplementedError("route arrives in a later phase")


# ----------------------------------------------------------------- offer views


@router.get(
    "/api/v1/offers/{buyer_order_id}",
    response_model=schemas.OfferResponse,
    operation_id="offers_get",
)
async def offers_get(
    buyer_order_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The offer disclosure: catalog terms, awarded totals and the buyer's cap."""
    services = _services(request)
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    lot = await _lot(db, order.lot_id)
    award = await db.scalar(select(Award).where(Award.lot_id == lot.id))
    pool = await db.scalar(select(Pool).where(Pool.id == lot.pool_id))
    cap_cents = await db.scalar(select(PoolEntry.cap_cents).where(PoolEntry.id == order.entry_id))
    if award is None or pool is None or cap_cents is None:
        raise ApplicationError("INTEGRITY_ERROR")
    payee = await services.directory.get_payee(db, award.merchant_id)
    template = pool.template
    breakdown = dict(order.breakdown)
    return {
        "buyer_order_id": order.id,
        "status": str(order.status),
        "merchant": {"display_name": payee.display_name},
        "product": {
            "title": str(template.get("title", "")),
            "variant": template.get("variant"),
            "condition": str(template.get("condition", "")),
            "bundle_contents": [str(item) for item in template.get("bundle_contents", [])],
        },
        "terms": {
            "delivery_sla_days": int(template["delivery_sla_days"]),
            "returns_days": int(template["min_return_days"]),
        },
        "totals": {
            "item_cents": int(breakdown["item_cents"]),
            "shipping_cents": int(breakdown["shipping_cents"]),
            "tax_cents": int(breakdown["tax_cents"]),
            "total_cents": int(order.total_cents),
            "cap_cents": int(cap_cents),
        },
        "offer_expires_at": order.offer_expires_at,
        "notices": {
            "hold": _hold_notice(lot),
            "lots_may_differ": LOTS_MAY_DIFFER_NOTICE,
            "fallback": _fallback_notice(lot),
        },
    }


@router.post(
    "/api/v1/offers/{buyer_order_id}/continue",
    response_model=schemas.ContinueResponse,
    operation_id="offers_continue",
)
async def offers_continue(
    buyer_order_id: UUID,
    payload: schemas.ContinueRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """BO-01: create the provider order once and hand the browser its approval URL.

    ``payload.shipping`` is sealed into ``buyer_orders.shipping_enc`` before the
    provider call (N14); the browser still sends no amount: the total is the stored
    order's (I3).
    """
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    result = await _services(request).authorize.continue_order(
        db, buyer_order_id=order.id, shipping=payload.shipping.model_dump()
    )
    paypal_order_id = result.get("paypal_order_id")
    approve_url = result.get("approve_url")
    if paypal_order_id is None or approve_url is None:
        # Past BO-01 with no stored provider order: there is nothing to approve.
        raise ApplicationError("ORDER_STATE_INVALID")
    return {
        "paypal_order_id": str(paypal_order_id),
        "approve_url": str(approve_url),
        "approval_ui": _settings(request).paypal_approval_ui,
    }


@router.post(
    "/api/v1/offers/{buyer_order_id}/decline",
    operation_id="offers_decline",
)
async def offers_decline(
    buyer_order_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """BO-21 from OFFERED, BO-22 from ORDER_CREATED; the engine decides which."""
    services = _services(request)
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    if str(order.status) == "DECLINED":
        return {"buyer_order_id": str(order.id), "status": "DECLINED"}
    # The whitelist stores BO-22's callback alternatives as one trigger string, so the
    # pair (from, to) selects the transition, exactly as ``CheckoutAuthorizeHandlers``
    # does for BO-02 and BO-18. Nothing here invents a trigger the contract lacks.
    decision = await services.engine.decide(
        db, buyer_order_id=order.id, to_state="DECLINED", trigger=None
    )
    if decision.illegal_pair or decision.reason is not None:
        # The whitelist or a guard refuses this seat here (for example a vault-mode
        # lot, which has no buyer payment window): no transition is invented.
        raise ApplicationError("ORDER_STATE_INVALID")
    try:
        await services.engine.apply(
            db,
            TransitionRequest(
                buyer_order_id=order.id,
                to_state="DECLINED",
                trigger=None,
                actor="buyer",
            ),
        )
    except IllegalTransition:
        # A decline that lost the race (the timer or a capture moved the seat) is the
        # contract's state answer, never a 500 (M12).
        raise ApplicationError("ORDER_STATE_INVALID") from None
    return {"buyer_order_id": str(order.id), "status": "DECLINED"}


# -------------------------------------------------------------- return/cancel


@router.get("/api/v1/checkout/return", operation_id="checkout_return")
async def checkout_return(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    token: str | None = Query(None),
    payer_id: str | None = Query(None, alias="PayerID"),
):
    """The provider redirect: the token only finds our row, then PayPal's GET decides."""
    result = await _services(request).authorize.checkout_return(
        db, token=token, user_id=principal.user_id
    )
    return _redirect(request, result["buyer_order_id"])


@router.get("/api/v1/checkout/cancel", operation_id="checkout_cancel")
async def checkout_cancel(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    token: str | None = Query(None),
):
    """api.md: an ORDER_CREATED order moves to DECLINED (BO-22), then redirect."""
    if not token:
        raise ApplicationError("NOT_FOUND")
    record = await db.scalar(select(PayPalOrder).where(PayPalOrder.paypal_order_id == token))
    if record is None:
        raise ApplicationError("NOT_FOUND")
    owner = await db.scalar(
        select(PoolEntry.user_id)
        .join(BuyerOrder, BuyerOrder.entry_id == PoolEntry.id)
        .where(BuyerOrder.id == record.buyer_order_id)
    )
    if owner != principal.user_id:
        raise ApplicationError("NOT_FOUND")
    services = _services(request)
    decision = await services.engine.decide(
        db, buyer_order_id=record.buyer_order_id, to_state="DECLINED", trigger=None
    )
    if not decision.illegal_pair and decision.reason is None:
        try:
            await services.engine.apply(
                db,
                TransitionRequest(
                    buyer_order_id=record.buyer_order_id,
                    to_state="DECLINED",
                    trigger=None,
                    actor="buyer",
                ),
            )
        except IllegalTransition:
            # The cancel hint is only a hint: a seat that moved on is not an error the
            # browser should see, and the redirect still happens (M12).
            pass
    return _redirect(request, record.buyer_order_id)


# ---------------------------------------------------------------- order status


@router.get(
    "/api/v1/orders/{buyer_order_id}",
    response_model=schemas.OrderStatusResponse,
    operation_id="orders_get",
)
async def orders_get(
    buyer_order_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The order status page: state, its history and the provider resource states."""
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    lot = await _lot(db, order.lot_id)
    rows = (
        await db.execute(
            text(
                "SELECT action, created_at FROM audit_log WHERE subject_type = 'buyer_order' "
                "AND subject_id = :id ORDER BY seq"
            ),
            {"id": str(order.id)},
        )
    ).all()
    history = [
        {
            "status": str(action).removeprefix("buyer_order.").upper(),
            "at": created_at.isoformat(),
        }
        for action, created_at in rows
    ]
    return {
        "buyer_order_id": order.id,
        "status": str(order.status),
        "lot_status": str(lot.status),
        "total_cents": int(order.total_cents),
        "history": history,
        "paypal": {
            "authorization_status": await _latest_status(
                db, PayPalAuthorization, order.id, PayPalAuthorization.paypal_auth_id
            ),
            "capture_status": await _latest_status(
                db, PayPalCapture, order.id, PayPalCapture.paypal_capture_id
            ),
            "refund_status": await _latest_status(
                db, PayPalRefund, order.id, PayPalRefund.paypal_refund_id
            ),
        },
        "labels": _labels(lot),
    }


async def _latest_status(
    db: AsyncSession, model: Any, buyer_order_id: UUID, order_by: Any
) -> str | None:
    """The newest provider resource's status for one order; never a payment signal."""
    value = await db.scalar(
        select(model.status)
        .where(model.buyer_order_id == buyer_order_id)
        .order_by(order_by.desc())
        .limit(1)
    )
    return None if value is None else str(value)


@router.post(
    "/api/v1/orders/{buyer_order_id}/withdraw",
    operation_id="orders_withdraw",
    dependencies=[Security(require_session)],
)
async def orders_withdraw(buyer_order_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


# -------------------------------------------------------------------- config


@router.get(
    "/api/v1/checkout/config",
    response_model=schemas.CheckoutConfigResponse,
    operation_id="checkout_config",
)
async def checkout_config(request: Request):
    """Public SDK values only: no secret, no token, no amount (api.md section 4.1)."""
    settings = _settings(request)
    return {
        "approval_ui": settings.paypal_approval_ui,
        "sdk_auth": settings.paypal_sdk_auth,
        "client_id": settings.paypal_client_id,
        "sdk_url": SDK_URL,
        "components": SDK_COMPONENTS,
        "page_type": "checkout",
        "currency": "USD",
        "labels": [SANDBOX_LABEL],
    }


@router.get(
    "/api/v1/checkout/client-token",
    response_model=schemas.ClientTokenResponse,
    operation_id="checkout_client_token",
    dependencies=[Security(require_session)],
)
async def checkout_client_token() -> None:
    raise NotImplementedError("route arrives in a later phase")


# ------------------------------------------------------------------- callbacks


@router.post(
    "/api/v1/offers/{buyer_order_id}/approved",
    response_model=schemas.ApprovedResponse,
    operation_id="offers_approved",
)
async def offers_approved(
    buyer_order_id: UUID,
    payload: schemas.ApprovedRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The SDK ``onApprove`` hint: verify it names our order, then run the checks."""
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    known = await db.scalar(
        select(PayPalOrder.id).where(
            PayPalOrder.buyer_order_id == order.id,
            PayPalOrder.paypal_order_id == payload.paypal_order_id,
        )
    )
    if known is None:
        # A reported order id this buyer order never created cannot be approved.
        raise ApplicationError("VALIDATION_ERROR")
    result = await _services(request).authorize.approved(db, buyer_order_id=order.id, trigger=None)
    status = str(result.get("status"))
    if status == "REJECTED":
        return {
            "buyer_order_id": order.id,
            "status": "REJECTED",
            "reason": None if result.get("reject_reason") is None else str(result["reject_reason"]),
        }
    if status in {"EXPIRED", "DECLINED"}:
        return {"buyer_order_id": order.id, "status": "EXPIRED", "reason": None}
    # APPROVED, or a replay after the seat moved on: the approval itself succeeded.
    return {"buyer_order_id": order.id, "status": "APPROVED", "reason": None}


@router.post(
    "/api/v1/offers/{buyer_order_id}/cancelled",
    operation_id="offers_cancelled",
)
async def offers_cancelled(
    buyer_order_id: UUID,
    payload: schemas.CancelledRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The SDK ``onCancel`` hint: ORDER_CREATED moves to DECLINED (BO-22), idempotently."""
    services = _services(request)
    order = await _owned_order(db, buyer_order_id=buyer_order_id, user_id=principal.user_id)
    if str(order.status) == "DECLINED":
        return {"buyer_order_id": str(order.id), "status": "DECLINED", "reason": None}
    decision = await services.engine.decide(
        db,
        buyer_order_id=order.id,
        to_state="DECLINED",
        trigger=None,
    )
    if decision.illegal_pair or decision.reason is not None:
        raise ApplicationError("ORDER_STATE_INVALID")
    try:
        await services.engine.apply(
            db,
            TransitionRequest(
                buyer_order_id=order.id,
                to_state="DECLINED",
                trigger=None,
                actor="buyer",
            ),
        )
    except IllegalTransition:
        raise ApplicationError("ORDER_STATE_INVALID") from None
    return {"buyer_order_id": str(order.id), "status": "DECLINED", "reason": None}


@router.get(
    "/api/v1/me/orders",
    response_model=schemas.MeOrderList,
    operation_id="me_orders",
)
async def me_orders(
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """Every order of this buyer with the receipt that goes with it."""
    rows = (
        await db.execute(
            select(BuyerOrder, EntryReceipt)
            .join(PoolEntry, PoolEntry.id == BuyerOrder.entry_id)
            .outerjoin(EntryReceipt, EntryReceipt.entry_id == BuyerOrder.entry_id)
            .where(PoolEntry.user_id == principal.user_id)
            .order_by(BuyerOrder.created_at.desc(), BuyerOrder.id)
        )
    ).all()
    items: list[dict[str, Any]] = []
    for order, receipt in rows:
        items.append(
            {
                "buyer_order_id": order.id,
                "lot_id": order.lot_id,
                "status": str(order.status),
                "total_cents": int(order.total_cents),
                "receipt": None if receipt is None else _receipt(receipt),
            }
        )
    return {"items": items}


def _receipt(receipt: EntryReceipt) -> dict[str, Any]:
    return {
        "commitment": str(receipt.commitment),
        "salt_hex": str(receipt.salt),
        "signature": str(receipt.signature),
        "signed_at": receipt.signed_at.isoformat(),
    }
