"""Buyer delegations for the Agent API (T07A05, FR-AG-01, FR-AG-02).

Contract: ``db-schema.md`` ``delegations``, ``api.md`` sections 1 and 4.4, and
``domain-ports.md`` section 2. A delegation is a bearer credential an AI client
holds on behalf of one buyer: it carries a scope (pool ids or a category), a
maximum cap and an expiry, and it can never pay (I1, I2).

The token format mirrors merchant keys: ``fpd_<8 hex>_<43 base64url>``. The
secret is shown once at creation; the row keeps only its HMAC-SHA256 under
``HMAC_KEY`` so a database read cannot reproduce a usable token (I14, rule 25).
The whole token is hashed and looked up by that hash, which keeps the check one
index probe per call; every refusal (malformed, unknown, expired, revoked) is
the same ``401 DELEGATION_INVALID`` so the difference never answers a probe
(I11).

Nothing here writes during authentication: an agent token is not a session and
has no ``last_used_at`` to stamp. ``PostgresDelegationAuth.from_token`` reads
the row, compares the database clock against ``expires_at`` (I15) and returns
the principal the route enforces scope and cap against.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.identity import Delegation
from fairpool.domain.errors import ApplicationError
from fairpool.ports import AuditLog, Clock

logger: Final[logging.Logger] = logging.getLogger("fairpool.identity.delegations")

TOKEN_PREFIX: Final[str] = "fpd"
PREFIX_CHARS: Final[int] = 8
SECRET_BYTES: Final[int] = 32


@dataclass(frozen=True)
class AgentPrincipal:
    """What an agent token resolves to: the buyer, the scope, the cap, the expiry."""

    delegation_id: UUID
    user_id: UUID
    scope: dict[str, Any]
    max_cap_cents: int
    expires_at: datetime


def hash_token(hmac_key: str, token: str) -> str:
    """HMAC-SHA256 of the full token under ``HMAC_KEY``; the token is never stored."""
    return hmac_lib.new(hmac_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def _new_token() -> str:
    prefix = secrets.token_hex(PREFIX_CHARS // 2)
    secret = secrets.token_urlsafe(SECRET_BYTES)[:43]
    return f"{TOKEN_PREFIX}_{prefix}_{secret}"


class DelegationService:
    """Create, list and revoke one buyer's delegations."""

    def __init__(self, *, clock: Clock, audit: AuditLog, hmac_key: str) -> None:
        self.clock = clock
        self.audit = audit
        self.hmac_key = hmac_key

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        scope: dict[str, Any],
        max_cap_cents: int,
        expires_at: datetime,
    ) -> tuple[Delegation, str]:
        """Issue a token once, alongside the row that holds only its hash."""
        if max_cap_cents < 0 or expires_at.tzinfo is None:
            # An absolute instant is required (api.md section 1); a naive value would
            # depend on the server's local zone, which I15 forbids.
            raise ApplicationError("VALIDATION_ERROR")
        normalized = {
            "pool_ids": [str(pool_id) for pool_id in scope.get("pool_ids", [])],
            "category": scope.get("category"),
        }
        token = _new_token()
        row = Delegation(
            id=uuid4(),
            user_id=user_id,
            token_hash=hash_token(self.hmac_key, token),
            scope=normalized,
            max_cap_cents=max_cap_cents,
            expires_at=expires_at,
        )
        session.add(row)
        await session.flush()
        await self.audit.append(
            session,
            actor=str(user_id),
            action="delegation.created",
            subject_type="delegation",
            subject_id=str(row.id),
            payload={
                "scope": normalized,
                "max_cap_cents": max_cap_cents,
                "expires_at": expires_at.isoformat(),
            },
        )
        # The token never reaches the audit payload or the log (rule 25).
        logger.info("delegation created user_id=%s delegation_id=%s", user_id, row.id)
        return row, token

    async def list(self, session: AsyncSession, *, user_id: UUID) -> list[Delegation]:
        return list(
            await session.scalars(
                select(Delegation)
                .where(Delegation.user_id == user_id)
                .order_by(Delegation.created_at, Delegation.id)
            )
        )

    async def revoke(
        self, session: AsyncSession, *, user_id: UUID, delegation_id: UUID
    ) -> Delegation:
        """Mark the delegation revoked; the row stays so the audit keeps its subject."""
        row = await session.scalar(
            select(Delegation)
            .where(Delegation.id == delegation_id, Delegation.user_id == user_id)
            .with_for_update()
        )
        if row is None:
            # Another buyer's delegation is not there: never a 403 that discloses it.
            raise ApplicationError("NOT_FOUND")
        if row.revoked_at is None:
            row.revoked_at = await self.clock.db_now(session)
            await session.flush()
            await self.audit.append(
                session,
                actor=str(user_id),
                action="delegation.revoked",
                subject_type="delegation",
                subject_id=str(row.id),
                payload={"max_cap_cents": row.max_cap_cents},
            )
        return row


class PostgresDelegationAuth:
    """Resolve ``fpd_<prefix>_<secret>`` to an ``AgentPrincipal`` or refuse."""

    def __init__(self, *, clock: Clock, hmac_key: str) -> None:
        self.clock = clock
        self.hmac_key = hmac_key

    async def from_token(self, session: AsyncSession, bearer: str) -> AgentPrincipal:
        """Read the row for this token hash; every failure is ``DELEGATION_INVALID``.

        The expiry comparison uses the database clock (I15), not the process clock,
        so two servers can never disagree about whether a token is still valid.
        """
        if not _looks_like_token(bearer):
            raise ApplicationError("DELEGATION_INVALID")
        row = await session.scalar(
            select(Delegation).where(Delegation.token_hash == hash_token(self.hmac_key, bearer))
        )
        if row is None or row.revoked_at is not None:
            raise ApplicationError("DELEGATION_INVALID")
        if row.expires_at <= await self.clock.db_now(session):
            raise ApplicationError("DELEGATION_INVALID")
        return AgentPrincipal(
            delegation_id=row.id,
            user_id=row.user_id,
            scope=dict(row.scope or {}),
            max_cap_cents=row.max_cap_cents,
            expires_at=row.expires_at,
        )


def _looks_like_token(bearer: str) -> bool:
    if not bearer.startswith(f"{TOKEN_PREFIX}_"):
        return False
    parts = bearer[len(TOKEN_PREFIX) + 1 :].split("_", 1)
    return len(parts) == 2 and len(parts[0]) == PREFIX_CHARS and bool(parts[1])
