"""Deterministic manual confirmation (api.md "Intake", CR-3 pull-forward of T04B01).

The manual form is the deterministic half of intake: the pure validator in
``domain.request_rules`` decides, this module writes the immutable
``confirmed_requests`` row bound to the confirming user, the pool and the pool's
frozen ``rules_hash``, and nothing else. No AI, no PayPal, no money state.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import ConfirmedRequest, Pool
from fairpool.domain.errors import ApplicationError
from fairpool.domain.request_rules import ValidatedRequest, validate_manual_request
from fairpool.ports import AuditLog


class ManualIntakeService:
    """Turns a validated manual request into a durable confirmed request."""

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    async def confirm(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        pool_id: UUID,
        payload: dict[str, Any],
    ) -> ConfirmedRequest:
        pool = await session.scalar(select(Pool).where(Pool.id == pool_id))
        if pool is None:
            raise ApplicationError("NOT_FOUND")
        # The request freezes against the published rules; an unfrozen pool has
        # nothing to be consistent with (FR-LT-03).
        if pool.rules_hash is None:
            raise ApplicationError("VALIDATION_ERROR")
        template = {**pool.template, "pool_id": str(pool.id)}
        validated: ValidatedRequest = validate_manual_request(template, payload)
        record = ConfirmedRequest(
            id=uuid4(),
            pool_id=pool.id,
            user_id=user_id,
            rules_hash=pool.rules_hash,
            canonical_request=validated.canonical,
            request_hash=validated.request_hash,
            cap_cents=validated.cap_cents,
            zone_id=validated.zone_id,
        )
        session.add(record)
        await session.flush()
        await self.audit.append(
            session,
            actor=str(user_id),
            action="intake.manual.confirm",
            subject_type="confirmed_request",
            subject_id=str(record.id),
            payload={
                "pool_id": str(pool.id),
                "request_hash": record.request_hash,
                "zone_id": record.zone_id,
            },
        )
        return record
