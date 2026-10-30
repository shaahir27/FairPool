"""Schema revision and the database/migrations readiness probe (T01A01)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import text

from fairpool.db.session import get_engine

# Updated only when a new migration is added; test_schema_contract checks it
# against the newest file under backend/migrations/versions.
HEAD_REVISION = "0001"


def make_readiness_probe() -> Callable[[], Awaitable[dict[str, str]]]:
    async def probe() -> dict[str, str]:
        try:
            async with get_engine().connect() as connection:
                await connection.execute(text("SELECT 1"))
                try:
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                except Exception:
                    return {"database": "ok", "migrations": "not_migrated"}
        except Exception:
            return {"database": "error", "migrations": "unknown"}
        if revision != HEAD_REVISION:
            return {"database": "ok", "migrations": "pending"}
        return {"database": "ok", "migrations": "ok"}

    return probe
