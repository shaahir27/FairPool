"""``order.vault_charge``: precheck then one saved-permission charge (T04A02/T04A03).

Contract: ``state-machines.md`` BO-23 to BO-27, ``vault-charge.md`` sections 2, 3, 4
and 7, ``paypal-adapter.md`` section 4, rule 27.

The flow, in order:

1. **BO-27 precheck through the engine**, not a private copy of it: the token must
   be ACTIVE with its recorded consent, the total must be at or below the cap by
   integer compare, the lot must still be CHECKOUT_OPEN and the award still valid.
   A failed precheck applies BO-27 (REJECTED) with its audit and refill job; a seat
   that is not valid anymore has no legal move and the handler stays quiet.
2. **A concurrency slot.** At most ``VAULT_CHARGE_CONCURRENCY`` charges run at once,
   enforced with one advisory-lock slot per permit; when every slot is busy the job
   is re-enqueued shortly instead of blocking a worker.
3. **BO-23** (OFFERED to CAPTURING) and then ``charge_vault`` with the logical key
   ``vc:{buyer_order_id}``. Only the gateway composes the HTTP request ids.
4. **BO-24 / BO-25 / BO-26** from the capture result. ``COMPLETED`` is the only paid
   status; a definitive decline also marks the permission DELETED; an unknown
   outcome leaves the order CAPTURING with no new key (I4, I9).

The saved payment token is a credential: it is decrypted here, passed to the
gateway, and never written to a log record, audit payload, notification or return
value (rule 27).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.checkout import BuyerOrder, PayPalCapture, PayPalOrder
from fairpool.db.models.enums import BuyerOrderStatus, VaultStatus
from fairpool.db.models.identity import VaultToken
from fairpool.domain import checkout_guards
from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import ApplicationError
from fairpool.domain.payments import ChargeResult, Payee, PaymentError
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from fairpool.modules.checkout.funding import retry_in, try_slot
from fairpool.ports import (
    AllocationReadService,
    AwardView,
    Clock,
    JobQueue,
    MerchantDirectory,
    PayeeRef,
)

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.vault_charge")

#: Slot namespace for the ``VAULT_CHARGE_CONCURRENCY`` permits (never a lot key).
SLOT_NAMESPACE: Final[str] = "fairpool/vault-charge-slot/v1"

#: How soon a charge retries when every slot is busy.
SLOT_RETRY_S: Final[int] = 5

_INT64_SPAN: Final[int] = 1 << 63


class TokenCipher(Protocol):
    """The at-rest cipher the vault service sealed the token with (rule 27)."""

    def open(self, nonce: bytes, ciphertext: bytes) -> str: ...


class ChargeGateway(Protocol):
    async def charge_vault(
        self, buyer_order_id: str, payment_token_id: str, total_cents: int, payee: Payee
    ) -> ChargeResult: ...


class VaultRouter(Protocol):
    """The router as the vault path sees it: payee selection plus the gateway."""

    name: str
    gateway: ChargeGateway

    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee: ...


def _slot_key(index: int) -> int:
    digest = hashlib.sha256(f"{SLOT_NAMESPACE}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") - _INT64_SPAN


class VaultChargeHandler:
    """The ``order.vault_charge`` job handler."""

    def __init__(
        self,
        *,
        engine: CheckoutEngine,
        clock: Clock,
        jobs: JobQueue,
        allocations: AllocationReadService,
        directory: MerchantDirectory,
        router: VaultRouter,
        cipher: TokenCipher,
        concurrency: int,
    ) -> None:
        self.engine = engine
        self.clock = clock
        self.jobs = jobs
        self.allocations = allocations
        self.directory = directory
        self.router = router
        self.cipher = cipher
        self.concurrency = max(1, int(concurrency))

    async def charge(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        buyer_order_id = UUID(str(payload["buyer_order_id"]))
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.OFFERED):
            # A retry after the charge resolved (or a seat already moved) is silent.
            return

        decision = await self.engine.decide(
            session,
            buyer_order_id=buyer_order_id,
            to_state="CAPTURING",
            trigger="job:order.vault_charge",
        )
        if decision.illegal_pair:
            return
        if decision.reason is not None:
            await self._reject_if_precheck_failed(session, buyer_order_id)
            return

        if not await try_slot(session, SLOT_NAMESPACE, self.concurrency):
            await retry_in(
                session,
                self.jobs,
                self.clock,
                kind="order.vault_charge",
                buyer_order_id=buyer_order_id,
                delay_s=SLOT_RETRY_S,
            )
            return

        token_id = await self._token_id(session, order.entry_id)
        award = await self.allocations.get_award(session, order.lot_id)
        payee_ref = await self.directory.get_payee(session, award.merchant_id)
        payee = self.router.payee_for(award, payee_ref)

        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="CAPTURING",
                trigger="job:order.vault_charge",
            ),
        )
        total_cents = int(order.total_cents)

        try:
            result = await self.router.gateway.charge_vault(
                str(buyer_order_id), token_id, total_cents, payee
            )
        except PaymentError as exc:
            if exc.code in checkout_guards.VAULT_DECLINE_CODES or exc.code == "TOKEN_REVOKED":
                # vault-charge.md section 7: the permission is gone, so it is marked
                # DELETED. No provider resource exists, and BO-26 accepts only a
                # resource this buyer order owns as evidence (I4), so the seat cannot
                # move here without inventing an identity; the order stays CAPTURING
                # for the reconciler (recorded as a contract/code gap in the report).
                await self._mark_token_deleted(session, order.entry_id)
                logger.error(
                    "checkout.vault_charge.declined_without_resource buyer_order_id=%s code=%s",
                    buyer_order_id,
                    exc.code,
                )
                return
            # Unknown: stay CAPTURING and reconcile by GET with the same identity.
            logger.error(
                "checkout.vault_charge.unknown buyer_order_id=%s category=%s code=%s",
                buyer_order_id,
                exc.category,
                exc.code,
            )
            return

        if result.error is not None:
            if result.error in checkout_guards.VAULT_DECLINE_CODES:
                await self._mark_token_deleted(session, order.entry_id)
                # The created order is the owned charge identity BO-26 needs.
                await self._record_capture(session, buyer_order_id, result, "DENIED", total_cents)
                await self.engine.apply(
                    session,
                    TransitionRequest(
                        buyer_order_id=buyer_order_id,
                        to_state="CAPTURE_FAILED",
                        trigger="job:order.vault_charge",
                        observation=Observation(
                            "charge",
                            "DENIED",
                            result.order_id,
                            error_code=result.error,
                            payee_matches=True,
                        ),
                    ),
                )
            else:
                logger.error(
                    "checkout.vault_charge.error buyer_order_id=%s code=%s",
                    buyer_order_id,
                    result.error,
                )
            return

        status = result.capture_status
        if status in (checkout_guards.CAPTURE_COMPLETED, checkout_guards.CAPTURE_PENDING):
            # COMPLETED is the only paid status; PENDING waits for ``capture.poll``.
            await self._record_capture(session, buyer_order_id, result, status, total_cents)
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=buyer_order_id,
                    to_state=(
                        "CAPTURED"
                        if status == checkout_guards.CAPTURE_COMPLETED
                        else "CAPTURE_PENDING"
                    ),
                    trigger="job:order.vault_charge",
                    observation=Observation(
                        "capture",
                        status,
                        result.capture_id or result.order_id,
                        amount_cents=total_cents,
                        payee_matches=True,
                    ),
                ),
            )
            return
        if status in {"DECLINED", "DENIED", "FAILED"}:
            # ``INSTRUMENT_DECLINED`` is the contracted name for a declined charge
            # (vault-charge.md section 7), whether the adapter raises it or returns it.
            await self._mark_token_deleted(session, order.entry_id)
            await self._record_capture(session, buyer_order_id, result, "DECLINED", total_cents)
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=buyer_order_id,
                    to_state="CAPTURE_FAILED",
                    trigger="job:order.vault_charge",
                    observation=Observation(
                        "charge",
                        "DENIED",
                        result.capture_id or result.order_id,
                        error_code="INSTRUMENT_DECLINED",
                        payee_matches=True,
                    ),
                ),
            )
            return
        logger.error(
            "checkout.vault_charge.unknown_status buyer_order_id=%s status=%s",
            buyer_order_id,
            status,
        )

    async def _reject_if_precheck_failed(self, session: AsyncSession, buyer_order_id: UUID) -> None:
        reject = await self.engine.decide(
            session,
            buyer_order_id=buyer_order_id,
            to_state="REJECTED",
            trigger="job:order.vault_charge",
        )
        if reject.illegal_pair or reject.reason is not None:
            # BO-27 is not available either: a released seat or a moved state has
            # no legal move from here, and the handler never invents one.
            return
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="REJECTED",
                trigger="job:order.vault_charge",
            ),
        )

    async def _token_id(self, session: AsyncSession, entry_id: UUID) -> str:
        row = (
            await session.execute(
                select(VaultToken.token_ciphertext, VaultToken.token_nonce).where(
                    VaultToken.entry_id == entry_id, VaultToken.deleted_at.is_(None)
                )
            )
        ).first()
        if row is None or row.token_ciphertext is None or row.token_nonce is None:
            raise ApplicationError("INTEGRITY_ERROR")
        return self.cipher.open(row.token_nonce, row.token_ciphertext)

    async def _mark_token_deleted(self, session: AsyncSession, entry_id: UUID) -> None:
        token = await session.scalar(
            select(VaultToken).where(
                VaultToken.entry_id == entry_id, VaultToken.deleted_at.is_(None)
            )
        )
        if token is None:
            return
        now = await self.clock.db_now(session)
        token.status = VaultStatus.DELETED
        token.deleted_at = now
        # The credential is dead at the provider; do not keep its ciphertext.
        token.token_ciphertext = None
        token.token_nonce = None
        await session.flush()

    async def _record_capture(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        result: ChargeResult,
        status: str,
        total_cents: int,
    ) -> None:
        # No capture row is written for a decline with no capture id: the ``charge``
        # observation carries the charge identity (``EVIDENCE_OWNERS``).
        capture_id = result.capture_id
        if capture_id is not None:
            existing = await session.scalar(
                select(PayPalCapture).where(PayPalCapture.paypal_capture_id == capture_id)
            )
            if existing is None:
                session.add(
                    PayPalCapture(
                        id=uuid4(),
                        buyer_order_id=buyer_order_id,
                        paypal_auth_id=None,
                        paypal_capture_id=capture_id,
                        status=status,
                        amount_cents=int(total_cents),
                        final_capture=True,
                        raw={},
                    )
                )
            else:
                existing.status = status
        # Persist the provider order id too, so a reconciler GET can find it.
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:  # pragma: no cover - caller checked
            raise ApplicationError("INTEGRITY_ERROR")
        known = await session.scalar(
            select(PayPalOrder).where(PayPalOrder.paypal_order_id == result.order_id)
        )
        if known is None:
            session.add(
                PayPalOrder(
                    id=uuid4(),
                    buyer_order_id=buyer_order_id,
                    attempt=int(order.current_attempt),
                    paypal_order_id=result.order_id,
                    status=status,
                    intent="CAPTURE",
                    amount_cents=int(total_cents),
                    raw={},
                )
            )
        await session.flush()


__all__ = ["SLOT_NAMESPACE", "SLOT_RETRY_S", "VaultChargeHandler"]
