"""The buyer-order transition engine (T03A01; I10, I7, I9, I15).

One entry point, :meth:`CheckoutEngine.apply`, moves a ``buyer_orders`` row along
the whitelist in ``domain/states.py`` and applies that transition's effects inside
the caller's single transaction. What this file exists to enforce:

* Only the whitelist decides legality. Guard *text* is never parsed or executed:
  the contract's guards are data comparisons in ``domain/checkout_guards.py``,
  evaluated here on post-lock values (I10).
* Lock order is the per-lot advisory lock, then the lot row, then the buyer-order
  row (``SELECT ... FOR UPDATE``). State, stamped ``payment_router`` and
  ``payment_mode``, the deadline, the award and the amount are all read again after
  those locks, so a later configuration change cannot reinterpret an existing lot
  (N8) and a transaction that waited on a lock across its deadline cannot act on a
  stale timestamp (CR-3 note 1, I15).
* A ``paypal:`` field on a transition names the call its handler already made. This
  module holds no gateway and performs no network call, directly or indirectly, and
  reads no HTTP client (CR-3 note 4, I2, I7).
* Money-bearing facts come from a validated adapter result, a row that handler
  persisted, or an explicit test fixture -- never from a request body and never from
  PayPal's ``order.status``, which read COMPLETED after a void (V8, I4).
* ``IllegalTransition`` both raises and alerts: one structured ERROR record naming
  the machine, the pair, the attempted trigger and the correlation ids available,
  and the transaction fails (CR-3 note 5).

The engine never commits: the job runner or the request handler owns the
transaction (I10, ``domain-ports.md`` section 1).
"""

from __future__ import annotations

import hashlib
import logging
import re
from contextvars import Token
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool import logging as correlation
from fairpool.db.models.auction import Award
from fairpool.db.models.catalog import PoolEntry
from fairpool.db.models.checkout import (
    BuyerOrder,
    PayPalAuthorization,
    PayPalCapture,
    PayPalOrder,
    PayPalRefund,
)
from fairpool.db.models.enums import BuyerOrderStatus
from fairpool.db.models.identity import VaultToken
from fairpool.db.models.pools import Allocation, Lot
from fairpool.domain import checkout_guards
from fairpool.domain.checkout_guards import BuyerOrderFacts, Observation
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.hashing import canonical_json, sha256_hex
from fairpool.domain.states import TRANSITIONS_BY_ID, Transition, assert_transition
from fairpool.infra.metrics import get_counters
from fairpool.ports import (
    AuditLog,
    Clock,
    IdemConflict,
    IdemNew,
    IdempotencyStore,
    IdemReplay,
    JobQueue,
    Ledger,
    Notifier,
)

logger: Final[logging.Logger] = logging.getLogger("fairpool.checkout.engine")

MACHINE: Final[str] = "buyer_order"

#: Namespace for the per-lot advisory key, so a lot key cannot collide with the
#: audit or job-claim locks in ``infra/audit.py`` and ``infra/jobs.py``.
LOT_LOCK_NAMESPACE: Final[str] = "fairpool/lot-lock/v1"

#: ``ledger_source`` values (db-schema.md): which read produced the money fact.
LEDGER_SOURCES: Final[frozenset[str]] = frozenset({"api", "webhook", "reconciler"})

IDEMPOTENCY_SCOPE: Final[str] = "checkout.buyer_order"

#: Which stored resources each evidence kind must belong to. A reference is only
#: evidence for the buyer order that owns the row, so evidence taken from another
#: order or lot cannot move money here (I4, I9). A vault charge names both its
#: order and its capture (``ChargeResult``), so either identity proves it is ours.
EVIDENCE_OWNERS: Final[dict[str, tuple[tuple[Any, str], ...]]] = {
    "approval": ((PayPalOrder, "paypal_order_id"),),
    "charge": ((PayPalOrder, "paypal_order_id"), (PayPalCapture, "paypal_capture_id")),
    "authorization": ((PayPalAuthorization, "paypal_auth_id"),),
    "capture": ((PayPalCapture, "paypal_capture_id"),),
    "refund": ((PayPalRefund, "paypal_refund_id"),),
}

