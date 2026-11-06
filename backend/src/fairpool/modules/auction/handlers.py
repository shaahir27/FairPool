"""The lot auction handlers: ``lot.bid_open``, ``lot.bid_close`` and ``lot.award``.

Contract: ``domain-ports.md`` section 5 (the three kinds, their payloads and their
concurrency keys), ``state-machines.md`` LS-01 to LS-04, PS-06 and the bid machine
BS-06 to BS-11, ``fairness-and-hashing.md`` sections 10 and 11, and the ``bids``,
``bid_revisions``, ``bid_flags`` and ``awards`` tables in ``db-schema.md``.

Four rules this module exists to honour:

* **The rules engine stays pure.** ``domain/auction_rules.py`` decides R1 to R9; this
  file is its only production caller and the only place that turns an assignment into
  an ``awards`` row. Nothing here re-implements a comparison the domain already makes.
* **Every status change is a whitelisted transition with its audit row** in the
  caller's transaction (I10), in the Member-B idiom ``allocation/service.py`` and
  ``pools/service.py`` already use: ``assert_transition``, then the write, then the
  audit. ``apply_lot_transition`` lives in Member A's checkout lane, and
  ``tools/check_imports.py`` rule 5 keeps this module from importing it.
* **Lots are awarded in ``lot_order``** (R9). A lot waits until every lower lot is
  decided, so one merchant's capacity is spent lot by lot and never overcommitted.
* **AI output can only withhold.** R7 rejects a bid carrying a BLOCKING flag; no path
  here reads a flag as qualifying a bid the deterministic rules reject (FR-AI-02).

``bid_open`` also applies PS-06, because a lot entering BIDDING is the only trigger
that pool edge names. A window that has not opened yet is rescheduled rather than
forced, and every deadline is read from the database wall clock after the lock (I15).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.auction import Award, Bid, BidFlag, BidRevision, Merchant
from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.enums import (
    AllocationStatus,
    BidStatus,
    FlagSeverity,
    LotStatus,
    PaymentMode,
    PaymentRouter,
    PoolStatus,
)
from fairpool.db.models.pools import Allocation, Lot
from fairpool.domain import auction_rules, hashing
from fairpool.domain.auction_rules import BidFacts, BidOffer, LotFacts, SeatedBuyer, Tier
from fairpool.domain.errors import ApplicationError
from fairpool.domain.states import assert_transition
from fairpool.modules.auction.bids import apply_bid_transition, validate_structured
from fairpool.ports import AuditLog, Clock, JobQueue, Notifier

logger: Final[logging.Logger] = logging.getLogger("fairpool.auction")

#: Byte-identical to ``modules/checkout/engine.py`` LOT_LOCK_NAMESPACE. The two lanes
#: must derive the same per-lot advisory key or ``lot.award`` and ``lot.try_fund`` never
#: contend and I8 breaks silently (Q-2026-11-03-27; guarded by
#: ``tests/unit/test_award_lock_key_matches_checkout_lane``).
LOT_LOCK_NAMESPACE: Final[str] = "fairpool/lot-lock/v1"
_INT64_SPAN: Final[int] = 1 << 63

#: How long an award waits while a lower ``lot_order`` lot is undecided
#: (``domain-ports.md`` section 5: "requeue +2 s while a lower lot_order lot is not
#: past BID_CLOSED").
AWARD_RETRY_S: Final[int] = 2

#: The three attestations ``db-schema.md`` names; R2 requires all three accepted.
ATTESTATION_KEYS: Final[tuple[str, ...]] = (
    "inventory_reserved",
    "map_compliance",
    "delivery_terms_accurate",
)

#: Onboarding states a lot may be awarded to: the reviewed merchant and the
#: stand-in seller that ``PAYMENT_ROUTER=single_seller`` creates (FR-AU-03).
AWARDABLE_ONBOARDING: Final[frozenset[str]] = frozenset({"COMPLETE", "DEMO"})

#: The states a lower ``lot_order`` lot can hold without being past BID_CLOSED
#: (``state-machines.md`` LS-03, ``domain-ports.md`` section 5). AWARDED, CANCELLED and
#: everything past them have left the award window, so they release the next lot.
_UNDECIDED_LOT_STATES: Final[frozenset[str]] = frozenset({"PLANNED", "BIDDING", "BID_CLOSED"})

#: The bid states ``lot.award`` may reject, each by its own whitelist edge: BS-06 from
#: CONFIRMED, BS-10 from FLAGGED, BS-11 from DRAFT or PROPOSED. All four share the
#: ``job:lot.award`` trigger, so the bid's own state picks the edge.
_REJECTABLE_STATES: Final[frozenset[str]] = frozenset({"DRAFT", "PROPOSED", "CONFIRMED", "FLAGGED"})

#: CR-11: what a losing merchant is told about an infeasibility or capacity rejection.
#: Both codes are decided from the seated buyers' hidden caps, so the exact code is a
#: signal about the crowd rather than about the bid: repeated pools let a merchant
#: binary-search the cap curve and price just under it in the next one, which is the
#: information sealing exists to keep private. The precise code still lands in
#: ``bid.reject_reason`` and in the audit row, where ops and the auditor need it.
_MERCHANT_VISIBLE_REASONS: Final[dict[str, str]] = {
    "R8_INFEASIBLE": "did not meet the lot's feasibility or capacity rules",
    "R8_NO_FEASIBLE_TIER": "did not meet the lot's feasibility or capacity rules",
    "R9_CAPACITY_EXHAUSTED": "did not meet the lot's feasibility or capacity rules",
}


def merchant_reject_copy(reason: str) -> str:
    """Coarsen only the codes that describe the crowd; leave the rest exact."""
    return _MERCHANT_VISIBLE_REASONS.get(reason, reason)


def lot_tiebreak_hash(seed_hex: str, lot_id: UUID, merchant_id: UUID) -> str:
    """The FR-AU-04 ranking tie-break for one bid on one lot.

    It is derived from the LOT seed, never the pool seed
    (``fairness-and-hashing.md`` section 1), because that is what a buyer recomputes from
    the published seed: the audit page's verify widget (``frontend/src/audit/verify.ts``,
    still to be written) must use the same two derivations. Guarded against the vector
    file by ``tests/unit/test_fairness_vectors.py``.
    """
    return hashing.tiebreak_hash(hashing.lot_seed(seed_hex, str(lot_id)), str(merchant_id))


def _iso(moment: datetime) -> str:
    """The ISO-8601 text the pure rules parse, always carrying a timezone (I15)."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(value: object) -> datetime | None:
    """A timestamp the merchant typed, or ``None`` when it is not one.

    ``bid_rejection`` parses these itself and raises on a bad value, and a revision is
    untrusted input, so the loader decides the schema failure here instead.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _bundle_key(contents: object) -> str | None:
    """A stable key for a bundle, so R3 compares like with like on both sides.

    The contract gives a bundle as a list of parts and says nothing about order, so the
    key is over the sorted parts in canonical JSON: the same list written two ways
    yields one key. A bundle that is not a list of non-empty strings has no key, and
    R3 then fails on shape (R1) rather than on identity.
    """
    if not isinstance(contents, list) or not all(
        isinstance(part, str) and part.strip() for part in contents
    ):
        return None
    return hashing.sha256_hex(hashing.canonical_json(sorted(contents)))


def _lot_advisory_key(lot_id: UUID) -> int:
    """The signed-bigint advisory key for one lot; identical to the checkout lane's."""
    digest = hashlib.sha256(f"{LOT_LOCK_NAMESPACE}:{lot_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") - _INT64_SPAN


