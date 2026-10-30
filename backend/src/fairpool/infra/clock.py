"""Database clock implementation (T01A02; I15)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DbClock:
    """Deadlines always come from the database clock, never the process clock."""

    async def db_now(self, session: AsyncSession) -> datetime:
        value = await session.scalar(text("SELECT now()"))
        if not isinstance(value, datetime):
            raise RuntimeError("database clock returned a non-datetime value")
        return value
