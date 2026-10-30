"""Append-only audit chain (T01A02; fairness-and-hashing.md section 8)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.hashing import audit_hash

AUDIT_LOCK = 0x46414952504F4F4C
ZERO_HASH = "0" * 64


class PostgresAuditLog:
    """Serialise appends, read the database time, and chain every row."""

    async def append(
        self,
        session: AsyncSession,
        *,
        actor: str,
        action: str,
        subject_type: str,
        subject_id: str | None,
        payload: dict[str, Any],
    ) -> int:
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_LOCK})
        created_at = await session.scalar(text("SELECT now()"))
        if not isinstance(created_at, datetime):
            raise RuntimeError("database clock returned a non-datetime value")
        previous = await session.scalar(
            text("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        )
        prev_hash = str(previous) if previous else ZERO_HASH
        created_text = created_at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        row = {
            "actor": actor,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload,
            "created_at": created_text,
        }
        digest = audit_hash(prev_hash, row)
        seq = await session.scalar(
            text(
                "INSERT INTO audit_log "
                "(prev_hash, hash, actor, action, subject_type, subject_id, payload, created_at) "
                "VALUES (:prev, :hash, :actor, :action, :subject_type, :subject_id, "
                "CAST(:payload AS jsonb), :created_at) RETURNING seq"
            ),
            {
                "prev": prev_hash,
                "hash": digest,
                "actor": actor,
                "action": action,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "payload": json.dumps(payload),
                "created_at": created_at,
            },
        )
        if seq is None:
            raise RuntimeError("audit insert returned no sequence")
        return int(seq)
