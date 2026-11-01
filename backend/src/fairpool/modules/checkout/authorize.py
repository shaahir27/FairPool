"""Approval checks and the server-side authorization flow (T04A02; BO-01..BO-05, BO-18..BO-20).

Contract: ``paypal-adapter.md`` sections 3, 4 and 6, ``state-machines.md`` BO-01 to
BO-05 and BO-18 to BO-20, FR-CK-05, FR-ID-04, I7.

This module owns the three triggers a checkout has:

* ``buyer.continue`` -- create the order with key ``create:{buyer_order_id}:{attempt}``
  and move the seat OFFERED to ORDER_CREATED through the engine (BO-01);
* ``buyer.return`` / ``buyer.approved_callback`` / ``checkout_return`` -- fetch the
  order from PayPal, run every FR-CK-05 check and only then apply BO-02. A failed
  check applies BO-18 (REJECTED) and never authorizes. The return URL is a hint:
  the only thing read from it is a provider id used to look up a row FairPool
  already wrote (FR-CK-05, INT-7);
* ``job:order.authorize`` -- BO-03 (lock and seat horizon, I7), the authorize call
  with key ``auth:{buyer_order_id}``, then BO-04, BO-05 or BO-20 from the
  **authorization object's** status. An unknown outcome leaves the order
  AUTHORIZING and is never retried under a new key (I9, V8).

No PayPal host is reachable from here: the gateway arrives as a structural
protocol supplied by the composition root, and the module imports no HTTP client
(I2, ``checkout/test_checkout_engine`` imports proof).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.checkout import BuyerOrder, PayPalAuthorization, PayPalOrder
from fairpool.db.models.enums import BuyerOrderStatus
from fairpool.db.models.pools import Lot
from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.payments import (
    CreateOrderRequest,
    Payee,
    PaymentError,
)
from fairpool.domain.payments import (
    PayPalAuthorization as GatewayAuthorization,
)
from fairpool.domain.payments import (
    PayPalOrder as GatewayOrder,
)
from fairpool.domain.states import MACHINES
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from fairpool.ports import (
    AllocationReadService,
    AwardView,
    Clock,
    JobQueue,
    MerchantDirectory,
    PayeeRef,
)

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.authorize")

#: Buyer-order states that still hold a seat; the payer-key uniqueness query only
#: looks at these (``db-schema.md`` active statuses, FR-ID-04).
ACTIVE_STATUSES: Final[tuple[str, ...]] = MACHINES["buyer_order"].active

#: ``DEDUPE_MODE`` values the payer-key check understands (config-and-errors.md).
DEDUPE_MODES: Final[frozenset[str]] = frozenset({"full", "two_keys", "checkout_only"})


class AuthorizeGateway(Protocol):
    """The PayPal calls this module owns (``paypal-adapter.md`` section 2)."""

    async def create_order(self, req: CreateOrderRequest) -> GatewayOrder: ...

    async def get_order(self, paypal_order_id: str) -> GatewayOrder: ...

    async def authorize_order(self, paypal_order_id: str, *, request_key: str) -> GatewayOrder: ...

    async def void_authorization(self, auth_id: str) -> None: ...


class CheckoutRouter(Protocol):
    """The payment router as checkout sees it (``domain-ports.md`` section 4.4)."""

    name: str
    gateway: AuthorizeGateway

    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee: ...


def payer_account_key(hmac_key: str, payer_id: str) -> str:
    """``HMAC(HMAC_KEY, payer_id)`` hex, the only form a payer id may be stored in.

    ``modules.identity`` computes the linked-account key with the same formula but
    lives in the other module group, which checkout may not import
    (``tools/check_imports.py`` rule 5); this three-line primitive is the shared
    formula from BD-12 and is all the equality check in ``DEDUPE_MODE=full`` needs.
    """
    return hmac.new(hmac_key.encode(), payer_id.encode(), hashlib.sha256).hexdigest()


def _payee_reason(result: GatewayOrder, payee: Payee) -> str | None:
    """Every payee clause of FR-CK-05; a missing payee is never a pass (V2)."""
    if result.payee_email is None and result.payee_merchant_id is None:
        return "the order carries neither payee email nor payee merchant id"
    if result.payee_email is not None:
        if payee.email is None or result.payee_email.lower() != payee.email.lower():
            return "payee email does not match the stamped router payee"
    if (
        result.payee_merchant_id is not None
        and payee.merchant_id is not None
        and result.payee_merchant_id != payee.merchant_id
    ):
        return "payee merchant id does not match the configured seller"
    return None


class CheckoutAuthorizeHandlers:
    """``offers_continue``, ``offers_approved``, ``checkout_return`` and ``order.authorize``."""

    def __init__(
        self,
        *,
        engine: CheckoutEngine,
        clock: Clock,
        jobs: JobQueue,
        allocations: AllocationReadService,
        directory: MerchantDirectory,
        router: CheckoutRouter,
        hmac_key: str,
        allowed_payer_countries: tuple[str, ...],
        dedupe_mode: str,
        public_base_url: str,
        payload_level: int = 0,
        return_path: str = "/api/v1/checkout/return",
        cancel_path: str = "/api/v1/checkout/cancel",
    ) -> None:
        if dedupe_mode not in DEDUPE_MODES:
            raise ApplicationError("VALIDATION_ERROR")
        self.engine = engine
        self.clock = clock
        self.jobs = jobs
        self.allocations = allocations
        self.directory = directory
        self.router = router
        self.hmac_key = hmac_key
        self.allowed_payer_countries = frozenset(
            country.upper() for country in allowed_payer_countries
        )
        self.dedupe_mode = dedupe_mode
        self.public_base_url = public_base_url.rstrip("/")
        self.payload_level = payload_level
        self.return_path = return_path
        self.cancel_path = cancel_path

    # ---------------------------------------------------------- buyer.continue

    async def continue_order(
        self, session: AsyncSession, *, buyer_order_id: UUID
    ) -> dict[str, Any]:
        """BO-01: create the PayPal order once per attempt and move the seat."""
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.OFFERED):
            # Already created (or past it): hand back the stored provider order so a
            # repeated approval popup is harmless (N9).
            record = await self._latest_record(session, buyer_order_id)
            return {
                "buyer_order_id": str(buyer_order_id),
                "status": str(order.status),
                "paypal_order_id": None if record is None else record.paypal_order_id,
                "approve_url": None if record is None else record.approve_url,
            }
        lot = await session.scalar(select(Lot).where(Lot.id == order.lot_id))
        if lot is None:
            raise ApplicationError("INTEGRITY_ERROR")
        award = await self.allocations.get_award(session, order.lot_id)
        payee = await self._payee(session, award)
        pool = await session.scalar(select(Pool).where(Pool.id == lot.pool_id))
        title = (
            "FairPool order" if pool is None else str(pool.template.get("title", "FairPool order"))
        )
        request = CreateOrderRequest(
            buyer_order_id=str(order.id),
            attempt=int(order.current_attempt),
            amount_cents=int(order.total_cents),
            breakdown={str(key): int(value) for key, value in dict(order.breakdown).items()},
            description=title,
            reference_id=str(order.id),
            payee=payee,
            return_url=f"{self.public_base_url}{self.return_path}",
            cancel_url=f"{self.public_base_url}{self.cancel_path}",
            shipping=None,
            payload_level=self.payload_level,
            extra_headers={},
        )
        result = await self.router.gateway.create_order(request)
        # Persist the provider order before the transition that will name it (I9).
        await self._record_order(session, order, result, approval_channel="redirect")
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="ORDER_CREATED",
                trigger="buyer.continue",
                actor="buyer",
            ),
        )
        return {
            "buyer_order_id": str(buyer_order_id),
            "status": str(BuyerOrderStatus.ORDER_CREATED),
            "paypal_order_id": result.id,
            "approve_url": result.approve_url,
        }

    # ------------------------------------------------ approval checks (BO-02)

    async def approved(
        self,
        session: AsyncSession,
        *,
        buyer_order_id: UUID,
        trigger: str | None = None,
    ) -> dict[str, Any]:
        """GET the order, run FR-CK-05, then BO-02 or BO-18."""
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.ORDER_CREATED):
            # A retry after approval/rejection/expiry has nothing left to decide.
            return {"buyer_order_id": str(buyer_order_id), "status": str(order.status)}
        record = await self._latest_record(session, buyer_order_id)
        if record is None:
            raise ApplicationError("INTEGRITY_ERROR")
        reason, result = await self._recheck(
            session, order=order, record=record, trigger=trigger, actor="buyer"
        )
        if reason is not None:
            # BO-18: a policy failure never authorizes and frees the seat.
            return {
                "buyer_order_id": str(buyer_order_id),
                "status": str(BuyerOrderStatus.REJECTED),
                "reject_reason": reason,
            }
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="APPROVED",
                trigger=trigger,
                observation=Observation(
                    "approval",
                    result.status,
                    result.id,
                    amount_cents=int(result.amount_cents),
                    currency=result.currency,
                    checks_passed=True,
                ),
                actor="buyer",
            ),
        )
        return {"buyer_order_id": str(buyer_order_id), "status": str(BuyerOrderStatus.APPROVED)}

    async def checkout_return(
        self, session: AsyncSession, *, token: str | None, user_id: UUID | None = None
    ) -> dict[str, Any]:
        """``GET /checkout/return``: the token only looks up our own order row."""
        if not token:
            raise ApplicationError("NOT_FOUND")
        record = await session.scalar(
            select(PayPalOrder).where(PayPalOrder.paypal_order_id == token)
        )
        if record is None:
            # An unknown token authorises nothing; the query string is not evidence.
            raise ApplicationError("NOT_FOUND")
        if user_id is not None:
            owner = await session.scalar(
                select(PoolEntry.user_id)
                .join(BuyerOrder, BuyerOrder.entry_id == PoolEntry.id)
                .where(BuyerOrder.id == record.buyer_order_id)
            )
            if owner != user_id:
                raise ApplicationError("NOT_FOUND")
        return await self.approved(session, buyer_order_id=record.buyer_order_id, trigger=None)

    async def _approval_reason(
        self,
        session: AsyncSession,
        *,
        result: GatewayOrder,
        order: BuyerOrder,
        pool_id: UUID,
        payee: Payee,
    ) -> str | None:
        """Every FR-CK-05 clause in the order the contract lists them."""
        if result.status != "APPROVED" or result.intent != "AUTHORIZE":
            return "STATUS_NOT_APPROVED"
        if result.currency != "USD":
            return "CURRENCY_MISMATCH"
        if int(result.amount_cents) != int(order.total_cents):
            return "AMOUNT_MISMATCH"
        payee_reason = _payee_reason(result, payee)
        if payee_reason is not None:
            return "PAYEE_MISMATCH"
        if result.payer_country is None or result.payer_country.upper() not in (
            self.allowed_payer_countries
        ):
            return "WRONG_COUNTRY"
        if result.payer_id is None:
            # Without the provider's payer id no uniqueness claim can be made.
            return "PAYER_MISMATCH"
        key = payer_account_key(self.hmac_key, result.payer_id)
        if self.dedupe_mode == "full":
            entry_key = await session.scalar(
                select(PoolEntry.paypal_account_key).where(PoolEntry.id == order.entry_id)
            )
            if entry_key is None or str(entry_key) != key:
                return "PAYER_MISMATCH"
        if await self._key_held_elsewhere(session, pool_id=pool_id, order_id=order.id, key=key):
            return "DUPLICATE_PAYER"
        return None

    async def _key_held_elsewhere(
        self, session: AsyncSession, *, pool_id: UUID, order_id: UUID, key: str
    ) -> bool:
        found = await session.scalar(
            text(
                "SELECT 1 FROM paypal_orders po "
                "JOIN buyer_orders bo ON bo.id = po.buyer_order_id "
                "JOIN lots l ON l.id = bo.lot_id "
                "WHERE l.pool_id = :pool AND bo.id <> :order AND po.payer_key = :key "
                "AND bo.status::text = ANY(CAST(:active AS text[])) LIMIT 1"
            ),
            {"pool": pool_id, "order": order_id, "key": key, "active": list(ACTIVE_STATUSES)},
        )
        return found is not None

    # ---------------------------------------------------- job:order.authorize

    async def authorize(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """BO-19, then BO-03, then BO-04 / BO-05 / BO-20 for one approved seat."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        record = await self._latest_record(session, buyer_order_id)
        if record is None:
            raise ApplicationError("INTEGRITY_ERROR")
        status = str(order.status)
        if status == str(BuyerOrderStatus.APPROVED):
            # BO-19: the checks are re-run against a fresh GET before authorizing,
            # so a policy failure found between approval and authorize never moves
            # money (the trigger exists for exactly this window).
            reason, _ = await self._recheck(
                session, order=order, record=record, trigger="job:order.authorize", actor="worker"
            )
            if reason is not None:
                return
            if not await self._to_authorizing(session, order):
                return
            status = str(BuyerOrderStatus.AUTHORIZING)
        if status != str(BuyerOrderStatus.AUTHORIZING):
            # AUTHORIZED, terminal or not yet approved: nothing this trigger may do.
            return
        expected = int(order.total_cents)
        try:
            result = await self.router.gateway.authorize_order(
                record.paypal_order_id, request_key=f"auth:{buyer_order_id}"
            )
        except PaymentError as exc:
            await self._authorize_error(session, buyer_order_id, record, exc)
            return
        if not result.authorizations:
            # No authorization object is an unknown outcome, never a success (V8).
            logger.error(
                "checkout.authorize.no_resource buyer_order_id=%s paypal_order_id=%s",
                buyer_order_id,
                record.paypal_order_id,
            )
            return
        authorization = result.authorizations[0]
        await self._record_authorization(session, buyer_order_id, record, authorization)
        observation = Observation(
            "authorization",
            authorization.status,
            authorization.id,
            amount_cents=int(authorization.amount_cents),
        )
        if authorization.status == "CREATED":
            if int(authorization.amount_cents) != expected:
                # N5: an authorization for another amount is voided at once.
                await self.router.gateway.void_authorization(authorization.id)
                await self.engine.apply(
                    session,
                    TransitionRequest(
                        buyer_order_id=buyer_order_id,
                        to_state="REJECTED",
                        trigger="job:order.authorize",
                        observation=observation,
                        reject_reason="AMOUNT_MISMATCH",
                    ),
                )
                return
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=buyer_order_id,
                    to_state="AUTHORIZED",
                    trigger="job:order.authorize",
                    observation=observation,
                ),
            )
            return
        if authorization.status in {"DENIED", "EXPIRED", "VOIDED"}:
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=buyer_order_id,
                    to_state="AUTH_FAILED",
                    trigger="job:order.authorize",
                    observation=observation,
                ),
            )
            return
        # PENDING and anything unrecognised: stay AUTHORIZING (adapter section 4).
        logger.info(
            "checkout.authorize.pending buyer_order_id=%s status=%s",
            buyer_order_id,
            authorization.status,
        )

    async def _recheck(
        self,
        session: AsyncSession,
        *,
        order: BuyerOrder,
        record: PayPalOrder,
        trigger: str | None,
        actor: str,
    ) -> tuple[str | None, GatewayOrder]:
        """Re-run FR-CK-05 from a fresh GET, persisting the record it read.

        BO-18 (on approval) and BO-19 (before authorizing) are the same check on the
        same resources; a failure applies the REJECTED edge of the trigger that owns
        the call and frees the seat. The fresh result also feeds the caller's own
        observation, so the GET is never made twice.
        """
        result = await self.router.gateway.get_order(record.paypal_order_id)
        lot = await session.scalar(select(Lot).where(Lot.id == order.lot_id))
        if lot is None:
            raise ApplicationError("INTEGRITY_ERROR")
        award = await self.allocations.get_award(session, order.lot_id)
        payee = await self._payee(session, award)
        reason = await self._approval_reason(
            session, result=result, order=order, pool_id=lot.pool_id, payee=payee
        )
        payer_key = (
            None if result.payer_id is None else payer_account_key(self.hmac_key, result.payer_id)
        )
        await self._record_order(
            session,
            order,
            result,
            approval_channel=record.approval_channel or "redirect",
            payer_key=payer_key,
        )
        if reason is None:
            return None, result
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=order.id,
                to_state="REJECTED",
                trigger=trigger,
                observation=Observation(
                    "approval",
                    result.status,
                    result.id,
                    amount_cents=int(result.amount_cents),
                    currency=result.currency,
                    checks_passed=False,
                ),
                reject_reason=reason,
                actor=actor,
            ),
        )
        return reason, result

    async def _to_authorizing(self, session: AsyncSession, order: BuyerOrder) -> bool:
        view = await self.allocations.get_lot(session, order.lot_id)
        wall_now = await self.clock.db_wall_now(session)
        grace = int(getattr(view, "capture_grace_s", 120))
        try:
            # BO-03 needs the seat horizon this handler supplies, which is exactly
            # what ``engine.decide`` cannot carry; ``apply`` re-checks the same
            # guards under the same locks (I7).
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=order.id,
                    to_state="AUTHORIZING",
                    trigger="job:order.authorize",
                    seat_locked_until=wall_now + timedelta(seconds=grace),
                ),
            )
        except IllegalTransition:
            # The seat or the lot moved under us; the money path must not run and
            # the order keeps the state the contract gives it (F5).
            return False
        return True

    async def _authorize_error(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        record: PayPalOrder,
        exc: PaymentError,
    ) -> None:
        if exc.code == "ORDER_NOT_APPROVED":
            # V4: a wait, not a failure; the approval callback or reconciler retries.
            return
        if exc.category not in {"TERMINAL", "CONFIG", "BUG"}:
            # RETRYABLE, TOKEN, UNKNOWN: stay AUTHORIZING, never a new key (I9).
            logger.error(
                "checkout.authorize.unknown buyer_order_id=%s category=%s code=%s",
                buyer_order_id,
                exc.category,
                exc.code,
            )
            return
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="AUTH_FAILED",
                trigger="job:order.authorize",
                observation=Observation(
                    "approval",
                    "DENIED",
                    record.paypal_order_id,
                    error_class=exc.category,
                    error_code=exc.code,
                ),
            ),
        )

    # --------------------------------------------------------------- records

    async def _payee(self, session: AsyncSession, award: AwardView) -> Payee:
        reference = await self.directory.get_payee(session, award.merchant_id)
        return self.router.payee_for(award, reference)

    async def _latest_record(
        self, session: AsyncSession, buyer_order_id: UUID
    ) -> PayPalOrder | None:
        return await session.scalar(
            select(PayPalOrder)
            .where(PayPalOrder.buyer_order_id == buyer_order_id)
            .order_by(PayPalOrder.attempt.desc(), PayPalOrder.created_at.desc())
            .limit(1)
        )

    async def _record_order(
        self,
        session: AsyncSession,
        order: BuyerOrder,
        result: GatewayOrder,
        *,
        approval_channel: str,
        payer_key: str | None = None,
    ) -> PayPalOrder:
        record = await session.scalar(
            select(PayPalOrder).where(
                PayPalOrder.buyer_order_id == order.id,
                PayPalOrder.attempt == int(order.current_attempt),
            )
        )
        if record is None:
            record = PayPalOrder(
                id=uuid4(),
                buyer_order_id=order.id,
                attempt=int(order.current_attempt),
                paypal_order_id=result.id,
                status=result.status,
                intent=result.intent,
                amount_cents=int(result.amount_cents),
                raw=dict(result.raw),
            )
            session.add(record)
        record.status = result.status
        record.intent = result.intent
        record.amount_cents = int(result.amount_cents)
        record.payee_email = result.payee_email
        record.payee_merchant_id = result.payee_merchant_id
        record.payer_country = result.payer_country
        # The approval URL is stored for the browser and never logged or audited.
        record.approve_url = result.approve_url
        record.approval_channel = approval_channel
        if payer_key is not None:
            record.payer_key = payer_key
        await session.flush()
        return record

    async def _record_authorization(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        record: PayPalOrder,
        authorization: GatewayAuthorization,
    ) -> None:
        existing = await session.scalar(
            select(PayPalAuthorization).where(
                PayPalAuthorization.paypal_auth_id == authorization.id
            )
        )
        if existing is None:
            session.add(
                PayPalAuthorization(
                    id=uuid4(),
                    buyer_order_id=buyer_order_id,
                    paypal_order_id=record.paypal_order_id,
                    paypal_auth_id=authorization.id,
                    status=authorization.status,
                    amount_cents=int(authorization.amount_cents),
                    expires_at=authorization.expires_at,
                    raw={},
                )
            )
        else:
            existing.status = authorization.status
            existing.amount_cents = int(authorization.amount_cents)
        await session.flush()


__all__ = [
    "ACTIVE_STATUSES",
    "CheckoutAuthorizeHandlers",
    "CheckoutRouter",
    "payer_account_key",
]
