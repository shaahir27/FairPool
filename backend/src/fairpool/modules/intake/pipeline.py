"""Intake: retrieval, the model's proposal, deterministic checks, confirmation (T04B01).

Contract: ``ai-schemas.md`` sections 1, 2 and 8, ``api.md`` "Intake", FR-IN-01 to
FR-IN-08, FR-AI-01, F19, CR-4 (``intake_proposals``).

One turn, in this order:

1. retrieve at most five OPEN pools through ``SearchService`` (public documents
   only: buyer entries, caps, requests and users are never indexed, INT-1);
2. call ``AIClient.parse_intake`` with the message, the candidates and the turns
   already spent on this session;
3. apply the deterministic checks of ``ai-schemas.md`` section 2 to the model's
   proposal. A deviation becomes one clarifying question (never a silent change);
   after ``MAX_TURNS`` turns without a usable request the answer is ``NO_MATCH``
   plus the manual form's instruction (FR-IN-08);
4. build the manual payload and let ``domain.request_rules`` accept or reject it.
   That validator is the same one the manual form and the join use, so intake has
   exactly one acceptance rule; a rejection here is a ``NO_MATCH`` and never a
   stored proposal (F19);
5. persist one owner-bound ``intake_proposals`` row and answer with the card the
   server builds from the pool template. Nothing raw from the model reaches the
   buyer.

``ManualIntakeService.confirm`` is the only writer of ``confirmed_requests``: this
module's :meth:`IntakeService.confirm` checks the proposal's owner, expiry and
single use, then delegates, so a request confirmed through intake and through the
manual form cannot differ.

The turn history lives in this process, keyed by the pair ``(user_id,
session_id)``: the contracts give the request shape no field to carry it,
``intake_proposals`` records only complete proposals, and CR-4 adds no table for
partial turns. A restart therefore costs a buyer a turn, never a wrong
confirmation, and a guessed ``session_id`` cannot read or reset another buyer's
history or their three-turn budget.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import ConfirmedRequest, Pool
from fairpool.db.models.catalog import IntakeProposal as IntakeProposalRow
from fairpool.db.models.enums import PoolStatus
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.domain.request_rules import ValidatedRequest, validate_manual_request
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.ports import AIClient, AiRunLogger, AuditLog, Clock, SearchService

#: ``ai-schemas.md`` section 2: at most five candidates per call and three turns.
MAX_CANDIDATES: Final[int] = 5
MAX_TURNS: Final[int] = 3

#: Sessions kept in memory; the history is a convenience, so the oldest is dropped.
MAX_SESSIONS: Final[int] = 512

#: CR-4: the proposal window on the database clock, capped by the pool's close.
#: A module constant on purpose: ``config-and-errors.md`` has no key for it and
#: this task adds none.
PROPOSAL_TTL_S: Final[int] = 30 * 60

MANUAL_FORM_INSTRUCTION: Final[str] = (
    "I could not turn that into a request for an open pool. "
    "You can still enter with the manual form."
)

NO_CHARGE_NOTICE: Final[str] = (
    # Mode-neutral on purpose: under PAYMENT_MODE=vault_charge no hold is ever placed,
    # and the card cannot know a lot's stamped mode yet, so it promises no charge and
    # no hold at all (Q-2026-11-01-19; api.md's sentence needs a change request).
    "Nothing is charged now. A merchant and an exact price are confirmed first, you are "
    "never charged above the maximum you set here, and any payment follows your own "
    "approval of that offer."
)
LOTS_MAY_DIFFER_NOTICE: Final[str] = (
    "Separate lots in this pool can end with different winning merchants and prices."
)

_STATUS_READY: Final[str] = "READY_TO_CONFIRM"
_STATUS_ASK: Final[str] = "NEEDS_CLARIFICATION"
_STATUS_NONE: Final[str] = "NO_MATCH"

_SERVED_STATE_NAMES: Final[dict[str, str]] = {
    "new york": "NY",
    "new jersey": "NJ",
    "pennsylvania": "PA",
}


def _text(value: object, *, limit: int = 4000) -> str | None:
    """A model-supplied string, or ``None``: an untrusted field is never coerced."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:limit] if stripped else None


def _integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _terms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _cents_from_amount(amount: str | None) -> int | None:
    """``ai-schemas.md`` 1.7: a decimal string to integer cents, or a rejection."""
    if amount is None:
        return None
    whole, _, fraction = amount.partition(".")
    if not whole.isdigit() or len(fraction) > 2 or (fraction and not fraction.isdigit()):
        return None
    value = int(whole) * 100 + int(fraction.ljust(2, "0"))
    return value if value > 0 else None


