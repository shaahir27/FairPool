"""Pool join, entry creation and withdrawal (api.md "Entry", CR-3).

Every rule here is contract text, not preference:

* the confirmed request is fetched by id **and owner** (another buyer's id is
  ``404``, identical to an unknown id, so no existence information leaks);
* its frozen ``rules_hash`` must equal the pool's or the call is
  ``409 RULES_MISMATCH``; the stored canonical bytes are re-validated by the
  deterministic validator (``INTEGRITY_ERROR`` on a break);
* the pool row is locked and the database **wall clock** is read after the
  lock; admission is strictly before ``close_at`` (CR-3, I15) while receipts,
  audit rows and canonical records keep the stable transaction timestamp;
* entry, salt, commitment, Ed25519 receipt, audit row and the
  ``confirmed_requests.consumed_*`` update happen in one transaction, signed
  over the stored database timestamp;
* a consumed confirmation replays to the entry it created, even after the
  cutoff, and never reactivates a withdrawn entry or rewrites a cap;
* the ``(pool_id, user_id)`` and ``(pool_id, paypal_account_key)`` constraints
  are the last word on one entry: a swallowed duplicate-key violation is
  mapped to the winning entry's stored response through a savepoint;
* withdrawal is owner-only, ES-03 only, and serialises against ``pool.close``
  under the same pool lock.

Everything runs inside the caller's transaction; the planned error paths roll
back their savepoint so a rejected request never burns an idempotency key.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import ConfirmedRequest, EntryReceipt, Pool, PoolEntry
from fairpool.db.models.enums import EntryStatus, PoolMode, PoolStatus, SubmittedVia
from fairpool.db.models.identity import PayPalLink
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import commitment as commitment_hash
from fairpool.domain.hashing import request_hash as canonical_request_hash
from fairpool.domain.hashing import sha256_hex
from fairpool.domain.request_rules import revalidate_canonical
from fairpool.domain.states import assert_transition
from fairpool.modules.pools.receipts import build_receipt, receipt_for_entry
from fairpool.ports import AuditLog, Clock, IdemNew, IdempotencyStore, IdemReplay

_JOIN_SCOPE = "entries_join"

# The only two constraint names a join may swallow (config-and-errors.md §3).
_ENTRY_CONSTRAINTS = frozenset({"uq_pool_entries_pool_user", "uq_pool_entries_pool_account"})


def _is_duplicate_entry_constraint(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    name = getattr(orig, "constraint_name", None)
    if name is None:
        # asyncpg on this platform exposes only the message text.
        import re

        match = re.search(r'unique constraint "([^"]+)"', str(orig))
        name = match.group(1) if match else ""
    return name in _ENTRY_CONSTRAINTS


@dataclass(frozen=True)
class JoinOutcome:
    """The response to return: body plus the HTTP status api.md fixes (201/200)."""

    status_code: int
    body: dict[str, Any]


def _parse_iso(value: object) -> datetime:
    if not isinstance(value, str):
        raise ApplicationError("INTERNAL_ERROR")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class JoinService:
    def __init__(
        self,
        clock: Clock,
        audit: AuditLog,
        idempotency: IdempotencyStore,
        *,
        signing_seed: bytes,
        dedupe_mode: str,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.idempotency = idempotency
        self.signing_seed = signing_seed
        self.dedupe_mode = dedupe_mode

    # ------------------------------------------------------------------ join

    async def join(
        self,
        session: AsyncSession,
        *,
        pool_id: UUID,
        user_id: UUID,
        confirmed_request_id: UUID,
        idempotency_key: str,
        delegation_id: UUID | None = None,
    ) -> JoinOutcome:
        """Join a pool in one savepoint: a planned error rolls the savepoint
        back (nothing is written, no idempotency key is burned) and raises
        ``ApplicationError`` with the contract code (config-and-errors.md §4).

        ``delegation_id`` is the identity path of the agent lane (F15, I6): the entry
        is recorded as agent-submitted and bound to that ``delegations`` row. The
        ``/agent/v1`` HTTP lane of Phase 7 is what authenticates the token and enforces
        its scope and cap; here the service only refuses a delegation that is not this
        user's own, so one buyer's agent can never act as another's.
        """
        async with session.begin_nested():
            if delegation_id is not None:
                owned = await session.scalar(
                    text("SELECT id FROM delegations WHERE id = :id AND user_id = :user"),
                    {"id": delegation_id, "user": user_id},
                )
                if owned is None:
                    # api.md "Agent": a delegation that is not this principal's own is
                    # not a delegation at all for this call.
                    raise ApplicationError("DELEGATION_INVALID")
            return await self._join_inner(
                session,
                pool_id=pool_id,
                user_id=user_id,
                confirmed_request_id=confirmed_request_id,
                idempotency_key=idempotency_key,
                delegation_id=delegation_id,
            )

    async def _join_inner(
        self,
        session: AsyncSession,
        *,
        pool_id: UUID,
        user_id: UUID,
        confirmed_request_id: UUID,
        idempotency_key: str,
        delegation_id: UUID | None = None,
    ) -> JoinOutcome:
        # Owner-only fetch: another buyer's id and an unknown id answer alike (404).
        cr = await session.scalar(
            select(ConfirmedRequest).where(
                ConfirmedRequest.id == confirmed_request_id,
                ConfirmedRequest.user_id == user_id,
            )
        )
        if cr is None:
            raise ApplicationError("NOT_FOUND")
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id))
        if pool is None:
            raise ApplicationError("NOT_FOUND")

        # The request froze against one rules document; it must be this pool's.
        if pool.rules_hash is None or cr.rules_hash != pool.rules_hash:
            raise ApplicationError("RULES_MISMATCH")
        template = {**pool.template, "pool_id": str(pool.id)}
        revalidate_canonical(template, cr.canonical_request, cr.request_hash)
        if cr.request_hash != canonical_request_hash(cr.canonical_request):
            raise ApplicationError("INTEGRITY_ERROR")
        if cr.cap_cents != cr.canonical_request.get("max_total_cents"):
            # The cap a receipt was issued over must never move (CR-3).
            raise ApplicationError("INTEGRITY_ERROR")

        key = self._idem_key(idempotency_key, pool_id, user_id)
        idem = await self.idempotency.begin(
            session,
            key=key,
            scope=f"{_JOIN_SCOPE}:{pool_id}",
            request_hash=sha256_hex(f"confirmed_request:{confirmed_request_id}"),
        )
        if isinstance(idem, IdemReplay):
            stored = idem.response
            return JoinOutcome(status_code=int(stored["status_code"]), body=dict(stored["body"]))
        if not isinstance(idem, IdemNew):
            # IdemConflict covers a different body and an in-flight key whose
            # response is not yet written (CR-3); a retry is safe by contract.
            raise ApplicationError("IDEMPOTENCY_CONFLICT")

        # api.md "Account link": link, unlink and join serialise user-then-pool.
        await session.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id}
        )
        locked_pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
        if locked_pool is None:  # pragma: no cover - the pool exists under a FK
            raise ApplicationError("NOT_FOUND")
        # Re-read the request under the locks: a concurrent join of the same
        # request serialises here and its consumption becomes visible.
        locked_cr = await session.scalar(
            select(ConfirmedRequest)
            .where(ConfirmedRequest.id == confirmed_request_id)
            .with_for_update()
        )
        if locked_cr is None:
            raise ApplicationError("INTEGRITY_ERROR")

        # CR-3: the cutoff is decided on the wall clock read AFTER the lock.
        wall_now = await self.clock.db_wall_now(session)

        # A consumed confirmation replays to the entry it created, including
        # after the cutoff, and never creates, reactivates or rewrites anything.
        if locked_cr.consumed_by_entry_id is not None:
            entry = await session.scalar(
                select(PoolEntry).where(PoolEntry.id == locked_cr.consumed_by_entry_id)
            )
            if entry is None:
                raise ApplicationError("INTEGRITY_ERROR")
            outcome = await self._entry_outcome(session, entry, already_entered=True)
            await self.idempotency.complete(
                session,
                key=key,
                response={"status_code": outcome.status_code, "body": outcome.body},
            )
            return outcome

        if locked_pool.status != PoolStatus.OPEN:
            raise ApplicationError("POOL_NOT_OPEN")
        if wall_now >= _parse_iso(locked_pool.timeline.get("close_at")):
            raise ApplicationError("POOL_CLOSED")

        account_key = await self._account_key(session, user_id=user_id, pool=locked_pool)
        entry_id = uuid4()
        salt_hex = secrets.token_hex(32)  # 32 random bytes as 64 hex characters (§2)
        received_at = await self.clock.db_now(session)
        digest = commitment_hash(str(pool_id), str(entry_id), str(cr.request_hash), salt_hex)
        _, receipt = build_receipt(
            self.signing_seed,
            pool_id=str(pool_id),
            entry_id=str(entry_id),
            commitment=digest,
            salt_hex=salt_hex,
            request_hash=str(cr.request_hash),
            received_at=received_at,
        )
        entry = PoolEntry(
            id=entry_id,
            pool_id=pool_id,
            user_id=user_id,
            paypal_account_key=account_key,
            canonical_request=cr.canonical_request,
            request_hash=cr.request_hash,
            cap_cents=cr.cap_cents,
            zone_id=cr.zone_id,
            status=EntryStatus.SUBMITTED,
            # F15: the delegation-backed identity is recorded, not inferred later.
            submitted_via=SubmittedVia.agent if delegation_id else SubmittedVia.human,
            delegation_id=delegation_id,
            received_at=received_at,
            # I12: synthetic is derived from the pool mode, never taken from a client.
            synthetic=locked_pool.mode == PoolMode.SIMULATION,
        )
        try:
            # I7/CR-3: the unique constraints, not this code, are the last word
            # on one entry; the savepoint keeps the transaction usable and the
            # loser answers with the winning entry's stored receipt.
            async with session.begin_nested():
                session.add(entry)
                await session.flush()
                session.add(
                    EntryReceipt(
                        entry_id=entry.id,
                        commitment=digest,
                        salt=salt_hex,
                        signature=receipt["signature"],
                        signed_at=received_at,
                    )
                )
                await session.flush()
                await self.audit.append(
                    session,
                    actor=str(user_id),
                    action="entry.join",
                    subject_type="pool_entry",
                    subject_id=str(entry.id),
                    payload={
                        "pool_id": str(pool_id),
                        "request_hash": str(cr.request_hash),
                        "commitment": digest,
                        "zone_id": cr.zone_id,
                        "via": str(entry.submitted_via),
                    },
                )
        except IntegrityError as exc:
            if not _is_duplicate_entry_constraint(exc):
                # Only the two entry constraints are expected here; anything
                # else (FK, trigger, check) is a real failure, never swallowed.
                raise ApplicationError("INTERNAL_ERROR") from None
            winner = await self._winner_entry(
                session, pool_id=pool_id, user_id=user_id, account_key=account_key
            )
            outcome = await self._entry_outcome(session, winner, already_entered=True)
            await self.idempotency.complete(
                session,
                key=key,
                response={"status_code": outcome.status_code, "body": outcome.body},
            )
            return outcome

        # The two consumed_* columns are the only mutable fields; set once by
        # the join that created the entry (db-schema.md).
        consumed = await session.scalar(
            text(
                "UPDATE confirmed_requests SET consumed_at = :at, consumed_by_entry_id = :entry "
                "WHERE id = :id AND consumed_at IS NULL AND consumed_by_entry_id IS NULL "
                "RETURNING id"
            ),
            {
                "at": await self.clock.db_now(session),
                "entry": str(entry_id),
                "id": str(confirmed_request_id),
            },
        )
        if consumed is None:
            raise ApplicationError("INTEGRITY_ERROR")
        outcome = JoinOutcome(
            status_code=201,
            body={
                "entry_id": str(entry.id),
                "already_entered": False,
                "pool_status": str(locked_pool.status),
                "receipt": receipt,
            },
        )
        await self.idempotency.complete(
            session, key=key, response={"status_code": outcome.status_code, "body": outcome.body}
        )
        return outcome

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _idem_key(idempotency_key: str, pool_id: UUID, user_id: UUID) -> str:
        # The store keys globally; scope the text so one client's key cannot
        # collide with another buyer's or another pool's.
        return f"{_JOIN_SCOPE}:{pool_id}:{user_id}:{idempotency_key}"

    async def _account_key(self, session: AsyncSession, *, user_id: UUID, pool: Pool) -> str | None:
        link_required = bool(pool.require_paypal_link)
        link = await session.scalar(
            select(PayPalLink).where(PayPalLink.user_id == user_id, PayPalLink.revoked_at.is_(None))
        )
        if link_required and link is None:
            raise ApplicationError("PAYPAL_LINK_REQUIRED")
        if self.dedupe_mode == "checkout_only":
            # db-schema.md: the account key is NULL when DEDUPE_MODE=checkout_only.
            return None
        return link.paypal_account_key if link is not None else None

    async def _winner_entry(
        self, session: AsyncSession, *, pool_id: UUID, user_id: UUID, account_key: str | None
    ) -> PoolEntry:
        entry = await session.scalar(
            select(PoolEntry).where(PoolEntry.pool_id == pool_id, PoolEntry.user_id == user_id)
        )
        if entry is None and account_key is not None:
            entry = await session.scalar(
                select(PoolEntry).where(
                    PoolEntry.pool_id == pool_id,
                    PoolEntry.paypal_account_key == account_key,
                )
            )
        if entry is None:
            # The violation named a constraint we cannot now find: integrity,
            # never an invented entry.
            raise ApplicationError("INTEGRITY_ERROR")
        return entry

    async def _entry_outcome(
        self, session: AsyncSession, entry: PoolEntry, *, already_entered: bool
    ) -> JoinOutcome:
        receipt = await receipt_for_entry(session, entry)
        pool_status = await session.scalar(
            text("SELECT status FROM pools WHERE id = :id"), {"id": entry.pool_id}
        )
        return JoinOutcome(
            status_code=200,
            body={
                "entry_id": str(entry.id),
                "already_entered": already_entered,
                "pool_status": str(pool_status),
                "receipt": receipt,
            },
        )

    # ------------------------------------------------------------- withdraw

    async def withdraw(self, session: AsyncSession, *, pool_id: UUID, user_id: UUID) -> JoinOutcome:
        """ES-03: SUBMITTED to WITHDRAWN while OPEN and before ``close_at``.

        Serialises against ``pool.close`` under the same pool lock, so a close
        racing this withdrawal sees either the entry or the withdrawal.
        """
        async with session.begin_nested():
            await session.execute(
                text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id}
            )
            pool = await session.scalar(select(Pool).where(Pool.id == pool_id).with_for_update())
            if pool is None:
                raise ApplicationError("NOT_FOUND")
            entry = await session.scalar(
                select(PoolEntry).where(PoolEntry.pool_id == pool_id, PoolEntry.user_id == user_id)
            )
            if entry is None:
                raise ApplicationError("NOT_FOUND")
            if entry.status == EntryStatus.WITHDRAWN:
                # Idempotent for the client; the whitelist is not re-run.
                return JoinOutcome(
                    status_code=200,
                    body={"entry_id": str(entry.id), "entry_status": str(entry.status)},
                )
            # CR-3: the deadline guard reads the wall clock after the lock.
            wall_now = await self.clock.db_wall_now(session)
            if pool.status != PoolStatus.OPEN:
                raise ApplicationError("POOL_NOT_OPEN")
            if wall_now >= _parse_iso(pool.timeline.get("close_at")):
                raise ApplicationError("POOL_CLOSED")
            if entry.status != EntryStatus.SUBMITTED:
                # ES-03 starts at SUBMITTED only; ELIGIBLE/REJECTED cannot withdraw.
                raise ApplicationError("ORDER_STATE_INVALID")
            assert_transition("entry", str(EntryStatus.SUBMITTED), "WITHDRAWN")  # ES-03
            before = str(entry.status)
            entry.status = EntryStatus.WITHDRAWN
            await session.flush()
            await self.audit.append(
                session,
                actor=str(user_id),
                action="entry.withdraw",
                subject_type="pool_entry",
                subject_id=str(entry.id),
                payload={"pool_id": str(pool_id), "from": before, "to": "WITHDRAWN"},
            )
            return JoinOutcome(
                status_code=200,
                body={"entry_id": str(entry.id), "entry_status": str(entry.status)},
            )
