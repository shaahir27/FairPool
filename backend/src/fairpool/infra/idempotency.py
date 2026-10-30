"""Postgres idempotency store (T01A02; api.md section 1)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.ports import IdemConflict, IdemNew, IdemReplay, IdemResult


class PostgresIdempotencyStore:
    async def begin(
        self,
        session: AsyncSession,
        *,
        key: str,
        scope: str,
        request_hash: str,
    ) -> IdemResult:
        inserted = await session.scalar(
            text(
                "INSERT INTO idempotency_keys (key, scope, request_hash) "
                "VALUES (:key, :scope, :hash) ON CONFLICT (key) DO NOTHING RETURNING key"
            ),
            {"key": key, "scope": scope, "hash": request_hash},
        )
        if inserted is not None:
            return IdemNew()

        row = (
            await session.execute(
                text("SELECT scope, request_hash, response FROM idempotency_keys WHERE key = :key"),
                {"key": key},
            )
        ).one()
        existing_scope, existing_hash, response = row
        if existing_scope != scope or existing_hash != request_hash:
            return IdemConflict()
        if response is None:
            return IdemConflict()
        return IdemReplay(response=response)

    async def complete(
        self,
        session: AsyncSession,
        *,
        key: str,
        response: dict[str, Any],
    ) -> None:
        await session.execute(
            text(
                "UPDATE idempotency_keys SET response = CAST(:response AS jsonb) "
                "WHERE key = :key AND response IS NULL"
            ),
            {"key": key, "response": json.dumps(response)},
        )