_INT64_SPAN: Final[int] = 1 << 63
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def lot_advisory_lock_key(lot_id: UUID) -> int:
    """A stable signed-bigint advisory key for one lot.

    ``pg_advisory_xact_lock`` takes a bigint and the key must be the same on every
    worker for the same lot, so it derives from the lot id alone (AGENTS.md
    section 4: a per-lot advisory lock before lot-level decisions).
    """
    digest = hashlib.sha256(f"{LOT_LOCK_NAMESPACE}:{lot_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") - _INT64_SPAN


@dataclass(frozen=True)
class TransitionRequest:
    """What the caller asks for, plus the facts only a handler can know.

    ``observation`` is a validated adapter result or an explicit test fixture.
    Amounts, deadlines, the stamped mode, the cap and the lot status are never taken
    from here: they are re-read from the database under the lock, which is what
    keeps a request body from carrying a money fact (I4, V8).
    """

    buyer_order_id: UUID
    to_state: str
    trigger: str | None = None
    observation: Observation | None = None
    actor: str = "worker"
    source: str = "api"
    attempt: int | None = None
    refund_seq: int | None = None
    void_source: str | None = None
    reject_reason: str | None = None
    ops_refund: bool = False
    pending_wait_exceeded: bool = False
    seat_locked_until: datetime | None = None


@dataclass(frozen=True)
class TransitionOutcome:
    """The recorded result of one transition, replayable for the same request."""

    machine: str
    transition_id: str
    buyer_order_id: UUID
    lot_id: UUID
    pool_id: UUID
    from_state: str
    to_state: str
    trigger: str | None
    idempotency_key: str
    effects: tuple[str, ...]
    applied: bool

    def as_response(self) -> dict[str, Any]:
        """The JSON-safe form stored against the idempotency key (api.md section 1)."""
        return {
            "machine": self.machine,
            "transition_id": self.transition_id,
            "buyer_order_id": str(self.buyer_order_id),
            "lot_id": str(self.lot_id),
            "pool_id": str(self.pool_id),
            "from_state": self.from_state,
            "to_state": self.to_state,
            "trigger": self.trigger,
            "idempotency_key": self.idempotency_key,
            "effects": list(self.effects),
        }

    @classmethod
    def from_response(cls, response: dict[str, Any]) -> TransitionOutcome:
        """Rebuild the original outcome for a replay, which applied nothing again."""
        return cls(
            machine=str(response["machine"]),
            transition_id=str(response["transition_id"]),
            buyer_order_id=UUID(str(response["buyer_order_id"])),
            lot_id=UUID(str(response["lot_id"])),
            pool_id=UUID(str(response["pool_id"])),
            from_state=str(response["from_state"]),
            to_state=str(response["to_state"]),
            trigger=str(response["trigger"]) if response.get("trigger") is not None else None,
            idempotency_key=str(response["idempotency_key"]),
            effects=tuple(str(effect) for effect in response["effects"]),
            applied=False,
        )


@dataclass(frozen=True)
class _Snapshot:
    """Post-lock reads for one buyer order: the only data a guard may see."""

    now: datetime
    written_at: datetime
    user_id: UUID
    cap_cents: int
    seat_valid: bool
    award_valid_until: datetime | None
    saved_permission_status: str | None
    auth_id: str | None
    capture_id: str | None
    has_completed_capture: bool
    paypal_order_id: str | None


def _request_key(order: BuyerOrder, request: TransitionRequest) -> str:
    """The replay key for this request, rebuildable from the request alone.

    The contract's section 3 texts key the *money* facts (see
    :func:`money_idempotency_key`); this key covers every transition, including the
    ones the contract lists without a ``key``, and carries the attempt so a re-quote
    is a new request rather than a replay (N9).
    """
    attempt = order.current_attempt if request.attempt is None else request.attempt
    return f"bo:{order.id}:{request.to_state}:{request.trigger or 'none'}:attempt={attempt}"


def _observation_document(observation: Observation | None) -> dict[str, Any] | None:
    if observation is None:
        return None
    return {
        "kind": observation.kind,
        "status": observation.status,
        "reference": observation.reference,
        "source": observation.source,
        "amount_cents": observation.amount_cents,
        "currency": observation.currency,
        "checks_passed": observation.checks_passed,
        "payee_matches": observation.payee_matches,
        "error_code": observation.error_code,
        "error_class": observation.error_class,
    }


