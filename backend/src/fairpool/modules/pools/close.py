"""``pool.close``: the eligibility sweep and the immutable commitment snapshot (T03B04).

Contract: ``state-machines.md`` PS-02, PS-03, ES-01, ES-02 and CR-3 notes 1 and 2,
``fairness-and-hashing.md`` sections 3 and 8, ``domain-ports.md`` section 5,
``vault-charge.md`` section 4 (CR-3 note 3).

What this handler does, in the locked order the contract fixes:

* takes the pool row ``FOR UPDATE``, then reads ``Clock.db_wall_now`` and re-checks
  the status and the deadline with that wall-clock value (CR-3 note 1: ``now()`` is
  fixed at transaction start, so a job that waited on the lock across ``close_at``
  must not act on the stale time);
* a pool that is still ``PUBLISHED`` when the deadline has passed catches up
  through PS-02 then PS-03, in that order, inside this same transaction: never a
  direct status write (I10). A late join is impossible regardless, because the
  ``pool_entries`` insert trigger refuses a row at or after ``close_at``, and the
  pool lock held here serialises the sweep against ``buyer.withdraw``;
* every ``SUBMITTED`` entry is swept through ES-01 or ES-02 with the whitelist's
  own guards: the stored canonical request must still satisfy the frozen rules, the
  account link must still be active when the pool requires it, and under
  ``PAYMENT_MODE=vault_charge`` a recorded consent plus an ``ACTIVE`` permission is
  required, else the rejection stores ``VAULT_MISSING``. Withdrawn entries stay
  withdrawn;
* commitments come from ``entry_receipts`` for ELIGIBLE entries only, sorted
  ascending as hex strings, and hashed with ``domain/hashing`` (leaf ``0x00``,
  parent ``0x01``, an odd node promoted unchanged, the empty root for no entries).
  A missing receipt, or a stored hash that no longer matches these bytes, is
  ``INTEGRITY_ERROR``: never a silent omission, never an invented commitment;
* ``entries_root``, ``entries_count``, the close time, the audit checkpoint and the
  ``pool.seed`` enqueue all land in this one transaction (I10, I11: the list is
  published before any seed exists);
* a replay of ``pool.close`` on an already-closed pool returns the stored snapshot
  and repeats no audit row, notification or job (I15, I9).

No provider call happens here: eligibility reads the vault rows that the vault
service already persisted, so the pool lock is never held across network I/O.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import EntryReceipt, Pool, PoolEntry
from fairpool.db.models.enums import EntryStatus, PoolStatus
from fairpool.db.models.identity import PayPalLink
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import commitment as commitment_hash
from fairpool.domain.hashing import merkle_root
from fairpool.domain.hashing import request_hash as canonical_request_hash
from fairpool.domain.request_rules import revalidate_canonical
from fairpool.domain.states import assert_transition
from fairpool.modules.pools.vault import has_active_permission
from fairpool.ports import AuditLog, Clock, JobQueue, Notifier

#: ``pool_entries.reject_reason`` values for this handler (config-and-errors.md §5
#: plus CR-3 note 3).
REJECT_LINK_INACTIVE = "LINK_INACTIVE"
REJECT_REQUEST_INVALID = "REQUEST_INVALID"
REJECT_VAULT_MISSING = "VAULT_MISSING"

#: Statuses from PS-03 onwards: the close snapshot exists and is immutable.
_CLOSED_OR_LATER = (
    "CLOSED",
    "SEEDED",
    "ALLOCATED",
    "RUNNING",
    "COMPLETED",
    "CANCELLED",
)

#: The only reason codes this sweep may store; anything else is a bug, not data.
_REJECT_REASONS = frozenset({REJECT_LINK_INACTIVE, REJECT_REQUEST_INVALID, REJECT_VAULT_MISSING})


def _parse_iso(value: object) -> datetime:
    if not isinstance(value, str):
        raise ApplicationError("INTERNAL_ERROR")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class PoolCloseService:
    def __init__(
        self,
        clock: Clock,
        audit: AuditLog,
        jobs: JobQueue,
        notifier: Notifier,
        *,
        payment_mode: str,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.jobs = jobs
        self.notifier = notifier
        self.payment_mode = payment_mode

    async def close(self, session: AsyncSession, payload: dict[str, Any]) -> None:
        """Job handler for ``pool.close`` (payload carries ids only)."""
        pool_id = UUID(str(payload["pool_id"]))
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if pool is None:
            raise ApplicationError("NOT_FOUND")

        # CR-3 note 1: the wall clock after the lock, never the transaction-start now().
        wall_now = await self.clock.db_wall_now(session)
        status = str(pool.status)
        if status in _CLOSED_OR_LATER:
            # I15: the snapshot is already written; a replay changes and emits nothing.
            return
        close_at = _parse_iso(pool.timeline.get("close_at"))
        if wall_now < close_at:
            # PS-03's guard is now >= close_at. Closing early would be a direct
            # status write, so the job simply does nothing and the deadline re-runs it.
            return
        if status == str(PoolStatus.DRAFT):
            # Never published: there is no entry window to close.
            return

        if status == str(PoolStatus.PUBLISHED):
            # CR-3 note 2: catch up through the whitelist, PS-02 first.
            open_at = _parse_iso(pool.timeline.get("open_at"))
            if wall_now < open_at:
                raise ApplicationError("ORDER_STATE_INVALID")
            await self._transition(session, pool, "OPEN", "job:pool.open")

        # PS-03 with its effects (audit plus the pool.seed enqueue) in this transaction.
        await self._transition(session, pool, "CLOSED", "job:pool.close")

        commitments, counts = await self._sweep(session, pool)
        ordered = sorted(commitments)
        # fairness-and-hashing.md §3: the existing Merkle implementation over the
        # ascending list; the empty list gives the empty root.
        root = merkle_root(ordered)
        pool.entries_root = root
        pool.entries_count = len(ordered)
        pool.closed_at = wall_now
        await session.flush()
        # The checkpoint row (fairness §8): the public audit surface publishes the
        # chain hash of this row as the close-time checkpoint.
        await self.audit.append(
            session,
            actor="worker",
            action="pool.close.snapshot",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={
                "entries_root": root,
                "entries_count": len(ordered),
                "eligible": counts["eligible"],
                "rejected": counts["rejected"],
                "withdrawn": counts["withdrawn"],
                "rules_hash": pool.rules_hash,
            },
        )

    # ------------------------------------------------------------- transitions

    async def _transition(
        self, session: AsyncSession, pool: Pool, to_status: str, trigger: str
    ) -> None:
        # I10: the whitelist decides; this handler never writes a status directly.
        assert_transition("pool", str(pool.status), to_status, trigger=trigger)
        before = str(pool.status)
        pool.status = PoolStatus(to_status)
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action=f"pool.{to_status.lower()}",
            subject_type="pool",
            subject_id=str(pool.id),
            payload={"from": before, "to": to_status, "rules_hash": pool.rules_hash},
        )
        if to_status == "CLOSED":
            # PS-03's second effect, in the same transaction as the transition.
            # domain-ports.md section 5 gives pool.seed no dedupe key: one close enqueues
            # exactly one seed, and the pool concurrency key is what keeps two seeds for
            # one pool from running together. A dedupe key here would silently drop a
            # second close-time seed the contract says must be enqueued.
            run_at = await self.clock.db_now(session)
            await self.jobs.enqueue(
                session,
                "pool.seed",
                {"pool_id": str(pool.id)},
                run_at=run_at,
                concurrency_key=f"pool:{pool.id}",
            )

    # -------------------------------------------------------------- the sweep

    async def _sweep(self, session: AsyncSession, pool: Pool) -> tuple[list[str], dict[str, int]]:
        """Move every SUBMITTED entry through ES-01 or ES-02 and collect commitments."""
        template = {**pool.template, "pool_id": str(pool.id)}
        entries = (
            (
                await session.execute(
                    select(PoolEntry)
                    .where(PoolEntry.pool_id == pool.id, PoolEntry.status == EntryStatus.SUBMITTED)
                    .order_by(PoolEntry.id)
                )
            )
            .scalars()
            .all()
        )

        commitments: list[str] = []
        eligible = 0
        rejected = 0
        for entry in entries:
            reason = await self._reject_reason(session, pool=pool, entry=entry, template=template)
            if reason is None:
                await self._decide(session, entry, EntryStatus.ELIGIBLE, None)
                commitments.append(await self._commitment(session, pool=pool, entry=entry))
                eligible += 1
                continue
            await self._decide(session, entry, EntryStatus.REJECTED, reason)
            rejected += 1

        # Withdrawn entries are not in the sweep at all: ES-01 and ES-02 both start
        # at SUBMITTED, so a withdrawn entry stays withdrawn and gets no commitment.
        withdrawn = int(
            await session.scalar(
                select(func.count())
                .select_from(PoolEntry)
                .where(PoolEntry.pool_id == pool.id, PoolEntry.status == EntryStatus.WITHDRAWN)
            )
            or 0
        )
        return commitments, {"eligible": eligible, "rejected": rejected, "withdrawn": withdrawn}

    async def _reject_reason(
        self,
        session: AsyncSession,
        *,
        pool: Pool,
        entry: PoolEntry,
        template: dict[str, Any],
    ) -> str | None:
        """The first failing ES-01 guard, or ``None`` when the entry is eligible."""
        # INTEGRITY_ERROR first: a stored record whose bytes no longer match their
        # hash is an auditability break, never a user rejection (config-and-errors §5).
        if str(entry.request_hash) != canonical_request_hash(entry.canonical_request):
            raise ApplicationError("INTEGRITY_ERROR")

        if pool.require_paypal_link and not await self._link_active(session, entry):
            return REJECT_LINK_INACTIVE

        try:
            revalidate_canonical(template, entry.canonical_request, str(entry.request_hash))
        except ApplicationError as exc:
            if exc.code == "INTEGRITY_ERROR":
                # The bytes still hash to their stored digest (checked above), so
                # this is the frozen rules no longer admitting the request: the
                # ES-02 guard "request still valid" failed.
                return REJECT_REQUEST_INVALID
            raise
        if self.payment_mode == "vault_charge" and not await has_active_permission(
            session, entry_id=entry.id, cap_cents=entry.cap_cents
        ):
            # CR-3 note 3 / DEP-5: without consent plus an ACTIVE permission the
            # entry cannot be charged, so it is never presented as eligible.
            return REJECT_VAULT_MISSING
        return None

    async def _link_active(self, session: AsyncSession, entry: PoolEntry) -> bool:
        key = await session.scalar(
            select(PayPalLink.paypal_account_key).where(
                PayPalLink.user_id == entry.user_id, PayPalLink.revoked_at.is_(None)
            )
        )
        if key is None:
            return False
        if entry.paypal_account_key is not None and str(key) != str(entry.paypal_account_key):
            # The account the entry was made with is no longer this buyer's link.
            return False
        return True

    async def _decide(
        self,
        session: AsyncSession,
        entry: PoolEntry,
        to_status: EntryStatus,
        reason: str | None,
    ) -> None:
        if reason is not None and reason not in _REJECT_REASONS:
            raise ApplicationError("INTERNAL_ERROR")
        # ES-01 and ES-02 belong to this job's trigger and start at SUBMITTED.
        assert_transition("entry", str(entry.status), str(to_status), trigger="job:pool.close")
        before = str(entry.status)
        entry.status = to_status
        if reason is not None:
            entry.reject_reason = reason
        await session.flush()
        await self.audit.append(
            session,
            actor="worker",
            action=f"entry.{str(to_status).lower()}",
            subject_type="pool_entry",
            subject_id=str(entry.id),
            payload={
                "pool_id": str(entry.pool_id),
                "from": before,
                "to": str(to_status),
                **({"reject_reason": reason} if reason is not None else {}),
            },
        )
        if reason is not None:
            # ES-02's notify effect. No personal data: the buyer's own entry, pool
            # and the reason code only.
            await self.notifier.notify(
                session,
                user_id=entry.user_id,
                kind="entry.rejected",
                payload={
                    "pool_id": str(entry.pool_id),
                    "entry_id": str(entry.id),
                    "reason": reason,
                },
            )

    async def _commitment(self, session: AsyncSession, *, pool: Pool, entry: PoolEntry) -> str:
        """The receipt's commitment, recomputed and compared (never invented)."""
        receipt = await session.scalar(
            select(EntryReceipt).where(EntryReceipt.entry_id == entry.id)
        )
        if receipt is None:
            raise ApplicationError("INTEGRITY_ERROR")
        digest = commitment_hash(
            str(pool.id), str(entry.id), str(entry.request_hash), str(receipt.salt)
        )
        if digest != str(receipt.commitment):
            raise ApplicationError("INTEGRITY_ERROR")
        return digest
