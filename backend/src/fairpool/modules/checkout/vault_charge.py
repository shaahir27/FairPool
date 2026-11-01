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

An order that stays CAPTURING is not abandoned: :meth:`VaultChargeHandler.reconcile`
is what ``order.resolve`` runs for it. It reads the provider resource back by the
stored order id (or replays the logical charge under the same key when the provider
never returned an id) and applies the outcome with that same identity, so an unknown
outcome is settled by evidence and never by a second charge (vault-charge.md
section 7).

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
from fairpool.db.models.pools import Lot
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

    async def get_order(self, paypal_order_id: str) -> Any: ...


class VaultRouter(Protocol):
    """The router as the vault path sees it: payee selection plus the gateway."""

    name: str
    gateway: ChargeGateway

    def payee_for(self, award: AwardView, payee_ref: PayeeRef) -> Payee: ...


def _slot_key(index: int) -> int:
    digest = hashlib.sha256(f"{SLOT_NAMESPACE}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") - _INT64_SPAN


class VaultChargeHandler:
    """The ``order.vault_charge`` job handler and its ``order.resolve`` step."""

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
            # A retry after the charge resolved (or a seat already moved) is silent;
            # a CAPTURING row belongs to ``reconcile``, not to a second charge.
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
        payee = await self._payee(session, order)
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
            await self._settle_error(session, buyer_order_id=buyer_order_id, exc=exc)
            return
        await self._settle(session, order=order, result=result, payee=payee)

    async def reconcile(self, session: AsyncSession, buyer_order_id: UUID) -> None:
        """Settle one CAPTURING vault order from evidence, never from a new charge.

        ``order.resolve`` calls this for an order whose provider outcome is unknown
        (vault-charge.md section 7): a 5xx, a timeout or an unrecognised status. The
        provider resource is read back by the order id persisted when the provider
        answered; when it never answered, the charge is replayed under the same
        logical key ``vc:{buyer_order_id}``, so the provider sees one operation and a
        replay returns the original (never a second charge, I9).
        """
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:
            raise ApplicationError("NOT_FOUND")
        if str(order.status) != str(BuyerOrderStatus.CAPTURING):
            return
        mode = await session.scalar(select(Lot.payment_mode).where(Lot.id == order.lot_id))
        if mode is None or str(mode) != checkout_guards.MODE_VAULT:
            # The authorize ladder's CAPTURING rows belong to ``order.capture``.
            return
        payee = await self._payee(session, order)
        total_cents = int(order.total_cents)
        record = await session.scalar(
            select(PayPalOrder).where(
                PayPalOrder.buyer_order_id == order.id,
                PayPalOrder.attempt == int(order.current_attempt),
            )
        )
        try:
            if record is not None:
                result = await self._read_back(record.paypal_order_id)
            else:
                token_id = await self._token_id(session, order.entry_id)
                result = await self.router.gateway.charge_vault(
                    str(order.id), token_id, total_cents, payee
                )
        except PaymentError as exc:
            await self._settle_error(session, buyer_order_id=order.id, exc=exc)
            return
        except ApplicationError:
            # No stored permission and no provider id: there is no identity left to
            # read back, so the row stays CAPTURING and the alert names the order.
            logger.error("checkout.vault_charge.reconcile_unavailable buyer_order_id=%s", order.id)
            return
        await self._settle(session, order=order, result=result, payee=payee)

    # ------------------------------------------------------------- settlement

    async def _settle(
        self, session: AsyncSession, *, order: BuyerOrder, result: ChargeResult, payee: Payee
    ) -> None:
        """Persist what the provider said, then apply the one transition it proves."""
        total_cents = int(order.total_cents)
        # The provider order id is persisted on every answered call, so a later
        # reconcile can read the resource back instead of guessing (B2, section 7).
        await self._record_charge(session, order.id, result, total_cents)
        if result.error is not None:
            if result.error in checkout_guards.VAULT_DECLINE_CODES:
                await self._mark_token_deleted(session, order.entry_id)
                observation = self._charge_observation(result.order_id, error_code=result.error)
                await self._to_capture_failed(session, order.id, observation)
            else:
                # Conditional or unknown error: CAPTURING, reconciled by GET.
                logger.error(
                    "checkout.vault_charge.error buyer_order_id=%s code=%s",
                    order.id,
                    result.error,
                )
            return

        status = result.capture_status
        if status in (checkout_guards.CAPTURE_COMPLETED, checkout_guards.CAPTURE_PENDING):
            # COMPLETED is the only paid status; PENDING waits for ``capture.poll``.
            await self.engine.apply(
                session,
                TransitionRequest(
                    buyer_order_id=order.id,
                    to_state=(
                        "CAPTURED"
                        if status == checkout_guards.CAPTURE_COMPLETED
                        else "CAPTURE_PENDING"
                    ),
                    trigger="job:order.vault_charge",
                    observation=self._capture_observation(result, payee=payee, status=status),
                ),
            )
            return
        if status in {"DECLINED", "DENIED", "FAILED"}:
            # ``INSTRUMENT_DECLINED`` is the contracted name for a declined charge
            # (vault-charge.md section 7), whether the adapter raises it or returns it.
            await self._mark_token_deleted(session, order.entry_id)
            observation = self._charge_observation(
                result.capture_id or result.order_id, error_code="INSTRUMENT_DECLINED"
            )
            await self._to_capture_failed(session, order.id, observation)
            return
        logger.error(
            "checkout.vault_charge.unknown_status buyer_order_id=%s status=%s",
            order.id,
            status,
        )

    async def _settle_error(
        self, session: AsyncSession, *, buyer_order_id: UUID, exc: PaymentError
    ) -> None:
        """A raised adapter error: definitive 403 rows free the seat, the rest wait."""
        order = await session.scalar(select(BuyerOrder).where(BuyerOrder.id == buyer_order_id))
        if order is None:  # pragma: no cover - caller read it
            raise ApplicationError("INTEGRITY_ERROR")
        if exc.code in checkout_guards.VAULT_DECLINE_CODES:
            await self._mark_token_deleted(session, order.entry_id)
            # No provider resource exists, so the evidence carries the charge's own
            # logical key and the adapter's definitive code; BO-26 applies and the
            # seat gets its vacancy and refill (B3, vault-charge.md section 7).
            observation = self._charge_observation(f"vc:{buyer_order_id}", error_code=exc.code)
            await self._to_capture_failed(session, buyer_order_id, observation)
            return
        # Unknown: stay CAPTURING and reconcile by GET with the same identity.
        logger.error(
            "checkout.vault_charge.unknown buyer_order_id=%s category=%s code=%s",
            buyer_order_id,
            exc.category,
            exc.code,
        )

    async def _to_capture_failed(
        self, session: AsyncSession, buyer_order_id: UUID, observation: Observation
    ) -> None:
        """BO-26 for this seat: audit, vacancy and ``lot.refill`` (no ledger fact)."""
        await self.engine.apply(
            session,
            TransitionRequest(
                buyer_order_id=buyer_order_id,
                to_state="CAPTURE_FAILED",
                trigger="job:order.vault_charge",
                observation=observation,
            ),
        )

    def _capture_observation(
        self, result: ChargeResult, *, payee: Payee, status: str
    ) -> Observation:
        """BO-24's evidence: the provider's captured amount and payee, not ours (I3)."""
        return Observation(
            "capture",
            status,
            result.capture_id or result.order_id,
            amount_cents=result.amount_cents,
            payee_matches=self._payee_matches(result.payee_email, payee),
        )

    def _charge_observation(self, reference: str, *, error_code: str) -> Observation:
        """BO-26's evidence: the definitive code, and the identity that carried it."""
        return Observation("charge", "DENIED", reference, error_code=error_code)

    @staticmethod
    def _payee_matches(observed: str | None, payee: Payee) -> bool:
        """The captured payee against the stamped router's seller (BO-24, V2)."""
        return (
            observed is not None
            and payee.email is not None
            and observed.lower() == payee.email.lower()
        )

    async def _read_back(self, paypal_order_id: str) -> ChargeResult:
        """GET the stored provider order and read its capture resource (section 7)."""
        order = await self.router.gateway.get_order(paypal_order_id)
        captures = getattr(order, "captures", None) or []
        if not captures:
            # The provider holds no capture yet: an unknown outcome, still CAPTURING.
            return ChargeResult(paypal_order_id, None, None, None)
        capture = captures[-1]
        return ChargeResult(
            paypal_order_id,
            capture.id,
            str(capture.status),
            None,
            int(capture.amount_cents),
            getattr(order, "payee_email", None),
        )

    async def _payee(self, session: AsyncSession, order: BuyerOrder) -> Payee:
        award = await self.allocations.get_award(session, order.lot_id)
        payee_ref = await self.directory.get_payee(session, award.merchant_id)
        return self.router.payee_for(award, payee_ref)

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

    async def _record_charge(
        self,
        session: AsyncSession,
        buyer_order_id: UUID,
        result: ChargeResult,
        total_cents: int,
    ) -> None:
        """Persist the provider order and capture rows this answer carried (I4, I9)."""
        status = result.capture_status or ("DENIED" if result.error is not None else "UNKNOWN")
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
                        amount_cents=int(result.amount_cents or total_cents),
                        final_capture=True,
                        raw={},
                    )
                )
            else:
                existing.status = status
                if result.amount_cents is not None:
                    existing.amount_cents = int(result.amount_cents)
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
                    amount_cents=int(result.amount_cents or total_cents),
                    payee_email=result.payee_email,
                    raw={},
                )
            )
        else:
            known.status = status
        await session.flush()


__all__ = ["SLOT_NAMESPACE", "SLOT_RETRY_S", "VaultChargeHandler"]
