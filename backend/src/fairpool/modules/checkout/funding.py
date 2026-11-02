"""Funding, capture, polling and close (T04A03; LS-06, LS-07, LS-11, BO-06..BO-11).

Every decision here is a whitelisted lot transition or buyer-order transition; no
method writes a status directly (I10). The three rules the contract makes
non-negotiable:

* **Only completed money funds.** ``authorize_capture`` counts authorizations for
  the trigger, but the lot reaches FUNDED only from the ledger's completed
  captures from distinct buyers (I5). ``vault_charge`` has no authorization at all
  and uses that same ledger count for both LS-06 and LS-07 (CR-4).
* **A capture is never inferred.** A PENDING capture is recorded as
  ``CAPTURE_PENDING`` with its ledger fact and polled; only a POST result or a GET
  that reads ``COMPLETED`` becomes ``CAPTURED`` (P3, I4). An unknown outcome leaves
  the order where it was and the reconciler owns it.
* **A money-moving call is persisted before the next step.** The capture row and
  its ledger fact are written in this handler's transaction, then the next job is
  enqueued (AGENTS.md section 4).

``apply_lot_transition`` is shared with ``lot.open_checkout`` and the admin
force-award route so the three callers cannot drift apart in how a lot status
changes. ``lock_lot``, ``try_slot`` and ``retry_in`` are the same kind of shared
plumbing: the lock order, the concurrency-slot test and the "come back shortly"
enqueue.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Merchant
from fairpool.db.models.checkout import BuyerOrder, PayPalAuthorization, PayPalCapture
from fairpool.db.models.enums import BuyerOrderStatus, LotStatus
from fairpool.db.models.pools import Lot
from fairpool.domain import checkout_guards
from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import PaymentError
from fairpool.domain.payments import PayPalCapture as GatewayCapture
from fairpool.domain.states import assert_transition
from fairpool.modules.checkout.engine import (
    CheckoutEngine,
    TransitionRequest,
    lot_advisory_lock_key,
)
from fairpool.ports import (
    AllocationReadService,
    AuditLog,
    AwardView,
    Clock,
    JobQueue,
    Ledger,
    Notifier,
)

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.funding")

#: Buyer-order states that prove an authorization was once created. Once a capture
#: starts the order leaves AUTHORIZED, and a funding count that dropped then would
#: make a funded lot look unfunded.
AUTHORIZED_STATES: Final[tuple[str, ...]] = (
    "AUTHORIZED",
    "CAPTURING",
    "CAPTURE_PENDING",
    "CAPTURED",
)

#: At most ``CAPTURE_CONCURRENCY`` capture calls in flight per worker; the slot
#: keys are stable so two workers contend for the same pool of slots.
CAPTURE_SLOT_NAMESPACE: Final[str] = "fairpool/capture-slot/v1"

#: How soon a capture job retries when no slot was free (never a blocking wait).
CAPTURE_SLOT_RETRY_S: Final[int] = 5

#: ``capture.poll`` cadence while a capture is PENDING (bounded by pending_wait_s).
POLL_INTERVAL_S: Final[int] = 5

_INT64_SPAN: Final[int] = 1 << 63


def _slot_key(namespace: str, index: int) -> int:
    digest = hashlib.sha256(f"{namespace}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") - _INT64_SPAN


async def apply_lot_transition(
    session: AsyncSession,
    *,
    lot: Lot,
    to_status: str,
    trigger: str,
    audit: AuditLog,
    actor: str = "worker",
    payload: dict[str, Any] | None = None,
) -> None:
    """Move a lot along the whitelist and write its audit row in this transaction."""
    assert_transition("lot", str(lot.status), to_status, trigger=trigger)
    before = str(lot.status)
    lot.status = LotStatus(to_status)
    await session.flush()
    await audit.append(
        session,
        actor=actor,
        action=f"lot.{to_status.lower()}",
        subject_type="lot",
        subject_id=str(lot.id),
        payload={
            "pool_id": str(lot.pool_id),
            "from": before,
            "to": to_status,
            "trigger": trigger,
            **(payload or {}),
        },
    )


class CaptureGateway(Protocol):
    """The two PayPal calls this module owns (``paypal-adapter.md`` section 2)."""

    async def capture_authorization(
        self, auth_id: str, *, amount_cents: int, request_key: str
    ) -> GatewayCapture: ...

    async def get_capture(self, capture_id: str) -> GatewayCapture: ...


async def lock_lot(session: AsyncSession, lot_id: UUID) -> Lot:
    """The per-lot advisory lock, then the lot row: the order every lot handler uses."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lot_advisory_lock_key(lot_id)}
    )
    lot = await session.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
    if lot is None:
        raise ApplicationError("NOT_FOUND")
    return lot