def latest_delivery(template: dict[str, Any]) -> date | None:
    """The last date the pool can deliver: ``fund_by`` plus ``delivery_sla_days``.

    This is the card's ``latest_delivery`` value (``api.md``) and the date the
    clarifying question quotes. It accepts nothing: acceptance is
    ``validate_manual_request``, which applies the same arithmetic as one of its
    rules (``domain.request_rules``).
    """
    fund_by = template.get("fund_by")
    sla = template.get("delivery_sla_days")
    if not isinstance(fund_by, str) or not isinstance(sla, int) or isinstance(sla, bool):
        return None
    try:
        return date.fromisoformat(fund_by) + timedelta(days=sla)
    except ValueError:
        return None


def _candidate(pool: Pool) -> dict[str, Any]:
    """One public candidate card: the five fields ``ai-schemas.md`` section 2 names."""
    template = pool.template
    regions = [
        region
        for zone in template.get("zones", [])
        if isinstance(zone, dict)
        for region in zone.get("regions", [])
        if isinstance(region, str)
    ]
    return {
        "pool_id": str(pool.id),
        "title": pool.title,
        "variant": template.get("variant"),
        "condition": template.get("condition"),
        "regions": regions,
    }


def _zone_regions(template: dict[str, Any]) -> list[str]:
    return [
        region
        for zone in template.get("zones", [])
        if isinstance(zone, dict)
        for region in zone.get("regions", [])
        if isinstance(region, str)
    ]


