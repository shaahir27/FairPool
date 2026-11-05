"""The Agent API service: pool search, entry creation and withdrawal (T07A05).

Contract: ``api.md`` sections 1 and 4.4, ``product-spec.md`` FR-AG-01/FR-AG-02
and FR-SL-03, invariant I6 (one human, one entry) and I1/I2 (no payment surface).

The entry path is deliberately the web path: a delegation holder's request is
validated by ``ManualIntakeService.confirm`` — the same deterministic validator
the manual form and the confirmed-request join use — and the entry is written by
``JoinService.join`` with the delegation id, so one account has one entry however
many identity paths it uses (F15). Scope and cap are the only extra rules, and
they can only narrow what that validator already allows.

Idempotency has two layers and both must hold: this service records the whole
response under the caller's ``Idempotency-Key`` before anything is returned, so
a replay never confirms a second request, and ``JoinService`` keeps its own key
so a retried join cannot create a second entry.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, false, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.enums import PoolStatus
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import sha256_hex
from fairpool.modules.agentapi.views import entry_view, entry_views
from fairpool.modules.identity.delegations import AgentPrincipal
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.modules.pools.join import JoinOutcome, JoinService
from fairpool.ports import (
    AuditLog,
    Clock,
    IdemNew,
    IdempotencyStore,
    IdemReplay,
    SearchHit,
    SearchService,
)

_USD_RE = re.compile(r"^\d+(\.\d{1,2})?$")
_IDEM_SCOPE = "agent_entries"

#: The literal ``checkout_hint`` every agent entry body carries (api.md §4.4).
CHECKOUT_HINT = "A human approves payment on PayPal; this API cannot pay."


def usd_to_cents(value: str) -> int:
    """``"600.00"`` to ``60000`` with the contract regex; never a float (I3)."""
    if not _USD_RE.match(value):
        raise ApplicationError("VALIDATION_ERROR")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def cap_cents(max_total_cents: int | None, max_total_usd: str | None) -> int:
    """Exactly one of the two forms (api.md §4.4); both or neither is invalid."""
    if (max_total_cents is None) == (max_total_usd is None):
        raise ApplicationError("VALIDATION_ERROR")
    if max_total_usd is not None:
        return usd_to_cents(max_total_usd)
    assert max_total_cents is not None  # the XOR above proved it
    return max_total_cents


def _scope_conditions(principal: AgentPrincipal) -> list[ColumnElement[bool]]:
    """Every pool a delegation may see must satisfy its ``pool_ids`` and ``category``.

    The create path and the read path share these conditions, so a delegation
    cannot read or withdraw an entry its scope would refuse to create (I11).
    """
    if not principal.scope:
        # A scope with neither a pool list nor a category selected every pool, which is
        # the opposite of what a delegation is for (I11). The token is refused rather
        # than widened; a row this shape can only come from a write that bypassed
        # ``DelegationService.create``.
        raise ApplicationError("VALIDATION_ERROR")
    conditions: list[ColumnElement[bool]] = []
    allowed = [str(value) for value in principal.scope.get("pool_ids") or []]
    if allowed:
        try:
            conditions.append(Pool.id.in_([UUID(value) for value in allowed]))
        except ValueError:
            # A malformed stored id allows nothing, exactly like a revoked scope.
            conditions.append(false())
    category = principal.scope.get("category")
    if category is not None:
        conditions.append(Pool.template["category"].astext == str(category))
    return conditions


def _scoped_pool_ids(principal: AgentPrincipal) -> Select[UUID]:
    return select(Pool.id).where(*_scope_conditions(principal))


class AgentService:
    """Agent-lane orchestration over the same services the web flow uses."""

    def __init__(
        self,
        *,
        clock: Clock,
        audit: AuditLog,
        idempotency: IdempotencyStore,
        join: JoinService,
        manual: ManualIntakeService,
        frontend_base_url: str,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.idempotency = idempotency
        self.join = join
        self.manual = manual
        self.frontend_base_url = frontend_base_url

    # ------------------------------------------------------------------ pools

    async def list_pools(
        self,
        session: AsyncSession,
        *,
        q: str | None,
        limit: int,
        search: SearchService,
    ) -> list[dict[str, Any]]:
        query = select(Pool).where(Pool.status == PoolStatus.OPEN)
        hits: list[SearchHit] | None = None
        if q:
            # FR-IG-01/INT-1: retrieval only, through the same search service the
            # public list uses. An empty answer means nothing matched.
            hits = await search.search(session, q=q, kinds=["pool"], status=None, limit=limit)
            if not hits:
                return []
            query = query.where(Pool.id.in_([UUID(hit.doc_id) for hit in hits]))
        query = query.order_by(Pool.timeline["close_at"].astext, Pool.id).limit(limit)
        pools = list((await session.scalars(query)).all())
        if hits is not None:
            by_id = {pool.id: pool for pool in pools}
            pools = [by_id[UUID(hit.doc_id)] for hit in hits if UUID(hit.doc_id) in by_id]
        return [
            {
                "pool_id": pool.id,
                "title": pool.title,
                "status": str(pool.status),
                "template": pool.template,
                "timeline": pool.timeline,
                "rules_hash": pool.rules_hash,
            }
            for pool in pools
        ]

    # ----------------------------------------------------------------- entries

    async def create_entry(
        self,
        session: AsyncSession,
        *,
        principal: AgentPrincipal,
        pool_id: UUID,
        request: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[int, dict[str, Any]]:
        """Validate, confirm and join in one transaction; replay-safe by key."""
        max_cents = cap_cents(request.get("max_total_cents"), request.get("max_total_usd"))
        await self._check_scope(session, principal, pool_id)
        if max_cents > principal.max_cap_cents:
            raise ApplicationError("DELEGATION_CAP_EXCEEDED")

        key = self._idem_key(principal.user_id, idempotency_key)
        # The manual validator accepts exactly the five buyer-chosen fields; the
        # pool is a route parameter, not part of the confirmed request body.
        payload = {
            "delivery": request["delivery"],
            "required_by": request["required_by"],
            "max_total_cents": max_cents,
            "firm": list(request.get("firm", [])),
            "preferences": list(request.get("preferences", [])),
        }
        fingerprint = {"pool_id": str(pool_id), **payload}
        idem = await self.idempotency.begin(
            session,
            key=key,
            scope=_IDEM_SCOPE,
            request_hash=sha256_hex(json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))),
        )
        if isinstance(idem, IdemReplay):
            stored = idem.response
            # A replay is the original entry, answered as a read (api.md §4.1 join
            # semantics and §4.4): 200, never a second 201.
            return 200, dict(stored["body"])
        if not isinstance(idem, IdemNew):
            raise ApplicationError("IDEMPOTENCY_CONFLICT")

        record = await self.manual.confirm(
            session, user_id=principal.user_id, pool_id=pool_id, payload=payload
        )
        outcome: JoinOutcome = await self.join.join(
            session,
            pool_id=pool_id,
            user_id=principal.user_id,
            confirmed_request_id=record.id,
            idempotency_key=idempotency_key,
            delegation_id=principal.delegation_id,
        )
        body = await self._view(session, UUID(str(outcome.body["entry_id"])), principal=principal)
        body["already_entered"] = bool(outcome.body.get("already_entered", False))
        await self.idempotency.complete(
            session, key=key, response={"status_code": outcome.status_code, "body": body}
        )
        return outcome.status_code, body

    async def get_entry(
        self, session: AsyncSession, *, principal: AgentPrincipal, entry_id: UUID
    ) -> dict[str, Any]:
        return await self._view(session, entry_id, principal=principal)

    async def list_entries(
        self,
        session: AsyncSession,
        *,
        principal: AgentPrincipal,
        pool_id: UUID | None,
        entry_id: UUID | None,
    ) -> list[dict[str, Any]]:
        query = select(PoolEntry).where(
            PoolEntry.user_id == principal.user_id,
            PoolEntry.pool_id.in_(_scoped_pool_ids(principal)),
        )
        if pool_id is not None:
            query = query.where(PoolEntry.pool_id == pool_id)
        if entry_id is not None:
            query = query.where(PoolEntry.id == entry_id)
        entries = list(
            (await session.scalars(query.order_by(PoolEntry.received_at, PoolEntry.id))).all()
        )
        return await entry_views(session, entries, frontend_base_url=self.frontend_base_url)

    async def owned_entry(
        self, session: AsyncSession, *, principal: AgentPrincipal, entry_id: UUID
    ) -> PoolEntry:
        """Owner and scope scoped lookup; anything else answers like an unknown entry."""
        entry = await session.scalar(
            select(PoolEntry).where(
                PoolEntry.id == entry_id,
                PoolEntry.user_id == principal.user_id,
                PoolEntry.pool_id.in_(_scoped_pool_ids(principal)),
            )
        )
        if entry is None:
            raise ApplicationError("NOT_FOUND")
        return entry

    # ----------------------------------------------------------------- helpers

    async def _view(
        self, session: AsyncSession, entry_id: UUID, *, principal: AgentPrincipal
    ) -> dict[str, Any]:
        entry = await session.scalar(
            select(PoolEntry).where(
                PoolEntry.id == entry_id,
                PoolEntry.user_id == principal.user_id,
                PoolEntry.pool_id.in_(_scoped_pool_ids(principal)),
            )
        )
        if entry is None:
            raise ApplicationError("NOT_FOUND")
        return await entry_view(session, entry, frontend_base_url=self.frontend_base_url)

    async def _check_scope(
        self, session: AsyncSession, principal: AgentPrincipal, pool_id: UUID
    ) -> Pool:
        pool = await session.scalar(
            select(Pool).where(
                Pool.id == pool_id,
                Pool.status == PoolStatus.OPEN,
                *_scope_conditions(principal),
            )
        )
        if pool is None:
            # api.md §4.4 fixes the response for a scope violation nowhere; the
            # same answer as an unknown pool leaks no pool existence (I11).
            raise ApplicationError("NOT_FOUND")
        return pool

    @staticmethod
    def _idem_key(user_id: UUID, idempotency_key: str) -> str:
        # The store keys globally; scope the text so two buyers cannot collide.
        return f"{_IDEM_SCOPE}:{user_id}:{idempotency_key}"