async def try_slot(session: AsyncSession, namespace: str, permits: int) -> bool:
    """True when one of ``permits`` advisory-lock slots was free; never blocks."""
    for index in range(permits):
        if await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _slot_key(namespace, index)}
        ):
            return True
    return False


async def retry_in(
    session: AsyncSession,
    jobs: JobQueue,
    clock: Clock,
    *,
    kind: str,
    buyer_order_id: UUID,
    delay_s: int,
) -> None:
    """Re-enqueue the same buyer-order job shortly instead of blocking a worker."""
    now = await clock.db_now(session)
    await jobs.enqueue(
        session,
        kind,
        {"buyer_order_id": str(buyer_order_id)},
        run_at=now + timedelta(seconds=delay_s),
        concurrency_key=f"bo:{buyer_order_id}",
    )


class FundingService:
    """``lot.try_fund``, ``order.capture``, ``capture.poll`` and ``lot.finalize_close``."""

    def __init__(
        self,
        *,
        engine: CheckoutEngine,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        notifier: Notifier,
        ledger: Ledger,
        allocations: AllocationReadService,
        gateway: CaptureGateway,
        capture_concurrency: int,
        capture_buffer: int,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.notifier = notifier
        self.ledger = ledger
        self.allocations = allocations
        self.gateway = gateway
        self.capture_concurrency = max(1, capture_concurrency)
        self.capture_buffer = max(0, capture_buffer)

    # ------------------------------------------------------------- try_fund

    async def try_fund(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Evaluate LS-06 then LS-07 for one lot; a no-op when neither guard holds."""
        lot_id = UUID(str(payload["lot_id"]))
        lot = await lock_lot(session, lot_id)
        if str(lot.status) not in ("CHECKOUT_OPEN", "FUNDING"):
            # A late capture arrives after the lot already failed: nothing to decide.
            return
        view = await self.allocations.get_lot(session, lot_id)
        try:
            award = await self.allocations.get_award(session, lot_id)
        except ApplicationError:
            return
        wall_now = await self.clock.db_wall_now(session)
        moq = int(award.moq)
        mode = None if view.payment_mode is None else str(view.payment_mode)

        entered_funding = False
        if str(lot.status) == str(LotStatus.CHECKOUT_OPEN):
            if mode == "vault_charge":
                # CR-4: there is no authorization in this mode, so the only count
                # that can fund it is completed captures from distinct buyers.
                completed = await self.ledger.completed_capture_count(session, lot.id)
                if completed >= moq:
                    await self._to_funding(session, lot, completed=completed)
                    entered_funding = True
            else:
                authorized = await self._authorized_count(session, lot.id)
                threshold = min(int(lot.seats), moq + self.capture_buffer)
                deadline_passed = lot.fund_deadline_at is not None and (
                    wall_now >= lot.fund_deadline_at
                )
                if authorized >= threshold or (deadline_passed and authorized >= moq):
                    await self._to_funding(session, lot, authorized=authorized)
                    entered_funding = True

        if str(lot.status) != str(LotStatus.FUNDING):
            # LS-08/LS-09: once the deadline passes short of the minimum the lot
            # fails. A pending capture blocks it (F9): the late capture is refunded
            # by the next pass instead of closing a lot over unsettled money.
            await self._fail_if_deadline_passed(
                session, lot=lot, moq=moq, mode=mode, wall_now=wall_now
            )
            return

        if mode != "vault_charge":
            await self._enqueue_captures(session, lot.id)

        completed = await self.ledger.completed_capture_count(session, lot.id)
        if completed < moq:
            # A lot that entered FUNDING in this same pass gets its captures queued
            # first; the next pass decides whether they arrived in time.
            if not entered_funding:
                await self._fail_if_deadline_passed(
                    session, lot=lot, moq=moq, mode=mode, wall_now=wall_now
                )
            return
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="FUNDED",
            trigger="job:lot.try_fund",
            audit=self.audit,
            payload={"transition_id": "LS-07", "completed_captures": completed, "moq": moq},
        )
        # ``now()`` is fixed at transaction start, so one read serves both the row
        # timestamp and the close horizon below.
        now = await self.clock.db_now(session)
        lot.funded_at = now
        await session.flush()
        await self._notify_merchant(session, award, kind="lot.funded", lot_id=lot.id)
        run_at = (
            lot.fund_deadline_at if lot.fund_deadline_at and lot.fund_deadline_at > now else now
        )
        await self.jobs.enqueue(
            session,
            "lot.finalize_close",
            {"lot_id": str(lot.id)},
            run_at=run_at,
            concurrency_key=f"lot:{lot.id}",
        )

    async def _fail_if_deadline_passed(
        self,
        session: AsyncSession,
        *,
        lot: Lot,
        moq: int,
        mode: str | None,
        wall_now: Any,
    ) -> None:
        """Apply LS-08 or LS-09 and hand the lot to ``lot.finalize_fail``."""
        if lot.fund_deadline_at is None or wall_now < lot.fund_deadline_at:
            return
        if await self._has_pending_capture(session, lot.id):
            return
        if mode == "vault_charge" or str(lot.status) != str(LotStatus.CHECKOUT_OPEN):
            short = (await self.ledger.completed_capture_count(session, lot.id)) < moq
        else:
            short = (await self._authorized_count(session, lot.id)) < moq
        if not short:
            return
        transition_id = "LS-09" if str(lot.status) == str(LotStatus.FUNDING) else "LS-08"
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="FAILING",
            trigger="job:lot.try_fund",
            audit=self.audit,
            payload={"transition_id": transition_id, "moq": moq},
        )
        await self.jobs.enqueue(
            session,
            "lot.finalize_fail",
            {"lot_id": str(lot.id)},
            concurrency_key=f"lot:{lot.id}",
            dedupe_key=f"finalize_fail:{lot.id}",
        )

    async def _has_pending_capture(self, session: AsyncSession, lot_id: UUID) -> bool:
        found = await session.scalar(
            select(PayPalCapture.id)
            .join(BuyerOrder, BuyerOrder.id == PayPalCapture.buyer_order_id)
            .where(BuyerOrder.lot_id == lot_id, PayPalCapture.status == "PENDING")
            .limit(1)
        )
        return found is not None

    async def _to_funding(self, session: AsyncSession, lot: Lot, **counts: int) -> None:
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="FUNDING",
            trigger="job:lot.try_fund",
            audit=self.audit,
            payload={"transition_id": "LS-06", **counts},
        )

    async def _authorized_count(self, session: AsyncSession, lot_id: UUID) -> int:
        statuses = [BuyerOrderStatus(state) for state in AUTHORIZED_STATES]
        value = await session.scalar(
            select(func.count())
            .select_from(BuyerOrder)
            .where(BuyerOrder.lot_id == lot_id, BuyerOrder.status.in_(statuses))
        )
        return int(value or 0)

    async def _enqueue_captures(self, session: AsyncSession, lot_id: UUID) -> None:
        """LS-06's ``job:order.capture`` effect for every authorized seat."""
        orders = (
            (
                await session.execute(
                    select(BuyerOrder.id)
                    .where(
                        BuyerOrder.lot_id == lot_id,
                        BuyerOrder.status == BuyerOrderStatus.AUTHORIZED,
                    )
                    .order_by(BuyerOrder.id)
                )
            )
            .scalars()
            .all()
        )
        now = await self.clock.db_now(session)
        for order_id in orders:
            await self.jobs.enqueue(
                session,
                "order.capture",
                {"buyer_order_id": str(order_id)},
                run_at=now,
                concurrency_key=f"bo:{order_id}",
            )

    # --------------------------------------------------------------- capture

    async def capture(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """BO-06 then BO-07, BO-08 or BO-11 for one authorized seat."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.AUTHORIZED):
            # A retry after the capture resolved has nothing to do (I15).
            return
        if not await try_slot(session, CAPTURE_SLOT_NAMESPACE, self.capture_concurrency):
            await retry_in(
                session,
                self.jobs,
                self.clock,
                kind="order.capture",
                buyer_order_id=buyer_order_id,
                delay_s=CAPTURE_SLOT_RETRY_S,
            )
            return
        decision = await self.engine.decide(
            session,
            buyer_order_id=buyer_order_id,
            to_state="CAPTURING",
            trigger="job:order.capture",
        )
        if decision.illegal_pair or decision.reason is not None:
            return
        auth_id = await session.scalar(
            select(PayPalAuthorization.paypal_auth_id)
            .where(PayPalAuthorization.buyer_order_id == buyer_order_id)
            .order_by(PayPalAuthorization.created_at.desc(), PayPalAuthorization.id)
            .limit(1)
        )
        if auth_id is None:
            raise ApplicationError("INTEGRITY_ERROR")
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="CAPTURING",
                trigger="job:order.capture",
            ),
        )
        try:
            capture = await self.gateway.capture_authorization(
                str(auth_id),
                amount_cents=int(order.total_cents),
                request_key=f"cap:{auth_id}",
            )
        except PaymentError as exc:
            # No capture resource exists to record, so no whitelisted pair applies;
            # the order stays CAPTURING and ``reconcile`` settles it under the same
            # request key once the reconciler sweeps it (I9, B2).
            logger.error(
                "checkout.capture.unknown buyer_order_id=%s category=%s code=%s",
                buyer_order_id,
                exc.category,
                exc.code,
            )
            return
        await self._settle_capture(
            session, buyer_order_id, capture, auth_id=str(auth_id), trigger="job:order.capture"
        )

    async def reconcile(self, session: AsyncSession, buyer_order_id: UUID) -> None:
        """Settle one CAPTURING authorize-mode order by replaying its capture key.

        ``order.resolve`` calls this for an order whose capture outcome is unknown:
        the capture is re-requested with ``cap:{paypal_auth_id}``, the key the first
        attempt used, so the provider replays rather than captures twice (I9), and the
        result is applied exactly as ``order.capture`` would apply it.
        """
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.CAPTURING):
            return
        mode = await session.scalar(select(Lot.payment_mode).where(Lot.id == order.lot_id))
        if mode is not None and str(mode) == "vault_charge":
            # The vault path's CAPTURING rows have their own reconciler step.
            return
        auth_id = await session.scalar(
            select(PayPalAuthorization.paypal_auth_id)
            .where(PayPalAuthorization.buyer_order_id == buyer_order_id)
            .order_by(PayPalAuthorization.created_at.desc(), PayPalAuthorization.id)
            .limit(1)
        )
        if auth_id is None:
            logger.error("checkout.capture.reconcile_unavailable buyer_order_id=%s", buyer_order_id)
            return
        try:
            capture = await self.gateway.capture_authorization(
                str(auth_id),
                amount_cents=int(order.total_cents),
                request_key=f"cap:{auth_id}",
            )
        except PaymentError as exc:
            logger.error(
                "checkout.capture.reconcile_unknown buyer_order_id=%s category=%s code=%s",
                buyer_order_id,
                exc.category,
                exc.code,
            )
            return
        await self._settle_capture(
            session, buyer_order_id, capture, auth_id=str(auth_id), trigger="job:order.capture"
        )

    async def _settle_capture(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        capture: GatewayCapture,
        *,
        auth_id: str | None,
        trigger: str,
    ) -> None:
        """Persist the capture row, then apply the one transition its status proves."""
        await self._record_capture(session, buyer_order_id, capture, auth_id=auth_id)
        status = str(capture.status)
        if status == "COMPLETED":
            await self._observe_capture(
                session, buyer_order_id, capture, to_state="CAPTURED", trigger=trigger
            )
        elif status == "PENDING":
            await self._observe_capture(
                session, buyer_order_id, capture, to_state="CAPTURE_PENDING", trigger=trigger
            )
        elif status in checkout_guards.CAPTURE_FAILURES:
            await self._observe_capture(
                session, buyer_order_id, capture, to_state="CAPTURE_FAILED", trigger=trigger
            )

    async def _observe_capture(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        capture: GatewayCapture,
        *,
        to_state: str,
        trigger: str,
        pending_wait_exceeded: bool = False,
    ) -> None:
        """Move the order on one captured resource, whose status the guard reads (I4)."""
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state=to_state,
                trigger=trigger,
                observation=checkout_guards.Observation(
                    "capture",
                    str(capture.status),
                    capture.id,
                    amount_cents=int(capture.amount_cents),
                ),
                pending_wait_exceeded=pending_wait_exceeded,
            ),
        )

    async def _record_capture(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        capture: GatewayCapture,
        *,
        auth_id: str | None,
    ) -> None:
        existing = await session.scalar(
            select(PayPalCapture).where(PayPalCapture.paypal_capture_id == capture.id)
        )
        if existing is None:
            session.add(
                PayPalCapture(
                    id=uuid4(),
                    buyer_order_id=buyer_order_id,
                    paypal_auth_id=auth_id,
                    paypal_capture_id=capture.id,
                    status=capture.status,
                    amount_cents=int(capture.amount_cents),
                    final_capture=bool(capture.final_capture),
                    raw={},
                )
            )
        else:
            existing.status = capture.status
            existing.amount_cents = int(capture.amount_cents)
        await session.flush()

    # ------------------------------------------------------------------ poll

    async def poll(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """BO-09 or BO-10 from a GET of the pending capture."""
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.CAPTURE_PENDING):
            return
        capture_id = await session.scalar(
            select(PayPalCapture.paypal_capture_id)
            .where(PayPalCapture.buyer_order_id == buyer_order_id)
            .order_by(PayPalCapture.created_at.desc(), PayPalCapture.paypal_capture_id)
            .limit(1)
        )
        if capture_id is None:
            raise ApplicationError("INTEGRITY_ERROR")
        capture = await self.gateway.get_capture(str(capture_id))
        status = str(capture.status)
        # The stored row follows every GET, whatever the outcome: a PENDING capture
        # that read DECLINED must not keep claiming to be pending (M6, I4).
        await self._record_capture(session, buyer_order_id, capture, auth_id=None)
        if status == "COMPLETED":
            await self._observe_capture(
                session, buyer_order_id, capture, to_state="CAPTURED", trigger="job:capture.poll"
            )
            return
        if status in checkout_guards.CAPTURE_FAILURES:
            await self._observe_capture(
                session,
                buyer_order_id,
                capture,
                to_state="CAPTURE_FAILED",
                trigger="job:capture.poll",
            )
            return
        view = await self.allocations.get_lot(session, order.lot_id)
        wall_now = await self.clock.db_wall_now(session)
        pending_wait_s = view.pending_wait_s if hasattr(view, "pending_wait_s") else 120
        if wall_now >= order.updated_at + timedelta(seconds=int(pending_wait_s)):
            # P3: a capture that never resolves is not paid, so the seat is freed.
            await self._observe_capture(
                session,
                buyer_order_id,
                capture,
                to_state="CAPTURE_FAILED",
                trigger="job:capture.poll",
                pending_wait_exceeded=True,
            )
            return
        now = await self.clock.db_now(session)
        await self.jobs.enqueue(
            session,
            "capture.poll",
            {"buyer_order_id": str(buyer_order_id)},
            run_at=now + timedelta(seconds=POLL_INTERVAL_S),
            concurrency_key=f"bo:{buyer_order_id}",
        )

    # --------------------------------------------------------- finalize_close

    async def finalize_close(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        lot_id = UUID(str(payload["lot_id"]))
        lot = await lock_lot(session, lot_id)
        if str(lot.status) != str(LotStatus.FUNDED):
            return
        if not await self._capture_window_over(session, lot.id):
            # LS-11: "capture window over; ledger balanced". A capture still PENDING at
            # the deadline, or a completed capture the ledger never recorded, means the
            # lot is not finished; the job comes back after the poll (I4, M5).
            now_wait = await self.clock.db_now(session)
            await self.jobs.enqueue(
                session,
                "lot.finalize_close",
                {"lot_id": str(lot.id)},
                run_at=now_wait + timedelta(seconds=POLL_INTERVAL_S),
                concurrency_key=f"lot:{lot.id}",
            )
            return
        award = await self.allocations.get_award(session, lot_id)
        # LS-11's guard text names the merchant notification, and its effect list
        # carries audit only; the notification is written before the transition so
        # a rollback cannot leave a merchant told about a close that did not happen.
        await self._notify_merchant(session, award, kind="lot.closed", lot_id=lot.id)
        await apply_lot_transition(
            session,
            lot=lot,
            to_status="CLOSED",
            trigger="job:lot.finalize_close",
            audit=self.audit,
            payload={"transition_id": "LS-11"},
        )

    async def _capture_window_over(self, session: AsyncSession, lot_id: UUID) -> bool:
        """True when no capture is PENDING and every completed one has its ledger fact."""
        pending = await session.scalar(
            select(func.count())
            .select_from(PayPalCapture)
            .join(BuyerOrder, BuyerOrder.id == PayPalCapture.buyer_order_id)
            .where(BuyerOrder.lot_id == lot_id, PayPalCapture.status == "PENDING")
        )
        if int(pending or 0) > 0:
            return False
        completed_rows = await session.scalar(
            select(func.count())
            .select_from(PayPalCapture)
            .join(BuyerOrder, BuyerOrder.id == PayPalCapture.buyer_order_id)
            .where(BuyerOrder.lot_id == lot_id, PayPalCapture.status == "COMPLETED")
        )
        on_ledger = await self.ledger.completed_capture_count(session, lot_id)
        return int(completed_rows or 0) == int(on_ledger)

    async def _notify_merchant(
        self, session: AsyncSession, award: AwardView, *, kind: str, lot_id: UUID
    ) -> None:
        user_id = await session.scalar(
            select(Merchant.user_id).where(Merchant.id == award.merchant_id)
        )
        if user_id is None:
            # An award without a merchant user cannot happen (foreign key), but a
            # notification is not worth failing a funding decision over.
            return
        await self.notifier.notify(
            session,
            user_id=user_id,
            kind=kind,
            payload={"lot_id": str(lot_id), "merchant_id": str(award.merchant_id)},
        )


__all__ = [
    "AUTHORIZED_STATES",
    "CAPTURE_SLOT_NAMESPACE",
    "CAPTURE_SLOT_RETRY_S",
    "FundingService",
    "apply_lot_transition",
    "lock_lot",
    "retry_in",
    "try_slot",
]