@dataclass(frozen=True)
class _Entry:
    """One candidate the award prices: seated now, or waitlisted in the lot's zone."""

    entry_id: UUID
    cap_cents: int
    seated: bool


@dataclass(frozen=True)
class _BidRow:
    """One merchant's bid on this lot with the revision the rules decide on."""

    bid: Bid
    revision: BidRevision
    merchant: Merchant
    blocking_flags: tuple[str, ...]

    @property
    def merchant_eligible(self) -> bool:
        """R2: an onboarding state that may be awarded and all three attestations."""
        if str(self.merchant.onboarding_status) not in AWARDABLE_ONBOARDING:
            return False
        return all(
            isinstance(self.merchant.attestations.get(key), dict)
            and self.merchant.attestations[key].get("accepted") is True
            for key in ATTESTATION_KEYS
        )


class LotAuctionHandlers:
    """The three B-owned lot kinds, plus the loader the Phase 5 rules engine lacked."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        notifier: Notifier,
        payment_router: str,
        payment_mode: str,
        flat_delivered: bool = True,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.notifier = notifier
        self.payment_router = payment_router
        self.payment_mode = payment_mode
        self.flat_delivered = flat_delivered

    # ------------------------------------------------------------- lot.bid_open

    async def bid_open(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """LS-01, and PS-06 the first time a lot of the pool enters BIDDING."""
        lot = await self._lock_lot(session, UUID(str(payload["lot_id"])))
        if str(lot.status) != str(LotStatus.PLANNED):
            # CR-8 clarification 3: ops already awarded this lot, or its window opened.
            # Nothing to do, and no illegal-transition alert (I10 is not being bent).
            logger.info("auction.bid_open.skipped lot_id=%s status=%s", lot.id, lot.status)
            return
        pool = await self._lock_pool(session, lot.pool_id)
        if await self.clock.db_wall_now(session) < lot.bid_open_at:
            await self._lot_job(session, "lot.bid_open", lot.id, run_at=lot.bid_open_at)
            return
        await self._lot_transition(
            session, lot=lot, to_status="BIDDING", trigger="job:lot.bid_open"
        )
        await self._lot_job(session, "lot.bid_close", lot.id, run_at=lot.bid_close_at)
        if str(pool.status) == str(PoolStatus.ALLOCATED):
            await self._pool_to_running(session, pool)

    # ------------------------------------------------------------ lot.bid_close

    async def bid_close(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """LS-02. A late bid is refused by the bid route, not by this handler."""
        lot = await self._lock_lot(session, UUID(str(payload["lot_id"])))
        if str(lot.status) != str(LotStatus.BIDDING):
            logger.info("auction.bid_close.skipped lot_id=%s status=%s", lot.id, lot.status)
            return
        if await self.clock.db_wall_now(session) < lot.bid_close_at:
            await self._lot_job(session, "lot.bid_close", lot.id, run_at=lot.bid_close_at)
            return
        pool = await self._lock_pool(session, lot.pool_id)
        # CR-11: commit to the bid set before the award exists. Buyers' entries were
        # already committed to a root at close; bids were committed to nothing, so a
        # revision or a whole bid created after this deadline produced a fresh valid
        # receipt that no outside observer could detect (fairness-and-hashing.md §6).
        bids_root, bids_count = await self._bid_set(session, lot.id)
        await self._lot_transition(
            session,
            lot=lot,
            to_status="BID_CLOSED",
            trigger="job:lot.bid_close",
            payload={"bids_root": bids_root, "bids_count": bids_count},
        )
        await self._award_job(session, pool_id=pool.id, lot_id=lot.id)

    @staticmethod
    async def _bid_set(session: AsyncSession, lot_id: UUID) -> tuple[str, int]:
        """The root over this lot's bids: one leaf per bid, its highest revision."""
        latest = (
            select(BidRevision.bid_id, func.max(BidRevision.revision).label("revision"))
            .where(BidRevision.bid_id.in_(select(Bid.id).where(Bid.lot_id == lot_id)))
            .group_by(BidRevision.bid_id)
            .subquery()
        )
        leaves = [
            str(value)
            for value in (
                await session.scalars(
                    select(BidRevision.receipt_hash)
                    .join(
                        latest,
                        and_(
                            latest.c.bid_id == BidRevision.bid_id,
                            latest.c.revision == BidRevision.revision,
                        ),
                    )
                    .order_by(BidRevision.receipt_hash)
                )
            ).all()
        ]
        # An empty bid set has a defined root (EMPTY_MERKLE_ROOT) and count 0, which
        # stays distinguishable from a force-awarded lot that never wrote LS-02.
        return hashing.merkle_root(leaves), len(leaves)

    # ---------------------------------------------------------------- lot.award

    async def award(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """LS-03 or LS-04: the rules engine decides, this handler writes the snapshot."""
        lot = await self._lock_lot(session, UUID(str(payload["lot_id"])))
        if str(lot.status) != str(LotStatus.BID_CLOSED):
            logger.info("auction.award.skipped lot_id=%s status=%s", lot.id, lot.status)
            return
        if await session.scalar(select(Award.id).where(Award.lot_id == lot.id)) is not None:
            # ``awards.lot_id`` is unique: this lot is decided, and a replay must not
            # write a second snapshot of it (I9).
            logger.info("auction.award.already_awarded lot_id=%s", lot.id)
            return
        pool = await self._lock_pool(session, lot.pool_id)
        if await self._lower_lot_undecided(session, pool_id=pool.id, lot=lot):
            # R9 needs the lower lots decided first. The re-enqueue is written here and
            # the runner commits, so ``award:{pool_id}`` is never held across a wait.
            await self._award_job(session, pool_id=pool.id, lot_id=lot.id, delay_s=AWARD_RETRY_S)
            return
        if not self.flat_delivered:
            # shortcut: ``select_across_lots`` ranks with one lot-level seat list, which
            # is exact only while every bid is one flat delivered price. Itemised ranking
            # needs per-offer shipping and tax; refused rather than ranked on the wrong
            # totals (Q-2026-11-03-28). ``BID_PRICING_MODE`` ships as ``flat_delivered``.
            raise ApplicationError("FEATURE_DISABLED")
        if pool.seed_hex is None:
            # BID_CLOSED before SEEDED is a broken snapshot, never a re-derivation (I15).
            raise ApplicationError("INTEGRITY_ERROR")

        now = await self.clock.db_wall_now(session)
        rows = await self._bids(session, lot_id=lot.id)
        entries = await self._candidates(session, lot=lot)
        lot_facts = self._lot_facts(pool=pool, lot=lot, now=now)
        if not rows:
            await self._cancel(session, lot=lot, rows=rows, why="no bid was made")
            return

        offers: list[BidOffer] = []
        survivors: dict[str, _BidRow] = {}
        for row in rows:
            facts = self._bid_facts(row=row, lot=lot)
            reason = auction_rules.bid_rejection(
                facts,
                lot_facts,
                merchant_eligible=row.merchant_eligible,
                flat_delivered=self.flat_delivered,
            )
            if reason is not None:
                await self._reject(session, row=row, reason=reason)
                continue
            if str(row.bid.status) == str(BidStatus.FLAGGED):
                # A flagged bid with no blocking flag left cannot reach ELIGIBLE: the
                # whitelist leaves FLAGGED only through BS-05 (a corrected revision) or
                # BS-10. Leave it out and say so rather than inventing an edge.
                logger.warning("auction.award.flagged_without_flags bid_id=%s", row.bid.id)
                continue
            offers.append(
                BidOffer(
                    bid_id=str(row.bid.id),
                    merchant_id=str(row.merchant.id),
                    tiers=facts.tiers,
                    capacity=int(facts.capacity or 0),
                    tiebreak_hash=lot_tiebreak_hash(str(pool.seed_hex), lot.id, row.merchant.id),
                )
            )
            survivors[str(row.bid.id)] = row

        if not offers:
            await self._cancel(session, lot=lot, rows=rows, why="no bid passed R1 to R7")
            return

        seated = [
            SeatedBuyer(
                entry_id=str(entry.entry_id),
                cap_cents=entry.cap_cents,
                shipping_cents=0,
                tax_rate_bps=0,
                tax_included=True,
            )
            for entry in entries
            if entry.seated
        ]
        assignment = auction_rules.select_across_lots(
            [lot_facts],
            {str(lot.id): seated},
            {str(lot.id): offers},
            await self._remaining_capacity(session, pool_id=pool.id, lot=lot, rows=rows),
        )[str(lot.id)]

        # ELIGIBLE (BS-07) means "all rules pass", so a bid only reaches it once R8 and
        # R9 have agreed: those the rules rejected go to REJECTED with their reason
        # (BS-06), the rest are the winner (BS-08) or LOST (BS-09).
        rejected_by_bid = dict(assignment.rejected)
        for bid_id, row in survivors.items():
            rule_why = rejected_by_bid.get(bid_id)
            if rule_why is not None:
                await self._reject(session, row=row, reason=rule_why)
                continue
            await self._move(session, row=row, to_status="ELIGIBLE")
            if bid_id != assignment.bid_id:
                await self._move(session, row=row, to_status="LOST")
        if assignment.bid_id is None:
            await self._cancel(
                session,
                lot=lot,
                rows=rows,
                why=assignment.reject or "no bid was feasible",
            )
            return

        winner = survivors[assignment.bid_id]
        offer = next(item for item in offers if item.bid_id == assignment.bid_id)
        resolution = auction_rules.resolve_tiers(seated, offer.tiers, lot_facts.moq)
        if resolution.chosen_tier_index is None:
            # select_across_lots only returns a winner from a feasible tier.
            raise ApplicationError("INTEGRITY_ERROR")
        chosen = resolution.evaluations[resolution.chosen_tier_index]
        await self._move(session, row=winner, to_status="AWARDED")

        # flat_delivered: the buyer's total is the item price and the award carries no
        # breakdown (flat-delivered-bids.md section 2). Waitlisted rows are priced too,
        # because lot.open_checkout offers a refilled seat from the same snapshot (CR-4).
        totals = {
            str(entry.entry_id): {
                "item_cents": chosen.item_price_cents,
                "shipping_cents": 0,
                "tax_cents": 0,
                "total_cents": chosen.item_price_cents,
            }
            for entry in entries
        }
        valid_until = _parse(winner.revision.structured.get("valid_until"))
        if valid_until is None:
            raise ApplicationError("INTEGRITY_ERROR")
        moq = max(int(lot.min_seats), 1)
        award = self._write_award(
            session,
            lot=lot,
            revision_id=winner.revision.id,
            merchant_id=winner.merchant.id,
            tier_index=chosen.tier_index,
            item_cents=chosen.item_price_cents,
            moq=moq,
            totals=totals,
            valid_until=valid_until,
        )

        # N8: the router and the mode are stamped here and never change afterwards. A
        # SIMULATION pool always uses the fake router, whatever the deployment says (I12).
        router = "fake" if str(pool.mode) == "SIMULATION" else self.payment_router
        lot.payment_router = PaymentRouter(router)
        lot.payment_mode = PaymentMode(self.payment_mode)
        lot.award_id = award.id

        priced_out = 0
        for entry in entries:
            if entry.seated and entry.cap_cents < chosen.item_price_cents:
                # SEATED to PRICED_OUT is legal only inside lot.award, and each such
                # release is a vacancy the same refill rule then fills (N12).
                await session.execute(
                    text(
                        "UPDATE allocations SET status = 'PRICED_OUT'::allocation_status, "
                        "lot_id = NULL WHERE pool_id = :pool AND entry_id = :entry"
                    ),
                    {"pool": pool.id, "entry": entry.entry_id},
                )
                priced_out += 1

        await self._lot_transition(
            session,
            lot=lot,
            to_status="AWARDED",
            trigger="job:lot.award",
            payload={
                "transition_id": "LS-03",
                "award_hash": award.award_hash,
                "bid_id": str(winner.bid.id),
                "bid_revision_id": str(winner.revision.id),
                "merchant_id": str(winner.merchant.id),
                "tier_index": chosen.tier_index,
                "item_cents": chosen.item_price_cents,
                "moq": moq,
                "priced_out": priced_out,
                "payment_router": router,
                "payment_mode": self.payment_mode,
            },
        )
        await self.jobs.enqueue(
            session,
            "lot.open_checkout",
            {"lot_id": str(lot.id)},
            run_at=now,
            concurrency_key=f"lot:{lot.id}",
        )
        await self.notifier.notify(
            session,
            user_id=winner.merchant.user_id,
            kind="lot.awarded",
            payload={"lot_id": str(lot.id), "award_hash": award.award_hash},
        )

    # ------------------------------------------------------------------ reading

    async def _lock_lot(self, session: AsyncSession, lot_id: UUID) -> Lot:
        """The per-lot advisory lock, then the lot row (AGENTS.md section 4, I8)."""
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lot_advisory_key(lot_id)}
        )
        lot = await session.scalar(select(Lot).where(Lot.id == lot_id).with_for_update())
        if lot is None:
            raise ApplicationError("NOT_FOUND")
        return lot

    async def _lock_pool(self, session: AsyncSession, pool_id: UUID) -> Pool:
        """Pool row after the lot row.

        ``pool.allocate`` takes the pool row and then writes lots, and no checkout
        handler takes a lot lock before a pool row, so this order cannot cycle.
        """
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        return pool

    async def _lower_lot_undecided(self, session: AsyncSession, *, pool_id: UUID, lot: Lot) -> bool:
        """True while any lower ``lot_order`` lot has not advanced past BID_CLOSED."""
        found = await session.scalar(
            select(Lot.id)
            .where(
                Lot.pool_id == pool_id,
                Lot.lot_order < lot.lot_order,
                Lot.status.in_([LotStatus(state) for state in sorted(_UNDECIDED_LOT_STATES)]),
            )
            .limit(1)
        )
        return found is not None

    async def _bids(self, session: AsyncSession, *, lot_id: UUID) -> list[_BidRow]:
        """Every bid on the lot with its current revision, merchant and blocking flags."""
        rows = (
            await session.execute(
                select(Bid, BidRevision, Merchant)
                .join(
                    BidRevision,
                    (BidRevision.bid_id == Bid.id) & (BidRevision.revision == Bid.current_revision),
                )
                .join(Merchant, Merchant.id == Bid.merchant_id)
                .where(Bid.lot_id == lot_id)
                .order_by(Bid.created_at, Bid.id)
            )
        ).all()
        out: list[_BidRow] = []
        for bid, revision, merchant in rows:
            codes = await session.scalars(
                select(BidFlag.code).where(
                    BidFlag.bid_revision_id == revision.id,
                    BidFlag.severity == FlagSeverity.BLOCKING,
                )
            )
            out.append(
                _BidRow(
                    bid=bid,
                    revision=revision,
                    merchant=merchant,
                    blocking_flags=tuple(str(code) for code in codes),
                )
            )
        return out

    async def _candidates(self, session: AsyncSession, *, lot: Lot) -> list[_Entry]:
        """The lot's SEATED rows plus its zone's WAITLISTED rows the award must price."""
        rows = (
            await session.execute(
                select(Allocation.entry_id, PoolEntry.cap_cents, Allocation.status)
                .join(PoolEntry, PoolEntry.id == Allocation.entry_id)
                .where(
                    Allocation.pool_id == lot.pool_id,
                    Allocation.zone_id == lot.zone_id,
                    Allocation.status.in_([AllocationStatus.SEATED, AllocationStatus.WAITLISTED]),
                )
                .order_by(Allocation.rank, Allocation.entry_id)
            )
        ).all()
        return [
            _Entry(
                entry_id=UUID(str(entry_id)),
                cap_cents=int(cap),
                seated=str(status) == str(AllocationStatus.SEATED),
            )
            for entry_id, cap, status in rows
        ]

    async def _remaining_capacity(
        self, session: AsyncSession, *, pool_id: UUID, lot: Lot, rows: list[_BidRow]
    ) -> dict[str, int]:
        """Each bidding merchant's capacity left for this lot (R9).

        The merchant's declared ``total_capacity`` minus the seats already awarded to
        them at a lower ``lot_order`` lot. A bid that states no total is treated as
        able to supply only the one lot it bid on.
        """
        declared: dict[str, int] = {}
        for row in rows:
            # CR-11: total_capacity is required by bids.py, so there is no per-lot
            # fallback left to fall through to.
            declared[str(row.merchant.id)] = int(row.revision.structured["total_capacity"])
        used_rows = (
            await session.execute(
                select(Award.merchant_id, func.sum(Lot.seats))
                .join(Lot, Lot.id == Award.lot_id)
                .where(Lot.pool_id == pool_id, Lot.lot_order < lot.lot_order)
                .group_by(Award.merchant_id)
            )
        ).all()
        used = {str(merchant_id): int(seats or 0) for merchant_id, seats in used_rows}
        return {
            merchant_id: total - used.get(merchant_id, 0) for merchant_id, total in declared.items()
        }

    # ------------------------------------------------------------------- facts

    def _lot_facts(self, *, pool: Pool, lot: Lot, now: datetime) -> LotFacts:
        """The lot's published requirements, as the pure rules want them.

        ``fund_deadline_at`` is set when checkout opens, which this award triggers in
        the same second, so the prospective deadline ``now + fund_deadline_s`` is the
        one R6 must measure against -- the same horizon the lot will actually get.
        """
        template = pool.template
        timeline = pool.timeline
        return LotFacts(
            lot_id=str(lot.id),
            lot_order=int(lot.lot_order),
            # R8's minimum is the lot's: the award snapshot funds against min_seats, the
            # same figure the ops force-award path and the LS-06 guard already use.
            moq=max(int(lot.min_seats), 1),
            seats=int(lot.seats),
            product_key=str(template.get("product_key") or ""),
            condition=str(template.get("condition") or ""),
            bundle_key=_bundle_key(template.get("bundle_contents")),
            max_delivery_days=int(template.get("delivery_sla_days") or 0),
            min_returns_days=int(template.get("min_return_days") or 0),
            fund_deadline_at=_iso(
                now + timedelta(seconds=int(timeline.get("fund_deadline_s", 600)))
            ),
            capture_grace_s=int(timeline.get("capture_grace_s", 120)),
        )

    def _bid_facts(self, *, row: _BidRow, lot: Lot) -> BidFacts:
        """One revision, normalised for deterministic validation."""
        structured = row.revision.structured
        try:
            validate_structured(structured, flat_delivered=self.flat_delivered)
            schema_ok = True
        except ApplicationError:
            schema_ok = False
        raw_tax = structured.get("tax")
        tax: dict[str, Any] = raw_tax if isinstance(raw_tax, dict) else {}
        raw_shipping = structured.get("shipping_cents_by_zone")
        shipping = (
            {str(zone): int(value) for zone, value in raw_shipping.items()}
            if isinstance(raw_shipping, dict)
            else {}
        )
        raw_capacity = structured.get("capacity")
        capacity = (
            int(raw_capacity)
            if isinstance(raw_capacity, int) and not isinstance(raw_capacity, bool)
            else None
        )
        valid_until = _parse(structured.get("valid_until"))
        return BidFacts(
            bid_id=str(row.bid.id),
            merchant_id=str(row.merchant.id),
            # A revision whose shape, timestamps or tier prices do not parse fails R1 in
            # the evaluator rather than raising inside it: a merchant submission is
            # untrusted input (AGENTS.md section 8).
            schema_ok=schema_ok and valid_until is not None,
            confirmed=row.revision.confirmed_at is not None,
            submitted_at=_iso(row.revision.created_at),
            bid_close_at=_iso(lot.bid_close_at),
            product_key=str(structured.get("product_key") or ""),
            condition=str(structured.get("condition") or ""),
            bundle_key=_bundle_key(structured.get("bundle_contents")),
            tiers=self._tiers(structured) if schema_ok else (),
            capacity=capacity,
            tax_mode=str(tax.get("mode") or ""),
            shipping_cents_by_zone=shipping,
            delivery_days=_int_at(structured, ("delivery", "sla_days")),
            returns_days=_int_at(structured, ("returns", "days")),
            validity_end=_iso(valid_until) if valid_until is not None else "",
            blocking_flags=row.blocking_flags,
        )

    @staticmethod
    def _tiers(structured: dict[str, Any]) -> tuple[Tier, ...]:
        """The tier list the ranking engine needs, only from a revision that passed shape."""
        tiers: list[Tier] = []
        for tier in structured.get("tiers") or []:
            if not isinstance(tier, dict):
                continue
            minimum = tier.get("min_qty")
            price = tier.get("item_price_cents")
            if isinstance(minimum, int) and isinstance(price, int):
                tiers.append(Tier(min_qty=minimum, item_price_cents=price))
        return tuple(tiers)

    # ------------------------------------------------------------------ writing

    async def _lot_transition(
        self,
        session: AsyncSession,
        *,
        lot: Lot,
        to_status: str,
        trigger: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """One whitelisted lot move with its audit row (I10)."""
        transition = assert_transition("lot", str(lot.status), to_status, trigger=trigger)
        before = str(lot.status)
        lot.status = LotStatus(to_status)
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action=f"lot.{to_status.lower()}",
            subject_type="lot",
            subject_id=str(lot.id),
            payload={
                "pool_id": str(lot.pool_id),
                "from": before,
                "to": to_status,
                "trigger": trigger,
                "transition_id": transition.id,
                **(payload or {}),
            },
        )

    async def _pool_to_running(self, session: AsyncSession, pool: Pool) -> None:
        """PS-06: the pool runs from the moment its first lot enters BIDDING."""
        transition = assert_transition(
            "pool", str(pool.status), "RUNNING", trigger="job:lot.bid_open"
        )
        before = str(pool.status)
        pool.status = PoolStatus.RUNNING
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action="pool.running",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={"from": before, "to": "RUNNING", "transition_id": transition.id},
        )

    async def _move(self, session: AsyncSession, *, row: _BidRow, to_status: str) -> None:
        """One bid move driven by ``job:lot.award`` (BS-07, BS-08, BS-09)."""
        await apply_bid_transition(
            session,
            bid=row.bid,
            to_status=to_status,
            trigger="job:lot.award",
            audit=self.audit,
            actor="worker",
        )
        if to_status == "LOST":
            # F6 / CR-11 audit follow-up: state-machines.md declares ``notify`` on
            # BS-09, and the award used to issue none, so a merchant learned they lost
            # only by polling their bid. BS-08's declared notify is the ``lot.awarded``
            # notice the winner already receives in the same award.
            await self.notifier.notify(
                session,
                user_id=row.merchant.user_id,
                kind="bid.lost",
                payload={"lot_id": str(row.bid.lot_id), "bid_id": str(row.bid.id)},
            )

    async def _reject(self, session: AsyncSession, *, row: _BidRow, reason: str) -> None:
        """BS-06, BS-10 or BS-11: the first failed rule is the one recorded."""
        if str(row.bid.status) not in _REJECTABLE_STATES:
            raise ApplicationError("INTEGRITY_ERROR")
        row.bid.reject_reason = reason
        await apply_bid_transition(
            session,
            bid=row.bid,
            to_status="REJECTED",
            trigger="job:lot.award",
            audit=self.audit,
            actor="worker",
            payload={"reject_reason": reason},
        )
        await self.notifier.notify(
            session,
            user_id=row.merchant.user_id,
            kind="bid.rejected",
            payload={
                "lot_id": str(row.bid.lot_id),
                "bid_id": str(row.bid.id),
                "reason": merchant_reject_copy(reason),
            },
        )

    async def _cancel(
        self,
        session: AsyncSession,
        *,
        lot: Lot,
        rows: list[_BidRow],
        why: str,
    ) -> None:
        """LS-04: no feasible bid and no money exists, so the lot is cancelled.

        Every bid that got this far has already been REJECTED by BS-06 with its own rule
        code, so the lot-level reason belongs in the audit payload and nowhere else.
        """
        await self._lot_transition(
            session,
            lot=lot,
            to_status="CANCELLED",
            trigger="job:lot.award",
            payload={"transition_id": "LS-04", "reason": why},
        )
        for row in rows:
            await self.notifier.notify(
                session,
                user_id=row.merchant.user_id,
                kind="lot.cancelled",
                payload={"lot_id": str(lot.id), "reason": why},
            )
        # F6: LS-04 also belongs to the buyers. They were told they held a seat, and
        # until now only the merchants heard that the lot produced no feasible bid --
        # a seated buyer's silence reads as "still waiting". ops.py's abort path
        # (_notify_seated) already tells buyers; this is the same notice from the award
        # path. The SQL is inlined because check_imports rule 5 forbids importing the
        # checkout lane from here, not because the query differs.
        seated = (
            (
                await session.execute(
                    text(
                        "SELECT DISTINCT pe.user_id FROM allocations a "
                        "JOIN pool_entries pe ON pe.id = a.entry_id "
                        "WHERE a.lot_id = :lot AND a.status = 'SEATED'"
                    ),
                    {"lot": lot.id},
                )
            )
            .scalars()
            .all()
        )
        for user_id in seated:
            await self.notifier.notify(
                session,
                user_id=user_id,
                kind="lot.cancelled",
                payload={"lot_id": str(lot.id), "pool_id": str(lot.pool_id)},
            )

    def _write_award(
        self,
        session: AsyncSession,
        *,
        lot: Lot,
        revision_id: UUID,
        merchant_id: UUID,
        tier_index: int,
        item_cents: int,
        moq: int,
        totals: dict[str, dict[str, int]],
        valid_until: datetime,
    ) -> Award:
        """The immutable snapshot ``fairness-and-hashing.md`` section 7 hashes."""
        document = {
            "v": 1,
            "lot_id": str(lot.id),
            "bid_revision_id": str(revision_id),
            "merchant_id": str(merchant_id),
            "tier_index": tier_index,
            "item_cents": item_cents,
            "moq": moq,
            "totals": totals,
            "valid_until": _iso(valid_until),
            "rule_version": "ranking_v1",
        }
        award = Award(
            id=uuid4(),
            lot_id=lot.id,
            bid_revision_id=revision_id,
            merchant_id=merchant_id,
            tier_index=tier_index,
            item_cents=item_cents,
            moq=moq,
            totals=totals,
            valid_until=valid_until,
            rule_version="ranking_v1",
            award_hash=hashing.award_hash(document),
        )
        session.add(award)
        return award

    # -------------------------------------------------------------------- jobs

    async def _lot_job(
        self, session: AsyncSession, kind: str, lot_id: UUID, *, run_at: datetime
    ) -> None:
        """A timer for the same lot: the job row is the timer, never an in-memory one."""
        await self.jobs.enqueue(
            session,
            kind,
            {"lot_id": str(lot_id)},
            run_at=run_at,
            concurrency_key=f"lot:{lot_id}",
        )

    async def _award_job(
        self, session: AsyncSession, *, pool_id: UUID, lot_id: UUID, delay_s: int = 0
    ) -> None:
        """``lot.award`` serialised across the pool on ``award:{pool_id}``."""
        run_at = await self.clock.db_now(session)
        if delay_s:
            run_at = run_at + timedelta(seconds=delay_s)
        await self.jobs.enqueue(
            session,
            "lot.award",
            {"lot_id": str(lot_id)},
            run_at=run_at,
            concurrency_key=f"award:{pool_id}",
        )


def _int_at(mapping: Any, path: tuple[str, ...]) -> int:
    """A non-negative integer buried in untrusted JSON, or 0 when it is not one."""
    node: Any = mapping
    for key in path:
        if not isinstance(node, dict):
            return 0
        node = node.get(key)
    return node if isinstance(node, int) and not isinstance(node, bool) and node >= 0 else 0