class IntakeService:
    """``POST /intake/messages`` and ``POST /intake/confirm`` behind one service."""

    def __init__(
        self,
        *,
        search: SearchService,
        ai: AIClient | None,
        audit: AuditLog,
        clock: Clock,
        run_logger: AiRunLogger,
        model: str,
        prompt_version: str = "intake-v1",
    ) -> None:
        self.search = search
        self.ai = ai
        self.audit = audit
        self.clock = clock
        self.run_logger = run_logger
        self.model = model
        self.prompt_version = prompt_version
        self.manual = ManualIntakeService(audit)
        # Keyed by owner and session: the session id arrives in the request body, so it
        # alone must never select a history (a guessed id would mix buyers' turns).
        self._history: OrderedDict[tuple[UUID, UUID], list[dict[str, Any]]] = OrderedDict()

    # ----------------------------------------------------------------- propose

    async def propose(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        message: str,
        pool_id_override: UUID | None = None,
        session_id: UUID | None = None,
    ) -> dict[str, Any]:
        """One conversation turn: a card, a question or the manual-form instruction."""
        sid = session_id or uuid4()
        key = (user_id, sid)
        history = list(self._history.get(key, []))
        pools = await self._candidates(session, message=message, override=pool_id_override)
        candidates = [_candidate(pool) for pool in pools]

        proposal = await self._ask(session, message=message, candidates=candidates, history=history)
        if proposal is None:
            self._forget(key)
            return self._reply(sid, _STATUS_NONE, MANUAL_FORM_INSTRUCTION)

        pool = self._matched_pool(pools, proposal)
        if pool is None:
            # ai-schemas.md 2.1: a pool outside the candidates, or not OPEN, is not a match.
            self._forget(key)
            return self._reply(sid, _STATUS_NONE, MANUAL_FORM_INSTRUCTION)

        template = {**pool.template, "pool_id": str(pool.id)}
        delivery = proposal.get("delivery")
        region = _text(delivery.get("region")) if isinstance(delivery, dict) else None
        if region is not None:
            canonical_region = _SERVED_STATE_NAMES.get(region.casefold(), region.upper())
            # ai-schemas.md 2.5: a name alias cannot widen the frozen delivery zones.
            if canonical_region in _zone_regions(template):
                proposal = {**proposal, "delivery": {"region": canonical_region}}
        question = self._question(proposal, template) or self._model_question(proposal)
        if question is not None:
            self._remember(key, message, question)
            if len(history) + 1 >= MAX_TURNS:
                # ai-schemas.md 2.8: three turns, then the manual form.
                self._forget(key)
                return self._reply(sid, _STATUS_NONE, MANUAL_FORM_INSTRUCTION)
            return self._reply(sid, _STATUS_ASK, question)

        validated = self._validate(template, proposal)
        if validated is None:
            # Every listed check passed but the shared validator still rejects the
            # request: fail closed with the manual form, never store it (F19).
            self._forget(key)
            return self._reply(sid, _STATUS_NONE, MANUAL_FORM_INSTRUCTION)

        row = await self._persist(
            session, user_id=user_id, pool=pool, payload=self._payload(proposal)
        )
        self._forget(key)
        return self._reply(
            sid,
            _STATUS_READY,
            None,
            card=self._card(row=row, pool=pool, validated=validated),
        )

    # ----------------------------------------------------------------- confirm

    async def confirm(
        self, session: AsyncSession, *, user_id: UUID, proposal_id: UUID
    ) -> ConfirmedRequest:
        """Turn an unexpired, unconsumed proposal into the canonical request.

        Owner-scoped by the query itself, so another buyer's proposal answers
        ``NOT_FOUND`` exactly like an unknown one. An expired or consumed proposal
        replays its own ``confirmed_requests`` row when one exists and is
        ``REQUEST_INVALID`` otherwise: a proposal can be confirmed once.
        """
        row = await session.scalar(
            select(IntakeProposalRow)
            .where(IntakeProposalRow.id == proposal_id, IntakeProposalRow.user_id == user_id)
            .with_for_update()
        )
        if row is None:
            raise ApplicationError("NOT_FOUND")
        now = await self.clock.db_now(session)
        if row.consumed_at is not None or now >= row.expires_at:
            replay = await self._existing(session, row)
            if replay is not None:
                return replay
            raise ApplicationError("REQUEST_INVALID")

        payload = dict(row.proposal)
        record = await self.manual.confirm(
            session, user_id=user_id, pool_id=row.pool_id, payload=payload
        )
        if str(record.rules_hash) != str(row.rules_hash):
            # The rules the buyer was shown and the rules the request froze against
            # must be the same document (CR-4); a mismatch is not a confirmation.
            raise ApplicationError("RULES_MISMATCH")
        row.consumed_at = now
        await session.flush()
        return record

    # ----------------------------------------------------------------- retrieval

    async def _candidates(
        self, session: AsyncSession, *, message: str, override: UUID | None
    ) -> list[Pool]:
        """The OPEN pools this turn may match: an explicit id, or the top search hits."""
        if override is not None:
            pool = await session.scalar(
                select(Pool).where(Pool.id == override, Pool.status == PoolStatus.OPEN)
            )
            return [] if pool is None else [pool]
        hits = await self.search.search(
            session, q=message, kinds=["pool"], status=[str(PoolStatus.OPEN)], limit=MAX_CANDIDATES
        )
        ids = [UUID(hit.doc_id) for hit in hits]
        if not ids:
            return []
        rows = list(
            (
                await session.scalars(
                    select(Pool).where(Pool.id.in_(ids), Pool.status == PoolStatus.OPEN)
                )
            ).all()
        )
        by_id = {pool.id: pool for pool in rows}
        # Keep the retrieval order the search service produced (INT-1: advisory).
        return [by_id[pool_id] for pool_id in ids if pool_id in by_id]

    @staticmethod
    def _matched_pool(pools: list[Pool], proposal: dict[str, Any]) -> Pool | None:
        """ai-schemas.md 2.1: the id must name a supplied candidate, and it is OPEN."""
        raw = _text(proposal.get("pool_id"))
        if raw is None:
            return None
        try:
            chosen = UUID(raw)
        except ValueError:
            return None
        return next((pool for pool in pools if pool.id == chosen), None)

    # ------------------------------------------------------------- model call

    async def _ask(
        self,
        session: AsyncSession,
        *,
        message: str,
        candidates: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Call the model once and record the attempt, whatever its outcome.

        ``ai-schemas.md`` section 1.5 wants an ``ai_runs`` row for every call and
        section 1.1 wants a fallback instead of an exception, so a failure is logged
        by its type name (never its text) and answered with the manual form.
        """
        input_hash = hashing.request_hash(
            {
                "task": "INTAKE",
                "input": {"message": message, "candidates": candidates, "history": history},
            }
        )
        started = time.perf_counter()
        output: dict[str, Any] | None = None
        error: str | None = None
        if self.ai is None:
            error = "AIUnavailable"
        else:
            try:
                proposal = await self.ai.parse_intake(
                    session, message=message, candidates=candidates, history=history
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure means "manual form"
                error = type(exc).__name__
            else:
                if isinstance(proposal, dict):
                    output = proposal
                else:
                    error = "SchemaError"
        await self.run_logger.log(
            session,
            task="INTAKE",
            model=self.model,
            prompt_version=self.prompt_version,
            input_hash=input_hash,
            output=output,
            ok=error is None,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tokens_in=0,
            tokens_out=0,
        )
        return output

    # ------------------------------------------------- deterministic checks

    def _question(self, proposal: dict[str, Any], template: dict[str, Any]) -> str | None:
        """The first deviation of ``ai-schemas.md`` 2.2 to 2.7, phrased as a question."""
        condition = template.get("condition")
        if _text(proposal.get("condition")) not in (None, condition):
            # 2.2: a mismatch is a question, never a silent change.
            return f"This pool is for {condition} items only. Should I continue with {condition}?"

        quantity = _integer(proposal.get("quantity"))
        if quantity is not None and quantity != 1:
            # 2.3: more than one unit is explained, and the proposal continues with one
            # only if the buyer agrees.
            return "Each entry is for one unit (limit one per entry). Should I continue with one?"

        money = proposal.get("max_total")
        amount = _text(money.get("amount")) if isinstance(money, dict) else None
        currency = _text(money.get("currency")) if isinstance(money, dict) else None
        if currency is not None and currency.upper() != "USD":
            # 2.4: any other currency is an ambiguity, never a conversion.
            return f"This pool charges in USD. Should I use USD instead of {currency.upper()}?"
        cents = _cents_from_amount(amount)
        if cents is None:
            return "What is the most you will pay in total, in USD?"
        cap_min = _integer(template.get("cap_min_cents"))
        cap_max = _integer(template.get("cap_max_cents"))
        if (cap_min is not None and cents < cap_min) or (cap_max is not None and cents > cap_max):
            low = "0.00" if cap_min is None else f"{cap_min / 100:.2f}"
            high = "any amount" if cap_max is None else f"{cap_max / 100:.2f}"
            return f"This pool accepts a total between USD {low} and USD {high}. What is your cap?"

        delivery = proposal.get("delivery")
        region = _text(delivery.get("region")) if isinstance(delivery, dict) else None
        regions = _zone_regions(template)
        if region is None or region not in regions:
            # 2.5: the region must map to exactly one frozen zone, otherwise ask.
            return (
                "Which state should this be delivered to? This pool covers "
                + ", ".join(regions)
                + "."
            )

        required_by = _text(proposal.get("required_by"))
        if required_by is None:
            return "By which date do you need it (YYYY-MM-DD)?"
        bound = latest_delivery(template)
        if bound is not None and required_by < bound.isoformat():
            # 2.6: the pool cannot meet an earlier date; say so and ask for another.
            return f"This pool can only deliver by {bound.isoformat()}. Which date should I use?"

        supported = set(_terms(template.get("bundle_contents")))
        unsupported = [
            term for term in _terms(proposal.get("firm_requirements")) if term not in supported
        ]
        if unsupported:
            # 2.7: an unsupported firm term is shown, never quietly dropped.
            return (
                "This pool does not offer: "
                + ", ".join(unsupported)
                + ". Should I drop that requirement?"
            )
        return None

    @staticmethod
    def _cents(amount: str | None) -> int | None:
        """``ai-schemas.md`` 1.7: decimal string to integer cents, or a rejection."""
        return _cents_from_amount(amount)

    @staticmethod
    def _model_question(proposal: dict[str, Any]) -> str | None:
        """The model's own question, used only when it is not confident (rule 8)."""
        if _text(proposal.get("match_confidence")) == "high":
            return None
        return _text(proposal.get("clarifying_question"))

    # ------------------------------------------------------------- acceptance

    @staticmethod
    def _payload(proposal: dict[str, Any]) -> dict[str, Any]:
        """The buyer-chosen fields of a manual-form payload, from validated model data."""
        delivery = proposal.get("delivery")
        raw_region = delivery.get("region") if isinstance(delivery, dict) else None
        money = proposal.get("max_total")
        raw_amount = money.get("amount") if isinstance(money, dict) else None
        amount = raw_amount if isinstance(raw_amount, str) else ""
        cents = _cents_from_amount(amount) or 0
        return {
            "delivery": {"region": raw_region},
            "required_by": proposal.get("required_by"),
            "max_total_cents": cents,
            "firm": _terms(proposal.get("firm_requirements")),
            "preferences": _terms(proposal.get("preferences")),
        }

    @staticmethod
    def _validate(template: dict[str, Any], proposal: dict[str, Any]) -> ValidatedRequest | None:
        """The shared validator decides; a rejection is never a stored proposal."""
        try:
            return validate_manual_request(template, IntakeService._payload(proposal))
        except ApplicationError:
            return None

    # ------------------------------------------------------------- persistence

    async def _persist(
        self, session: AsyncSession, *, user_id: UUID, pool: Pool, payload: dict[str, Any]
    ) -> IntakeProposalRow:
        """One owner-bound proposal, expiring at ``min(now + TTL, pool close)``."""
        if pool.rules_hash is None:
            # A pool without frozen rules cannot be confirmed against them.
            raise ApplicationError("VALIDATION_ERROR")
        now = await self.clock.db_now(session)
        expires_at = now + timedelta(seconds=PROPOSAL_TTL_S)
        close_at = self._close_at(pool)
        if close_at is not None:
            expires_at = min(expires_at, close_at)
        row = IntakeProposalRow(
            id=uuid4(),
            user_id=user_id,
            pool_id=pool.id,
            proposal=payload,
            rules_hash=pool.rules_hash,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    def _close_at(pool: Pool) -> datetime | None:
        raw = pool.timeline.get("close_at")
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _card(
        self, *, row: IntakeProposalRow, pool: Pool, validated: ValidatedRequest
    ) -> dict[str, Any]:
        """The confirmation card, built from catalog data and the validated request."""
        template = pool.template
        bound = latest_delivery(template)
        if bound is None:
            # The validator accepted this template, so its dates are well formed; a
            # card without a date would be inventing one, so it fails closed.
            raise ApplicationError("INTEGRITY_ERROR")
        return {
            "proposal_id": str(row.id),
            "pool": {
                "id": str(pool.id),
                "title": pool.title,
                "variant": template.get("variant"),
                "condition": template.get("condition"),
                "latest_delivery": bound.isoformat(),
            },
            "delivery": {
                "zone_id": validated.zone_id,
                "region": validated.canonical["delivery"]["region"],
            },
            "required_by": validated.canonical["required_by"],
            "max_total_cents": validated.cap_cents,
            "firm": list(validated.canonical["firm"]),
            "preferences": list(validated.canonical["preferences"]),
            "notices": {
                "no_charge": NO_CHARGE_NOTICE,
                "lots_may_differ": LOTS_MAY_DIFFER_NOTICE,
            },
        }

    async def _existing(
        self, session: AsyncSession, row: IntakeProposalRow
    ) -> ConfirmedRequest | None:
        """The request this proposal already produced, found by its own bytes."""
        pool = await session.scalar(select(Pool).where(Pool.id == row.pool_id))
        if pool is None or pool.rules_hash is None:
            return None
        payload = dict(row.proposal)
        try:
            validated = validate_manual_request({**pool.template, "pool_id": str(pool.id)}, payload)
        except ApplicationError:
            return None
        return await session.scalar(
            select(ConfirmedRequest).where(
                ConfirmedRequest.user_id == row.user_id,
                ConfirmedRequest.pool_id == row.pool_id,
                ConfirmedRequest.rules_hash == row.rules_hash,
                ConfirmedRequest.request_hash == validated.request_hash,
            )
        )

    # ---------------------------------------------------------------- sessions

    def _remember(self, key: tuple[UUID, UUID], message: str, question: str) -> None:
        self._history[key] = [
            *self._history.get(key, []),
            {"message": message, "question": question},
        ]
        self._history.move_to_end(key)
        while len(self._history) > MAX_SESSIONS:
            self._history.popitem(last=False)

    def _forget(self, key: tuple[UUID, UUID]) -> None:
        self._history.pop(key, None)

    @staticmethod
    def _reply(
        sid: UUID,
        status: str,
        question: str | None,
        *,
        card: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "session_id": str(sid),
            "status": status,
            "clarifying_question": question,
            "confirmation_card": card,
        }


__all__ = [
    "LOTS_MAY_DIFFER_NOTICE",
    "MANUAL_FORM_INSTRUCTION",
    "MAX_CANDIDATES",
    "MAX_TURNS",
    "NO_CHARGE_NOTICE",
    "PROPOSAL_TTL_S",
    "IntakeService",
    "latest_delivery",
]