def _request_hash(request: TransitionRequest) -> str:
    """Fingerprint the payload, so a reused key conflicts instead of reapplying."""
    document: dict[str, Any] = {
        "to_state": request.to_state,
        "trigger": request.trigger,
        "actor": request.actor,
        "source": request.source,
        "attempt": request.attempt,
        "refund_seq": request.refund_seq,
        "void_source": request.void_source,
        "reject_reason": request.reject_reason,
        "ops_refund": request.ops_refund,
        "pending_wait_exceeded": request.pending_wait_exceeded,
        "seat_locked_until": (
            request.seat_locked_until.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            if request.seat_locked_until is not None
            else None
        ),
        "observation": _observation_document(request.observation),
    }
    return sha256_hex(canonical_json(document))


def _render_key(template: str, values: dict[str, str]) -> str:
    """Substitute the section 3 placeholders, refusing to invent an identity (I9)."""
    used = set(_PLACEHOLDER.findall(template))
    rendered = template
    for name in used:
        rendered = rendered.replace("{" + name + "}", values.get(name, ""))
    if _PLACEHOLDER.search(rendered) or any(not values.get(name, "") for name in used):
        # A money key with no identity would let a second charge slip out under a
        # reused key, which is exactly what I9 forbids.
        raise ApplicationError("INTEGRITY_ERROR")
    return rendered


def money_idempotency_key(
    transition: Transition, *, order: BuyerOrder, snapshot: _Snapshot, request: TransitionRequest
) -> str:
    """The ``paypal-adapter.md`` section 3 key text for this transition.

    A void's key is for our own records only and is never sent to PayPal, because a
    void does not replay (S2, state-machines.md header). Transitions the contract
    lists without a ``key`` get an own-records key of one row per order and
    transition, which is never a money-call identity.
    """
    if transition.key is None:
        return f"state:{order.id}:{transition.id}"
    return _render_key(
        transition.key,
        {
            "buyer_order_id": str(order.id),
            "attempt": str(order.current_attempt if request.attempt is None else request.attempt),
            "paypal_auth_id": snapshot.auth_id or "",
            "paypal_capture_id": snapshot.capture_id or "",
            "seq": "" if request.refund_seq is None else str(request.refund_seq),
        },
    )


def alert_illegal_transition(
    *,
    machine: str,
    from_state: str,
    to_state: str,
    trigger: str | None,
    reason: str,
    pool_id: UUID | None = None,
    lot_id: UUID | None = None,
    buyer_order_id: UUID | None = None,
) -> None:
    """Write the one structured ERROR record CR-3 note 5 requires.

    Correlation ids travel in the ``fairpool.logging`` contextvars so the JSON line
    carries them. Only ids and the pair are written: no request body, no reference
    that could be a credential, no approval URL (I14).
    """
    tokens: list[tuple[Any, Token[str | None]]] = []
    for variable, value in (
        (correlation.pool_id, pool_id),
        (correlation.lot_id, lot_id),
        (correlation.buyer_order_id, buyer_order_id),
    ):
        if value is not None:
            tokens.append((variable, variable.set(str(value))))
    try:
        # FR-OP-02: one alert counter series per machine and trigger.
        get_counters().incr(
            "fairpool_transitions_rejected_total", entity=machine, trigger=trigger or "none"
        )
        logger.error(
            "checkout.illegal_transition machine=%s from_state=%s to_state=%s trigger=%s reason=%s",
            machine,
            from_state,
            to_state,
            trigger or "none",
            reason,
            extra={
                "machine": machine,
                "from_state": from_state,
                "to_state": to_state,
                "trigger": trigger,
                "reason": reason,
            },
        )
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


@dataclass(frozen=True)
class GuardDecision:
    """What the engine would do with a request, without doing it.

    ``illegal_pair`` is the whitelist's own refusal (CR-3 note 5: raise and alert);
    a ``reason`` with a listed pair is a guard the stored data does not satisfy, so
    the caller simply does not act. ``expiry.py`` uses this to keep a seat it must
    not release and to stay quiet on a timer that fired early, without re-reading
    the rows or re-implementing a guard of its own.
    """

    transition_id: str | None
    reason: str | None
    illegal_pair: bool
    lot_id: UUID
    pool_id: UUID
    from_state: str


