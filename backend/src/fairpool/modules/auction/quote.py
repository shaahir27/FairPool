"""Merchant quote parsing: a pasted quote becomes a PROPOSED bid (T06B01).

Contract: ``ai-schemas.md`` section 3 (task QUOTE), ``api.md`` "merchant quote",
``state-machines.md`` BS-01 and BS-03, ``db-schema.md`` ``bid_revisions.structured``
and ``flat-delivered-bids.md``.

The model proposes and the merchant confirms. Nothing written here can reach the
auction: an unconfirmed revision is rejected at award (R1 via BS-11) and the
deterministic shape check runs on the merchant's own save, not on this output.
Fields the quote does not state stay empty for the merchant to fill, which is why
this write does not go through ``BidService.save`` -- that path validates a complete
structured object, and a proposal is by definition incomplete.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.ai.schemas import cents
from fairpool.db.models.auction import Bid, BidRevision
from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import BidStatus
from fairpool.db.models.pools import Lot
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.modules.auction.bids import FLAT_DELIVERED_MESSAGE, apply_bid_transition
from fairpool.modules.pools.receipts import format_received_at
from fairpool.ports import AiRunLogger, AuditLog, Clock, QuoteProposal

logger: Final[logging.Logger] = logging.getLogger("fairpool.auction.quote")

#: The quote and notes limit of ``ai-schemas.md`` section 1.
QUOTE_TEXT_LIMIT: Final[int] = 4000


class QuoteService:
    """One pasted quote in, one PROPOSED revision out, with the AI run recorded."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        run_logger: AiRunLogger,
        ai: Any | None,
        model: str,
        prompt_version: str,
        signing_seed: bytes,
        flat_delivered: bool = True,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.run_logger = run_logger
        self.ai = ai
        self.model = model
        self.prompt_version = prompt_version
        self.signing_seed = signing_seed
        self.flat_delivered = flat_delivered

    async def propose(
        self, session: AsyncSession, *, merchant_id: UUID, lot_id: UUID, quote_text: str
    ) -> dict[str, Any]:
        """Parse ``quote_text`` against the lot and store the proposal (BS-01)."""
        lot = await session.get(Lot, lot_id)
        if lot is None:
            raise ApplicationError("NOT_FOUND")
        if str(lot.status) != "BIDDING":
            raise ApplicationError("LOT_NOT_BIDDING")
        pool = await session.get(Pool, lot.pool_id)
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        now = await self.clock.db_now(session)
        if lot.bid_close_at is not None and now >= lot.bid_close_at:
            raise ApplicationError("BID_WINDOW_CLOSED")
        if not quote_text.strip() or len(quote_text) > QUOTE_TEXT_LIMIT:
            raise ApplicationError("VALIDATION_ERROR")

        requirement = self._requirement(pool=pool, lot=lot)
        proposal = await self._call(session, quote_text=quote_text, requirement=requirement)
        if proposal is None:
            # The helper is off or the provider failed: the merchant fills the
            # structured form themselves through PUT /merchant/lots/{id}/bid, which is
            # the same fallback intake uses (FR-IN-08, AI_ENABLED).
            raise ApplicationError("FEATURE_DISABLED")

        structured = self._structured(proposal=proposal, pool=pool)
        ambiguities = self._ambiguities(proposal, structured=structured)
        bid, revision = await self._write(
            session,
            merchant_id=merchant_id,
            lot=lot,
            structured=structured,
            quote_text=quote_text,
            now=now,
        )
        return {
            "bid_id": str(bid.id),
            "revision": int(revision.revision),
            "status": str(bid.status),
            "proposed_fields": structured,
            "ambiguities": ambiguities,
        }

    # ------------------------------------------------------------------- ai call

    def _requirement(self, *, pool: Pool, lot: Lot) -> dict[str, Any]:
        """What the lot requires, as ``ai-schemas.md`` section 3 names it."""
        template = pool.template
        regions: list[str] = []
        for zone in template.get("zones") or []:
            if isinstance(zone, dict) and str(zone.get("zone_id")) == str(lot.zone_id):
                regions = [str(region) for region in zone.get("regions") or []]
        return {
            "product_key": str(template.get("product_key") or ""),
            "condition": str(template.get("condition") or ""),
            "bundle_contents": [str(part) for part in template.get("bundle_contents") or []],
            "seats": int(lot.seats),
            "zone_id": str(lot.zone_id),
            "regions": regions,
        }

    async def _call(
        self, session: AsyncSession, *, quote_text: str, requirement: dict[str, Any]
    ) -> dict[str, Any] | None:
        """One QUOTE call, logged either way; ``None`` means the merchant types it in."""
        input_hash = hashing.request_hash(
            {"task": "QUOTE", "input": {"quote_text": quote_text, "lot_requirement": requirement}}
        )
        started = time.perf_counter()
        output: dict[str, Any] | None = None
        error: str | None = None
        if self.ai is None:
            error = "AIUnavailable"
        else:
            try:
                proposal: QuoteProposal = await self.ai.parse_quote(
                    session, quote_text=quote_text, lot_requirement=requirement
                )
            except Exception as exc:  # noqa: BLE001 - any provider failure means "form"
                error = type(exc).__name__
            else:
                output = proposal if isinstance(proposal, dict) else None
                if output is None:
                    error = "SchemaError"
        await self.run_logger.log(
            session,
            task="QUOTE",
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

    # ------------------------------------------------------------- proposal shape

    def _structured(self, *, proposal: dict[str, Any], pool: Pool) -> dict[str, Any]:
        """The proposal as a ``bid_revisions.structured`` object, nulls kept null.

        Money arrives as ``"600.00"`` text (``ai-schemas.md`` section 1) and becomes
        integer cents here, at the only place that parses it (BD-14, I3). A value that
        does not parse stays unresolved for the merchant rather than being guessed.
        """
        template = pool.template
        raw_tax = proposal.get("tax")
        tax: dict[str, Any] = raw_tax if isinstance(raw_tax, dict) else {}
        raw_rates = tax.get("rate_bps_by_region")
        rates: dict[str, Any] = raw_rates if isinstance(raw_rates, dict) else {}
        mode = tax.get("mode")
        return {
            "v": 1,
            # The server prefills the product from the lot; a different key the merchant
            # types then fails R3 (ai-schemas.md section 3).
            "product_key": str(template.get("product_key") or ""),
            "condition": _text_or(proposal.get("condition"), str(template.get("condition") or "")),
            "bundle_contents": _string_list(proposal.get("bundle_contents")),
            "capacity": _positive(proposal.get("capacity")),
            "target_quantity": _positive(proposal.get("target_quantity")),
            "moq": _positive(proposal.get("moq")),
            "tiers": self._tiers(proposal.get("tiers")),
            "shipping_cents_by_zone": self._shipping(proposal.get("shipping_by_zone")),
            "tax": {
                "mode": mode if mode in ("INCLUDED", "RATE_TABLE") else None,
                "rate_bps_by_region": {str(region): int(rate) for region, rate in rates.items()},
            },
            "delivery": {"sla_days": _positive(proposal.get("delivery_sla_days"))},
            "returns": {"days": _nonnegative(proposal.get("returns_days"))},
            "valid_until": _text_or(proposal.get("valid_until"), None),
            # CR-11: required by bids.py. A quote that never mentions shared inventory
            # asserts only this lot, which understates rather than overclaims, and the
            # merchant confirms the number on screen before review (BS-03).
            "total_capacity": _positive(proposal.get("total_capacity"))
            or _positive(proposal.get("capacity")),
            "evidence": {
                "note": _text_or(proposal.get("evidence_note"), None),
                # The model quotes text it saw; it never supplies a URL (section 1:
                # untrusted input is data, and a link would be rendered to the merchant).
                "url": None,
            },
        }

    @staticmethod
    def _tiers(value: object) -> list[dict[str, Any]]:
        tiers: list[dict[str, Any]] = []
        for tier in value if isinstance(value, list) else []:
            if not isinstance(tier, dict):
                continue
            tiers.append(
                {
                    "min_qty": _positive(tier.get("min_qty")),
                    "item_price_cents": _amount(tier.get("item_price")),
                }
            )
        return tiers

    @staticmethod
    def _shipping(value: object) -> dict[str, int]:
        shipping: dict[str, int] = {}
        if not isinstance(value, dict):
            return shipping
        for zone, amount in value.items():
            cents_value = _amount(amount)
            if isinstance(cents_value, int):
                shipping[str(zone)] = cents_value
        return shipping

    def _ambiguities(
        self, proposal: dict[str, Any], *, structured: dict[str, Any]
    ) -> list[dict[str, str]]:
        """The model's own questions, plus the flat-delivered rule it cannot apply."""
        out: list[dict[str, str]] = []
        for item in proposal.get("ambiguities") or []:
            if isinstance(item, dict) and item.get("field"):
                out.append(
                    {
                        "field": str(item["field"]),
                        "question": str(item.get("question") or "Please confirm this field."),
                    }
                )
        if self.flat_delivered and (
            structured["tax"]["mode"] != "INCLUDED"
            or any(structured["shipping_cents_by_zone"].values())
        ):
            # The pool prices one delivered price; the merchant must fix it before the
            # bid can be saved at all (flat-delivered-bids.md).
            out.append({"field": "tax.mode", "question": FLAT_DELIVERED_MESSAGE})
        return out

    # ---------------------------------------------------------------------- write

    async def _write(
        self,
        session: AsyncSession,
        *,
        merchant_id: UUID,
        lot: Lot,
        structured: dict[str, Any],
        quote_text: str,
        now: Any,
    ) -> tuple[Bid, BidRevision]:
        """Store the proposal as a new revision and move the bid to PROPOSED (BS-01)."""
        bid = await session.scalar(
            select(Bid)
            .where(Bid.lot_id == lot.id, Bid.merchant_id == merchant_id)
            .with_for_update()
        )
        if bid is None:
            bid = Bid(
                id=uuid4(),
                lot_id=lot.id,
                merchant_id=merchant_id,
                status=BidStatus.DRAFT,
                current_revision=0,
            )
            session.add(bid)
            await session.flush()
        revision = int(bid.current_revision) + 1
        if str(bid.status) != str(BidStatus.DRAFT):
            # BS-12: a merchant who re-quotes takes the bid back to DRAFT with a new
            # revision and its own receipt, before this proposal is written.
            await apply_bid_transition(
                session,
                bid=bid,
                to_status="DRAFT",
                trigger="merchant.revise",
                audit=self.audit,
                payload={"revision": revision, "via": "quote"},
            )
        receipt_hash = hashing.bid_receipt_hash(
            str(bid.id), revision, structured, format_received_at(now)
        )
        row = BidRevision(
            id=uuid4(),
            bid_id=bid.id,
            revision=revision,
            structured=structured,
            quote_text=quote_text,
            notes=None,
            receipt_hash=receipt_hash,
            receipt_signature=hashing.sign_ed25519(
                hashing.bid_receipt_payload(str(bid.id), revision, receipt_hash), self.signing_seed
            ),
        )
        session.add(row)
        bid.current_revision = revision
        await session.flush()
        await apply_bid_transition(
            session,
            bid=bid,
            to_status="PROPOSED",
            trigger="merchant.quote",
            audit=self.audit,
            payload={"revision": revision, "transition_id": "BS-01"},
        )
        return bid, row


def _text_or(value: object, fallback: str | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(part) for part in value if isinstance(part, str) and part.strip()]


def _positive(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _nonnegative(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _amount(value: object) -> int | None:
    """A ``"600.00"`` proposal string to integer cents, or unresolved."""
    if not isinstance(value, str):
        return None
    try:
        return cents(value)
    except ValueError:
        return None
