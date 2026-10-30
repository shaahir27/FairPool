"""Deterministic idempotency-store fake (T01A02)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.ports import IdemConflict, IdemNew, IdemReplay, IdemResult


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.entries: dict[str, tuple[str, str, dict[str, Any] | None]] = {}

    async def begin(
        self,
        session: AsyncSession,
        *,
        key: str,
        scope: str,
        request_hash: str,
    ) -> IdemResult:
        if key not in self.entries:
            self.entries[key] = (scope, request_hash, None)
            return IdemNew()
        stored_scope, stored_hash, response = self.entries[key]
        if stored_scope != scope or stored_hash != request_hash:
            return IdemConflict()
        if response is None:
            return IdemConflict()
        return IdemReplay(response=dict(response))

    async def complete(
        self,
        session: AsyncSession,
        *,
        key: str,
        response: dict[str, Any],
    ) -> None:
        if key not in self.entries:
            raise KeyError(key)
        scope, request_hash, existing = self.entries[key]
        if existing is not None:
            raise ValueError("idempotency key already completed")
        self.entries[key] = (scope, request_hash, dict(response))
