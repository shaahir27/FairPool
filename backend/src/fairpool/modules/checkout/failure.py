"""Lot failure: close offers, void authorizations, refund captures, close at net zero.

Contract: ``docs/contracts/state-machines.md`` LS-08 to LS-10 and BO-12 to BO-14,
``docs/contracts/paypal-adapter.md`` sections 3 and 4.

Three rules this module may not break:

* **Every change is a whitelisted transition applied by the engine** (I10). The
  ledger facts come from the engine's declared effects; emitting one here as well
  would void or refund twice.
* **A payment is never inferred** (I4). Void is accepted only after the adapter's
  GET-first rule; a refund is complete only when ``get_refund`` reads COMPLETED.
* **FAILED_CLOSED needs proof, not hope.** The lot closes only when the ledger's
  net paid is zero, no capture is pending and no authorization is still live. A
  capture that completes after this pass is refunded by the next pass, which is
  what F9 proves.

A terminal void or refund failure leaves the lot in FAILING on purpose (F24): a
lot that cannot be balanced must stay visible, not be closed as if it were.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import (
    BuyerOrder,
    PayPalAuthorization,
    PayPalCapture,
)
from fairpool.db.models.checkout import (
    PayPalRefund as PayPalRefundRow,
)
from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import PaymentError, PayPalRefund
from fairpool.modules.checkout.engine import TransitionRequest
from fairpool.modules.checkout.funding import apply_lot_transition, lock_lot
from fairpool.ports import AuditLog, Clock, JobQueue, Ledger

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.failure")

#: How soon ``lot.finalize_fail`` looks again while a capture is still pending.
PENDING_RECHECK_S: Final[int] = 10

#: Buyer-order states that still hold a seat or money during failure.
VOIDABLE_STATES: Final[frozenset[str]] = frozenset({"AUTHORIZED"})
REFUNDABLE_STATES: Final[frozenset[str]] = frozenset({"CAPTURED", "REFUNDING"})
PENDING_STATES: Final[frozenset[str]] = frozenset({"CAPTURING", "CAPTURE_PENDING"})


class FailureGateway(Protocol):
    async def void_authorization(self, auth_id: str) -> None: ...

    async def refund_capture(
        self, capture_id: str, *, amount_cents: int | None, request_key: str
    ) -> PayPalRefund: ...

    async def get_refund(self, refund_id: str) -> PayPalRefund: ...


class FailureService:
    """LS-08 to LS-10 and BO-12 to BO-14 for one lot at a time."""

    def __init__(
        self,
        *,
        engine: Any,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        ledger: Ledger,
        gateway: FailureGateway,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.ledger = ledger
        self.gateway = gateway

    # ------------------------------------------------------------ finalize

    async def finalize_fail(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Close offers, settle every order, then close the lot only at net zero."""
        lot_id = UUID(str(payload["lot_id"]))
        lot = await lock_lot(session, lot_id)
        status = str(lot.status)
        if status == "FAILED_CLOSED":
            return
        if status not in ("FAILING", "CHECKOUT_OPEN", "FUNDING"):
            return
        if status != "FAILING":
            to_status = "FAILING"
            await apply_lot_transition(
                session,
                lot=lot,
                to_status=to_status,
                trigger="job:lot.try_fund",
                audit=self.audit,
                payload={"transition_id": "LS-09" if status == "FUNDING" else "LS-08"},
            )
        await self.close_offers(session, lot_id=lot.id)
        pending = await self._settle_orders(session, lot_id=lot.id)
        if pending:
            now = await self.clock.db_now(session)
            await self.jobs.enqueue(
                session,
                "lot.finalize_fail",
                {"lot_id": str(lot.id)},
                run_at=now + timedelta(seconds=PENDING_RECHECK_S),
                concurrency_key=f"lot:{lot.id}",
                dedupe_key=f"finalize_fail:{lot.id}",
            )
            return
        if not await self.net_zero(session, lot_id=lot.id):
            return
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="FAILED_CLOSED",
            trigger="job:lot.finalize_fail",
            audit=self.audit,
            payload={"transition_id": "LS-10"},
        )

    async def close_offers(self, session: AsyncSession, *, lot_id: UUID) -> int:
        """Expire the offers that already ran out; a live offer keeps its own timer.

        A FAILING lot cannot create new offers because ``lot.open_checkout`` only
        runs from CHECKOUT_OPEN, so the only orders this may move are ones whose
        ``offer_expires_at`` has passed, and BO-15 is the contracted edge for those.
        """
        now = await self.clock.db_now(session)
        rows = await session.scalars(
            select(BuyerOrder).where(
                BuyerOrder.lot_id == lot_id,
                BuyerOrder.status == "OFFERED",
                BuyerOrder.offer_expires_at.is_not(None),
                BuyerOrder.offer_expires_at <= now,
            )
        )
        closed = 0
        for order in rows:
            try:
                await self.engine.apply(
                    session,
                    TransitionRequest(
                        buyer_order_id=order.id,
                        to_state="EXPIRED",
                        trigger="job:offer.expire",
                        actor="worker",
                    ),
                )
            except ApplicationError:
                # A rival handler already moved it; nothing left to close.
                continue
            closed += 1
        return closed

    # ---------------------------------------------------------------- void

    async def run_void(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """BO-12: void one authorization, then let the engine write AUTH_VOIDED."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.get(BuyerOrder, buyer_order_id)
        if order is None or str(order.status) != "AUTHORIZED":
            return
        auth = await self._latest_authorization(session, buyer_order_id=buyer_order_id)
        if auth is None or auth.status == "VOIDED":
            return
        try:
            await self.gateway.void_authorization(auth.paypal_auth_id)
        except PaymentError as error:
            # Live money stays FAILING rather than closing on an unproven void.
            logger.warning(
                "void failed; lot stays failing",
                extra={
                    "buyer_order_id": str(buyer_order_id),
                    "error_class": error.category,
                    "error_code": error.code,
                },
            )
            return
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="VOIDED",
                trigger="job:void.run",
                observation=Observation(
                    kind="authorization",
                    status="VOIDED",
                    reference=auth.paypal_auth_id,
                    amount_cents=int(auth.amount_cents),
                    checks_passed=True,
                ),
                void_source=str(payload.get("void_source", "lot_failing")),
            ),
        )

    # -------------------------------------------------------------- refund

    async def run_refund(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """BO-13 then BO-14: refund one captured payment, polled until COMPLETED."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.get(BuyerOrder, buyer_order_id)
        if order is None:
            return
        state = str(order.status)
        if state == "CAPTURED":
            capture = await self._latest_capture(session, buyer_order_id=buyer_order_id)
            if capture is None:
                return
            try:
                refund = await self.gateway.refund_capture(
                    capture.paypal_capture_id,
                    amount_cents=int(capture.amount_cents),
                    request_key=f"refund:{capture.paypal_capture_id}:1",
                )
            except PaymentError as error:
                logger.warning(
                    "refund failed; lot stays failing",
                    extra={
                        "buyer_order_id": str(buyer_order_id),
                        "error_class": error.category,
                        "error_code": error.code,
                    },
                )
                return
            # Persisted before the next step: the refund exists at the provider now.
            session.add(
                PayPalRefundRow(
                    id=uuid4(),
                    buyer_order_id=buyer_order_id,
                    paypal_capture_id=capture.paypal_capture_id,
                    paypal_refund_id=refund.id,
                    seq=1,
                    status=refund.status,
                    amount_cents=int(refund.amount_cents),
                    raw={},
                )
            )
            await session.flush()
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=buyer_order_id,
                    to_state="REFUNDING",
                    trigger="job:refund.run",
                    refund_seq=1,
                    # BO-13 allows an ops refund without the lot failing.
                    ops_refund=bool(payload.get("ops_refund")),
                    observation=Observation(
                        kind="refund",
                        status=refund.status,
                        reference=refund.id,
                        amount_cents=int(refund.amount_cents),
                        checks_passed=refund.status == "COMPLETED",
                    ),
                ),
            )
            state = "REFUNDING"
        if state != "REFUNDING":
            return
        row = await self._latest_refund(session, buyer_order_id=buyer_order_id)
        if row is None:
            return
        try:
            refund = await self.gateway.get_refund(row.paypal_refund_id)
        except PaymentError as error:
            logger.warning(
                "refund read failed; lot stays failing",
                extra={
                    "buyer_order_id": str(buyer_order_id),
                    "error_class": error.category,
                    "error_code": error.code,
                },
            )
            return
        if refund.status != "COMPLETED":
            now = await self.clock.db_now(session)
            await self.jobs.enqueue(
                session,
                "refund.run",
                {"buyer_order_id": str(buyer_order_id)},
                run_at=now + timedelta(seconds=PENDING_RECHECK_S),
                concurrency_key=f"bo:{buyer_order_id}",
                dedupe_key=f"refund:{buyer_order_id}:{row.seq}",
            )
            return
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="REFUNDED",
                trigger="job:refund.run",
                observation=Observation(
                    kind="refund",
                    status=refund.status,
                    reference=refund.id,
                    amount_cents=int(refund.amount_cents),
                    checks_passed=True,
                ),
                refund_seq=int(row.seq),
            ),
        )

    # ------------------------------------------------------------ net zero

    async def net_zero(self, session: AsyncSession, *, lot_id: UUID) -> bool:
        """The four conditions LS-10 requires, none of them inferred."""
        net = await self.ledger.net_paid_cents(session, lot_id)
        if net != 0:
            return False
        live_auth = await session.scalar(
            select(BuyerOrder.id)
            .where(BuyerOrder.lot_id == lot_id, BuyerOrder.status.in_(sorted(VOIDABLE_STATES)))
            .limit(1)
        )
        if live_auth is not None:
            return False
        pending_capture = await session.scalar(
            select(PayPalCapture.id)
            .join(BuyerOrder, BuyerOrder.id == PayPalCapture.buyer_order_id)
            .where(BuyerOrder.lot_id == lot_id, PayPalCapture.status == "PENDING")
            .limit(1)
        )
        return pending_capture is None

    # -------------------------------------------------------------- helpers

    async def _settle_orders(self, session: AsyncSession, *, lot_id: UUID) -> int:
        """Enqueue a void or refund per order; return how many captures are pending."""
        rows = await session.scalars(
            select(BuyerOrder).where(BuyerOrder.lot_id == lot_id).order_by(BuyerOrder.created_at)
        )
        pending = 0
        for order in rows:
            state = str(order.status)
            payload = {"buyer_order_id": str(order.id), "void_source": "lot_failing"}
            if state in VOIDABLE_STATES:
                await self.jobs.enqueue(
                    session,
                    "void.run",
                    payload,
                    concurrency_key=f"bo:{order.id}",
                    dedupe_key=f"void:{order.id}",
                )
            elif state in REFUNDABLE_STATES:
                await self.jobs.enqueue(
                    session,
                    "refund.run",
                    payload,
                    concurrency_key=f"bo:{order.id}",
                    dedupe_key=f"refund:{order.id}",
                )
            elif state in PENDING_STATES:
                pending += 1
        return pending

    async def _latest_authorization(
        self, session: AsyncSession, *, buyer_order_id: UUID
    ) -> PayPalAuthorization | None:
        return await session.scalar(
            select(PayPalAuthorization)
            .where(PayPalAuthorization.buyer_order_id == buyer_order_id)
            .order_by(PayPalAuthorization.created_at.desc())
            .limit(1)
        )

    async def _latest_capture(
        self, session: AsyncSession, *, buyer_order_id: UUID
    ) -> PayPalCapture | None:
        return await session.scalar(
            select(PayPalCapture)
            .where(PayPalCapture.buyer_order_id == buyer_order_id)
            .order_by(PayPalCapture.created_at.desc())
            .limit(1)
        )

    async def _latest_refund(
        self, session: AsyncSession, *, buyer_order_id: UUID
    ) -> PayPalRefundRow | None:
        return await session.scalar(
            select(PayPalRefundRow)
            .where(PayPalRefundRow.buyer_order_id == buyer_order_id)
            .order_by(PayPalRefundRow.created_at.desc())
            .limit(1)
        )