class CheckoutEngine:
    """Apply whitelisted ``buyer_order`` transitions with their effects (I10).

    Money transitions are decided here from evidence the handler brings; the
    network call itself belongs to the handler that owns that operation
    (CR-3 note 4), so an unauthorized caller cannot trigger a payment by naming a
    transition.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        ledger: Ledger,
        notifier: Notifier,
        idempotency: IdempotencyStore,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.ledger = ledger
        self.notifier = notifier
        self.idempotency = idempotency

    async def _lock(self, session: AsyncSession, buyer_order_id: UUID) -> tuple[Lot, BuyerOrder]:
        """Take the lot advisory lock, the lot row, then the buyer-order row.

        The order of locks is fixed so two transitions on one lot can never
        interleave (AGENTS.md section 4, I8). Both row locks are ``FOR UPDATE``;
        reaching the return statement means this transaction holds all three.
        """
        lot_id = cast(
            UUID | None,
            await session.scalar(select(BuyerOrder.lot_id).where(BuyerOrder.id == buyer_order_id)),
        )
        if lot_id is None:
            raise ApplicationError("NOT_FOUND")
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": lot_advisory_lock_key(lot_id)}
        )
        lot = cast(
            Lot | None,
            await session.scalar(select(Lot).where(Lot.id == lot_id).with_for_update()),
        )
        if lot is None:
            raise ApplicationError("INTEGRITY_ERROR")
        order = cast(
            BuyerOrder | None,
            await session.scalar(
                select(BuyerOrder).where(BuyerOrder.id == buyer_order_id).with_for_update()
            ),
        )
        if order is None:
            raise ApplicationError("NOT_FOUND")
        return lot, order

    async def decide(
        self, session: AsyncSession, *, buyer_order_id: UUID, to_state: str, trigger: str
    ) -> GuardDecision:
        """Lock, re-read and report whether this transition may run -- and why not.

        Takes the same locks and reads the same post-lock values as ``apply``, so a
        caller that asks before acting cannot decide on stale data (CR-3 note 1,
        I15). Nothing is written here.
        """
        lot, order = await self._lock(session, buyer_order_id)
        from_state = str(order.status)
        request = TransitionRequest(
            buyer_order_id=buyer_order_id, to_state=to_state, trigger=trigger
        )
        try:
            transition = assert_transition(MACHINE, from_state, to_state, trigger=trigger)
        except IllegalTransition:
            return GuardDecision(
                None,
                "the pair is not in the whitelist (I10)",
                True,
                lot.id,
                lot.pool_id,
                from_state,
            )
        snapshot = await self._load_snapshot(session, order)
        facts = self._facts(lot, order, request, from_state, snapshot)
        return GuardDecision(
            transition.id,
            checkout_guards.unmet_guard_reason(transition.id, facts),
            False,
            lot.id,
            lot.pool_id,
            from_state,
        )

    async def recheck(
        self, session: AsyncSession, *, buyer_order_id: UUID, transition_id: str
    ) -> str | None:
        """Take the locks and re-evaluate one whitelisted guard on the stored data.

        A job that has already left the state a transition departs from still needs
        the *held seat* half of that guard before it calls the provider again: a retry
        of ``order.authorize`` must re-prove BO-03 (row lock, seat valid, lot
        CHECKOUT_OPEN) and not only replay its key (I7). Returns ``None`` when the
        named guard holds; nothing is written.
        """
        transition = TRANSITIONS_BY_ID.get(transition_id)
        if transition is None or transition.machine != MACHINE:
            raise ApplicationError("INTEGRITY_ERROR")
        lot, order = await self._lock(session, buyer_order_id)
        from_state = str(order.status)
        request = TransitionRequest(
            buyer_order_id=buyer_order_id,
            to_state=transition.to_state,
            trigger=transition.trigger,
        )
        snapshot = await self._load_snapshot(session, order)
        facts = self._facts(lot, order, request, from_state, snapshot)
        return checkout_guards.unmet_guard_reason(transition_id, facts)

    async def apply(self, session: AsyncSession, request: TransitionRequest) -> TransitionOutcome:
        """Move one buyer order to ``request.to_state`` inside the caller's transaction.

        Three outcomes are kept apart (I9): an exact replay of an already-applied
        transition returns the original outcome and duplicates no effect; a pair the
        whitelist does not list raises ``IllegalTransition`` and alerts; the same key
        with a different payload raises ``ApplicationError('IDEMPOTENCY_CONFLICT')``.
        """
        self._check_request(request)
        lot, order = await self._lock(session, request.buyer_order_id)

        from_state = str(order.status)
        if from_state == request.to_state:
            # The row already sits where the request wants to take it: either an
            # exact replay, a conflicting payload, or nothing recorded at all. The
            # whitelist never lists a self-pair, so a miss falls through to the
            # illegal-transition path below.
            replay = await self._replay_or_conflict(session, order, request)
            if replay is not None:
                return replay

        snapshot = await self._load_snapshot(session, order)
        transition = self._whitelist(lot, order, request, from_state)
        if request.observation is not None and not await self._evidence_is_ours(
            session, order, request.observation
        ):
            # Evidence naming a resource this buyer order does not own would move
            # money on another order's facts, so it is refused before any effect
            # runs and before the ledger gets a row (I4, I9).
            self._alert(
                lot,
                order,
                request,
                from_state,
                "the evidence references a resource this buyer order does not own",
            )
            raise IllegalTransition(MACHINE, from_state, request.to_state)
        facts = self._facts(lot, order, request, from_state, snapshot)
        reason = checkout_guards.unmet_guard_reason(transition.id, facts)
        if reason is not None:
            self._alert(lot, order, request, from_state, f"guard unmet: {reason}")
            raise IllegalTransition(MACHINE, from_state, request.to_state)

        replayed = await self._claim_key(session, order, request, lot, from_state)
        if replayed is not None:
            return replayed
        key = money_idempotency_key(transition, order=order, snapshot=snapshot, request=request)
        await self._write_state(session, order, request, transition, snapshot)
        await self._apply_effects(
            session,
            transition=transition,
            lot=lot,
            order=order,
            request=request,
            from_state=from_state,
            money_key=key,
            snapshot=snapshot,
            facts=facts,
        )
        outcome = TransitionOutcome(
            machine=MACHINE,
            transition_id=transition.id,
            buyer_order_id=order.id,
            lot_id=lot.id,
            pool_id=lot.pool_id,
            from_state=from_state,
            to_state=transition.to_state,
            trigger=request.trigger,
            idempotency_key=key,
            effects=tuple(transition.effects),
            applied=True,
        )
        await self.idempotency.complete(
            session, key=_request_key(order, request), response=outcome.as_response()
        )
        return outcome

    # -- request and replay handling -------------------------------------------

    def _check_request(self, request: TransitionRequest) -> None:
        if request.source not in LEDGER_SOURCES:
            raise ApplicationError("VALIDATION_ERROR")
        if request.observation is not None and request.observation.kind not in (
            checkout_guards.OBSERVATION_KINDS
        ):
            raise ApplicationError("VALIDATION_ERROR")

    async def _replay_or_conflict(
        self, session: AsyncSession, order: BuyerOrder, request: TransitionRequest
    ) -> TransitionOutcome | None:
        """Return the original outcome when this request was already applied."""
        stored = await self.idempotency.begin(
            session,
            key=_request_key(order, request),
            scope=IDEMPOTENCY_SCOPE,
            request_hash=_request_hash(request),
        )
        if isinstance(stored, IdemReplay):
            return TransitionOutcome.from_response(dict(stored.response))
        if isinstance(stored, IdemConflict):
            raise ApplicationError("IDEMPOTENCY_CONFLICT")
        return None

    async def _claim_key(
        self,
        session: AsyncSession,
        order: BuyerOrder,
        request: TransitionRequest,
        lot: Lot,
        from_state: str,
    ) -> TransitionOutcome | None:
        """Reserve the request key, refusing a payload that reuses it (I9).

        A completed response is returned instead of applying anything a second time.
        With the Postgres store a transaction that then fails discards the
        reservation; the in-memory fake keeps the shell, which no behaviour here
        depends on.
        """
        stored = await self.idempotency.begin(
            session,
            key=_request_key(order, request),
            scope=IDEMPOTENCY_SCOPE,
            request_hash=_request_hash(request),
        )
        if isinstance(stored, IdemReplay):
            return TransitionOutcome.from_response(dict(stored.response))
        if isinstance(stored, IdemConflict):
            self._alert(
                lot,
                order,
                request,
                from_state,
                "the same idempotency key arrived with a different payload (I9)",
            )
            raise ApplicationError("IDEMPOTENCY_CONFLICT")
        assert isinstance(stored, IdemNew)
        return None

    # -- whitelist, guards and post-lock reads ---------------------------------

    def _whitelist(
        self, lot: Lot, order: BuyerOrder, request: TransitionRequest, from_state: str
    ) -> Transition:
        """The whitelist is the only source of legality (I10)."""
        try:
            return assert_transition(MACHINE, from_state, request.to_state, trigger=request.trigger)
        except IllegalTransition:
            self._alert(lot, order, request, from_state, "the pair is not in the whitelist (I10)")
            raise

    def _alert(
        self,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        from_state: str,
        reason: str,
    ) -> None:
        alert_illegal_transition(
            machine=MACHINE,
            from_state=from_state,
            to_state=request.to_state,
            trigger=request.trigger,
            reason=reason,
            pool_id=lot.pool_id,
            lot_id=lot.id,
            buyer_order_id=order.id,
        )

    async def _evidence_is_ours(
        self, session: AsyncSession, order: BuyerOrder, observation: Observation
    ) -> bool:
        """True when the evidence reference is a resource row of this buyer order."""
        if observation.kind == "charge" and observation.reference == f"vc:{order.id}":
            # vault-charge.md section 2: ``vc:{buyer_order_id}`` is the charge's own
            # logical key, derived from this order's id and therefore an identity it
            # owns. A create-time 403 (the adapter's definitive PERMISSION_DENIED or
            # TOKEN_REVOKED) produces no provider resource, and BO-26 must still free
            # the seat rather than strand it (section 7).
            return True
        candidates = EVIDENCE_OWNERS.get(observation.kind)
        if not candidates:
            return False
        for model, column_name in candidates:
            column = getattr(model, column_name)
            found = await session.scalar(
                select(func.count())
                .select_from(model)
                .where(column == observation.reference, model.buyer_order_id == order.id)
            )
            if found:
                return True
        return False

    async def _load_snapshot(self, session: AsyncSession, order: BuyerOrder) -> _Snapshot:
        """Re-read every deciding value now that both row locks are held."""
        # CR-3 note 1: the deadline is decided on clock_timestamp(), read after the
        # lock; written_at keeps the stable transaction timestamp for the row.
        now = await self.clock.db_wall_now(session)
        written_at = await self.clock.db_now(session)
        entry = cast(
            tuple[UUID, int] | None,
            (
                await session.execute(
                    select(PoolEntry.user_id, PoolEntry.cap_cents).where(
                        PoolEntry.id == order.entry_id
                    )
                )
            ).first(),
        )
        if entry is None:
            raise ApplicationError("INTEGRITY_ERROR")
        user_id, cap_cents = entry
        seat_status = cast(
            str | None,
            await session.scalar(
                select(Allocation.status).where(
                    Allocation.lot_id == order.lot_id, Allocation.entry_id == order.entry_id
                )
            ),
        )
        award_valid_until = cast(
            datetime | None,
            await session.scalar(select(Award.valid_until).where(Award.lot_id == order.lot_id)),
        )
        permission = cast(
            tuple[str, str, str] | None,
            (
                await session.execute(
                    select(
                        VaultToken.status,
                        VaultToken.consent_version,
                        VaultToken.consent_text_sha256,
                    )
                    .where(VaultToken.entry_id == order.entry_id, VaultToken.deleted_at.is_(None))
                    .order_by(VaultToken.created_at.desc())
                    .limit(1)
                )
            ).first(),
        )
        # Rule 27: a permission without its recorded consent is not chargeable, so
        # it is reported as missing rather than ACTIVE.
        saved_permission_status = (
            str(permission[0]) if permission is not None and all(permission[1:]) else None
        )
        auth_id = cast(
            str | None,
            await session.scalar(
                select(PayPalAuthorization.paypal_auth_id)
                .where(PayPalAuthorization.buyer_order_id == order.id)
                .order_by(PayPalAuthorization.created_at.desc())
                .limit(1)
            ),
        )
        capture_id = cast(
            str | None,
            await session.scalar(
                select(PayPalCapture.paypal_capture_id)
                .where(PayPalCapture.buyer_order_id == order.id)
                .order_by(PayPalCapture.created_at.desc())
                .limit(1)
            ),
        )
        has_completed_capture = bool(
            await session.scalar(
                select(func.count())
                .select_from(PayPalCapture)
                .where(
                    PayPalCapture.buyer_order_id == order.id,
                    PayPalCapture.status == "COMPLETED",
                )
            )
        )
        # The order id is read for identity only: ``paypal_orders.status`` is never
        # consulted, because it reported COMPLETED after a void (V8).
        paypal_order_id = cast(
            str | None,
            await session.scalar(
                select(PayPalOrder.paypal_order_id)
                .where(PayPalOrder.buyer_order_id == order.id)
                .order_by(PayPalOrder.created_at.desc())
                .limit(1)
            ),
        )
        return _Snapshot(
            now=now,
            written_at=written_at,
            user_id=user_id,
            cap_cents=cap_cents,
            seat_valid=seat_status == "SEATED",
            award_valid_until=award_valid_until,
            saved_permission_status=saved_permission_status,
            auth_id=auth_id,
            capture_id=capture_id,
            has_completed_capture=has_completed_capture,
            paypal_order_id=paypal_order_id,
        )

    def _facts(
        self,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        from_state: str,
        snapshot: _Snapshot,
    ) -> BuyerOrderFacts:
        """The guard input: one stamped lot, one order, all read after the locks."""
        return BuyerOrderFacts(
            from_state=from_state,
            to_state=request.to_state,
            trigger=request.trigger,
            now=snapshot.now,
            offer_expires_at=order.offer_expires_at,
            award_valid_until=snapshot.award_valid_until,
            lot_status=str(lot.status),
            payment_mode=None if lot.payment_mode is None else str(lot.payment_mode),
            payment_router=None if lot.payment_router is None else str(lot.payment_router),
            seat_valid=snapshot.seat_valid,
            # I7: reaching here means the buyer-order row lock is held by this
            # transaction; a handler that skipped the lock cannot get past it.
            row_lock_taken=True,
            total_cents=order.total_cents,
            cap_cents=snapshot.cap_cents,
            expected_cents=order.total_cents,
            observation=request.observation,
            void_source=request.void_source,
            reject_reason=request.reject_reason,
            has_completed_capture=snapshot.has_completed_capture,
            ops_refund=request.ops_refund,
            pending_wait_exceeded=request.pending_wait_exceeded,
            saved_permission_status=snapshot.saved_permission_status,
            seat_locked_until=(
                request.seat_locked_until
                if request.seat_locked_until is not None
                else order.seat_locked_until
            ),
        )

    # -- effects ---------------------------------------------------------------

    async def _write_state(
        self,
        session: AsyncSession,
        order: BuyerOrder,
        request: TransitionRequest,
        transition: Transition,
        snapshot: _Snapshot,
    ) -> None:
        """Move the row and record the resource facts the guard demanded.

        I7: the seat stays locked while AUTHORIZING, so BO-03 writes the lock
        horizon its handler supplied; nothing here clears it.
        """
        order.status = BuyerOrderStatus(transition.to_state)
        order.updated_at = snapshot.written_at
        if request.void_source is not None:
            order.void_source = request.void_source
        if request.reject_reason is not None:
            order.reject_reason = request.reject_reason
        if request.seat_locked_until is not None:
            order.seat_locked_until = request.seat_locked_until
        await session.flush()

    async def _apply_effects(
        self,
        session: AsyncSession,
        *,
        transition: Transition,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        from_state: str,
        money_key: str,
        snapshot: _Snapshot,
        facts: BuyerOrderFacts,
    ) -> None:
        """Audit, ledger, notification and next jobs, all in this transaction (I10)."""
        for effect in transition.effects:
            if effect == "audit":
                await self._audit(session, transition, lot, order, request, from_state, money_key)
            elif effect.startswith("ledger:"):
                await self._ledger_fact(
                    session,
                    kind=effect.removeprefix("ledger:"),
                    lot=lot,
                    order=order,
                    request=request,
                    money_key=money_key,
                    facts=facts,
                    snapshot=snapshot,
                )
            elif effect == "notify":
                await self._notify(session, transition, lot, order, request, snapshot)
            elif effect.startswith("job:"):
                await self._enqueue(
                    session,
                    kind=effect.removeprefix("job:"),
                    transition=transition,
                    lot=lot,
                    order=order,
                    request=request,
                )
            else:
                # An effect prefix the contract does not define is a defect here,
                # not a licence to guess what it meant.
                raise ApplicationError("INTERNAL_ERROR")

    async def _audit(
        self,
        session: AsyncSession,
        transition: Transition,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        from_state: str,
        money_key: str,
    ) -> None:
        payload: dict[str, Any] = {
            "machine": MACHINE,
            "transition_id": transition.id,
            "from": from_state,
            "to": transition.to_state,
            "trigger": request.trigger,
            "lot_id": str(lot.id),
            "pool_id": str(lot.pool_id),
            "payment_mode": None if lot.payment_mode is None else str(lot.payment_mode),
            "payment_router": None if lot.payment_router is None else str(lot.payment_router),
            "total_cents": order.total_cents,
            "effects": list(transition.effects),
            "idempotency_key": money_key,
        }
        if request.void_source is not None:
            payload["void_source"] = request.void_source
        if request.reject_reason is not None:
            payload["reject_reason"] = request.reject_reason
        if request.observation is not None:
            payload["observation"] = {
                "kind": request.observation.kind,
                "status": request.observation.status,
                "reference": request.observation.reference,
                "amount_cents": request.observation.amount_cents,
                "source": request.observation.source,
                # The reason a seat was failed on evidence of its own, such as
                # AMOUNT_MISMATCH or UNVERIFIABLE (vault-charge.md section 7).
                "error_code": request.observation.error_code,
            }
        await self.audit.append(
            session,
            actor=request.actor,
            action=f"buyer_order.{transition.to_state.lower()}",
            subject_type="buyer_order",
            subject_id=str(order.id),
            payload=payload,
        )

    async def _ledger_fact(
        self,
        session: AsyncSession,
        *,
        kind: str,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        money_key: str,
        facts: BuyerOrderFacts,
        snapshot: _Snapshot,
    ) -> None:
        """Record one money fact, from validated evidence only (I4, I5)."""
        amount = checkout_guards.ledger_amount_cents(facts)
        reference = (
            request.observation.reference
            if request.observation is not None and request.observation.reference
            else snapshot.capture_id or snapshot.auth_id or snapshot.paypal_order_id or ""
        )
        if amount is None or not reference:
            # Never an invented amount or reference: a fact no evidence backs is an
            # integrity failure, not a zero (I4, config-and-errors.md).
            raise ApplicationError("INTEGRITY_ERROR")
        # One PayPal call can produce two ledger facts (a capture that reads PENDING
        # and later COMPLETED), so the section 3 text is scoped by the kind: the bare
        # key would be reused for a different payload (I9).
        await self.ledger.record(
            session,
            lot_id=lot.id,
            buyer_order_id=order.id,
            kind=kind,
            amount_cents=amount,
            paypal_ref=reference,
            idempotency_key=f"{money_key}:{kind.lower()}",
            source=request.source,
        )

    async def _notify(
        self,
        session: AsyncSession,
        transition: Transition,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
        snapshot: _Snapshot,
    ) -> None:
        payload: dict[str, Any] = {
            "lot_id": str(lot.id),
            "buyer_order_id": str(order.id),
            "transition_id": transition.id,
            "to_state": transition.to_state,
            "payment_router": None if lot.payment_router is None else str(lot.payment_router),
        }
        if request.reject_reason is not None:
            payload["reject_reason"] = request.reject_reason
        await self.notifier.notify(
            session,
            user_id=snapshot.user_id,
            kind=f"buyer_order.{transition.to_state.lower()}",
            payload=payload,
        )

    async def _enqueue(
        self,
        session: AsyncSession,
        *,
        kind: str,
        transition: Transition,
        lot: Lot,
        order: BuyerOrder,
        request: TransitionRequest,
    ) -> None:
        """Enqueue the next job with the keys of ``domain-ports.md`` section 5."""
        if kind == "lot.refill" and not checkout_guards.creates_vacancy(
            to_state=transition.to_state, void_source=request.void_source
        ):
            # Vacancy rule: a VOIDED with void_source lot_failing frees no seat, so
            # no refill is offered (state-machines.md, after the buyer_order table).
            return
        if kind.startswith("lot."):
            payload: dict[str, Any] = {"lot_id": str(lot.id)}
            concurrency = f"lot:{lot.id}"
            dedupe = f"try_fund:{lot.id}" if kind == "lot.try_fund" else None
            if kind == "lot.refill":
                dedupe = f"refill:{lot.id}"
        else:
            # No ``buyer_order`` effect carries a payload: ``job:void.run`` and
            # ``job:refund.run`` are enqueued by ``failure.py`` with their own keys, and
            # ``void_source`` there is what the vacancy rule reads (CR-8).
            payload = {"buyer_order_id": str(order.id)}
            concurrency = f"bo:{order.id}"
            dedupe = None
        await self.jobs.enqueue(
            session, kind, payload, concurrency_key=concurrency, dedupe_key=dedupe
        )
