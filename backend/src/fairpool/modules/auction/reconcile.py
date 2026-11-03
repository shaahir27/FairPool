"""AI offer reconciliation: flags that can only withhold a bid (T06A05).

Contract: ``ai-schemas.md`` section 4 (task RECONCILE) and its Phase 2 amendment,
``state-machines.md`` BS-04, BS-05 and BS-10, ``db-schema.md`` ``bid_flags``, and
``config-and-errors.md`` section 5's ``R7_AI_BLOCKING``.

The asymmetry is the whole point (design 10.5, FR-AI-02): a BLOCKING flag moves the bid
to FLAGGED, which the award then rejects (R7) until the merchant saves a corrected
revision. Nothing here can make a bid eligible, edit a field or accept a variation for
a buyer, and a WARNING -- including the search similarity advisory -- never changes a
status (INT-1).

It runs inline on the merchant's confirm, not as a job: ``ai.reconcile`` is a
transition trigger and ``domain-ports.md`` section 5 names no kind for it, so adding a
queue row would be a contract change no task asked for.

When the model is unavailable, or its flag cannot be grounded in the merchant's own
text, or its answer contradicts itself, the bid **waits**: it takes a BLOCKING ``OTHER``
flag naming the hold, which lands it in FLAGGED. That is reversible through BS-05 (a
corrected revision) and it never lets an unreviewed offer pass as clean --
``ai-schemas.md`` section 4 requires exactly this for bids carrying free text, while a
structured-only bid proceeds untouched.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Bid, BidFlag, BidRevision
from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import BidStatus
from fairpool.db.models.pools import Lot
from fairpool.domain import hashing
from fairpool.modules.auction.bids import apply_bid_transition
from fairpool.ports import AiRunLogger, AuditLog, Notifier, ReconcileResult

logger: Final[logging.Logger] = logging.getLogger("fairpool.auction.reconcile")

AI_TASK: Final[str] = "RECONCILE"

#: The evidence column's limit in ``db-schema.md``.
EVIDENCE_LIMIT: Final[int] = 200

#: What the hold rows say. A merchant reads these on their own bid, so they name the
#: cause instead of blaming the merchant.
HOLD_UNAVAILABLE: Final[str] = "Offer not reviewed: the reconciliation helper is unavailable"
HOLD_UNGROUNDED: Final[str] = "Offer not reviewed: the answer did not quote the merchant's own text"


class OfferReconciler:
    """Reconcile one confirmed revision against the lot's requirements."""

    def __init__(
        self,
        *,
        audit: AuditLog,
        run_logger: AiRunLogger,
        notifier: Notifier,
        ai: Any | None,
        model: str,
        prompt_version: str,
    ) -> None:
        self.audit = audit
        self.run_logger = run_logger
        self.notifier = notifier
        self.ai = ai
        self.model = model
        self.prompt_version = prompt_version

    async def reconcile(
        self,
        session: AsyncSession,
        *,
        bid: Bid,
        revision: BidRevision,
        lot: Lot,
        pool: Pool,
        merchant_user_id: UUID,
    ) -> list[BidFlag]:
        """Flag the bid from the model's answer, or hold it. Returns the rows written."""
        if str(bid.status) != str(BidStatus.CONFIRMED):
            # Only a confirmed revision has something decided to compare. A draft, a
            # proposal or an already-flagged bid is left exactly as it is.
            return []
        text = _free_text(revision)
        if not text:
            # Structured fields only: there is no prose to reconcile, so the bid proceeds.
            return []

        requirement = {
            "product_key": str(pool.template.get("product_key") or ""),
            "condition": str(pool.template.get("condition") or ""),
            "bundle_contents": [str(part) for part in pool.template.get("bundle_contents") or []],
            "seats": int(lot.seats),
            "zone_id": str(lot.zone_id),
        }
        run_id, result = await self._call(
            session,
            requirement=requirement,
            structured=dict(revision.structured),
            text=text,
        )
        flags = _flags(result, text=text) if result is not None else None
        if flags is None:
            why = HOLD_UNAVAILABLE if result is None else HOLD_UNGROUNDED
            return await self._mark(
                session,
                bid=bid,
                revision=revision,
                run_id=run_id,
                user_id=merchant_user_id,
                evidence=why,
                payload={"hold": "unreviewed" if result is None else "ungrounded"},
            )
        if not flags:
            return []

        rows = [
            BidFlag(
                id=uuid4(),
                bid_revision_id=revision.id,
                ai_run_id=run_id,
                code=str(flag["code"]),
                severity=str(flag["severity"]),
                field=str(flag["field"]),
                evidence=str(flag["snippet"])[:EVIDENCE_LIMIT],
            )
            for flag in flags
        ]
        for row in rows:
            session.add(row)
        await session.flush()

        blocking = sorted(str(row.code) for row in rows if str(row.severity) == "BLOCKING")
        if not blocking:
            # Warnings never change a status (INT-1, ai-schemas.md section 4).
            return rows
        await apply_bid_transition(
            session,
            bid=bid,
            to_status="FLAGGED",
            trigger="ai.reconcile",
            audit=self.audit,
            actor="worker",
            payload={"codes": blocking},
        )
        await self.notifier.notify(
            session,
            user_id=merchant_user_id,
            kind="bid.flagged",
            payload={"lot_id": str(bid.lot_id), "bid_id": str(bid.id), "codes": blocking},
        )
        return rows

    # ------------------------------------------------------------------- the call

    async def _call(
        self,
        session: AsyncSession,
        *,
        requirement: dict[str, Any],
        structured: dict[str, Any],
        text: str,
    ) -> tuple[UUID, dict[str, Any] | None]:
        """One RECONCILE call with its ``ai_runs`` row, and the answer or ``None``."""
        input_hash = hashing.request_hash(
            {
                "task": AI_TASK,
                "input": {
                    "lot_requirement": requirement,
                    "bid_structured": structured,
                    "text": text,
                },
            }
        )
        started = time.perf_counter()
        output: dict[str, Any] | None = None
        error: str | None = None
        if self.ai is None:
            error = "AIUnavailable"
        else:
            try:
                result: ReconcileResult = await self.ai.reconcile_offer(
                    session, lot_requirement=requirement, bid_structured=structured, text=text
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure becomes a hold
                error = type(exc).__name__
            else:
                output = result if isinstance(result, dict) else None
                if output is None:
                    error = "SchemaError"
        run_id = await self.run_logger.log(
            session,
            task=AI_TASK,
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
        return run_id, output

    async def _mark(
        self,
        session: AsyncSession,
        *,
        bid: Bid,
        revision: BidRevision,
        run_id: UUID,
        user_id: UUID,
        evidence: str,
        payload: dict[str, Any],
    ) -> list[BidFlag]:
        """One BLOCKING ``OTHER`` flag and BS-04: the bid waits instead of passing."""
        row = BidFlag(
            id=uuid4(),
            bid_revision_id=revision.id,
            ai_run_id=run_id,
            code="OTHER",
            severity="BLOCKING",
            field="reconcile",
            evidence=evidence[:EVIDENCE_LIMIT],
        )
        session.add(row)
        await session.flush()
        await apply_bid_transition(
            session,
            bid=bid,
            to_status="FLAGGED",
            trigger="ai.reconcile",
            audit=self.audit,
            actor="worker",
            payload={"codes": ["OTHER"], **payload},
        )
        await self.notifier.notify(
            session,
            user_id=user_id,
            kind="bid.flagged",
            payload={"lot_id": str(bid.lot_id), "bid_id": str(bid.id), **payload},
        )
        return [row]


def _free_text(revision: BidRevision) -> str:
    """The merchant's own words: the only text the model may quote back as evidence."""
    parts = [value for value in (revision.quote_text, revision.notes) if isinstance(value, str)]
    return "\n".join(part for part in parts if part.strip())


def _flags(result: dict[str, Any], *, text: str) -> list[dict[str, Any]] | None:
    """The answer's flags, validated and grounded, or ``None`` for a hold.

    A snippet that is not in the merchant's text is not evidence, and a ``consistent``
    answer carrying a BLOCKING flag contradicts itself. Either way the safe answer is
    "this review did not happen", never a silent clean bill (Phase 2 amendment).
    """
    raw = result.get("flags")
    if not isinstance(raw, list):
        return None
    lowered = text.lower()
    flags: list[dict[str, Any]] = []
    for flag in raw:
        if not isinstance(flag, dict):
            return None
        code, severity = flag.get("code"), flag.get("severity")
        field, snippet = flag.get("field"), flag.get("snippet")
        if not isinstance(code, str) or severity not in ("BLOCKING", "WARNING"):
            return None
        if not isinstance(field, str) or not field.strip():
            return None
        if not isinstance(snippet, str) or not snippet.strip():
            return None
        if snippet.strip().lower() not in lowered:
            return None
        flags.append({"code": code, "severity": str(severity), "field": field, "snippet": snippet})
    if any(flag["severity"] == "BLOCKING" for flag in flags) and result.get("consistent") is True:
        return None
    return flags
