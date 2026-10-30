"""Deterministic audit-chain fake (T01A02)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.hashing import audit_hash

ZERO_HASH = "0" * 64


class FakeAuditLog:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self.rows: list[dict[str, Any]] = []

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
        created_text = self._clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        prev_hash = self.rows[-1]["hash"] if self.rows else ZERO_HASH
        row = {
            "actor": actor,
            "action": action,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": payload,
            "created_at": created_text,
        }
        digest = audit_hash(prev_hash, row)
        self.rows.append(
            {
                "seq": len(self.rows) + 1,
                "prev_hash": prev_hash,
                "hash": digest,
                "row": row,
            }
        )
        return len(self.rows)

    def verify_chain(self) -> bool:
        prev_hash = ZERO_HASH
        for entry in self.rows:
            if entry["prev_hash"] != prev_hash:
                return False
            if audit_hash(prev_hash, entry["row"]) != entry["hash"]:
                return False
            prev_hash = entry["hash"]
        return True
