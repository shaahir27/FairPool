"""Transactional notification creation; no delivery side effects."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.platform import Notification


class PostgresNotifier:
    async def notify(
        self, session: AsyncSession, *, user_id: UUID, kind: str, payload: dict[str, Any]
    ) -> None:
        session.add(Notification(id=uuid4(), user_id=user_id, kind=kind, payload=payload))
        await session.flush()
