"""Owner-scoped notification reads (T09B05, CR-13); writes stay in ``service.py``.

The rows are written by the modules that produce the events, inside the transaction
that produced them (I10). This module only reads them back for their owner and marks
them read with the database clock (I15); it never changes an entry, an order or a
payment, and it adds no delivery channel (FR-UI-09).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.platform import Notification
from fairpool.ports import Clock

#: CR-13: the list is capped; ``unread`` still counts every row, not the page.
LIST_LIMIT: Final[int] = 50


class NotificationInbox:
    def __init__(self, clock: Clock) -> None:
        # The read timestamp comes from the injected clock (I15); this module is
        # Member B's and reaches no infrastructure directly (scaffold section 5.5).
        self.clock = clock

    async def list_for_user(
        self, session: AsyncSession, user_id: UUID
    ) -> tuple[list[Notification], int]:
        rows = (
            await session.scalars(
                select(Notification)
                .where(Notification.user_id == user_id)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(LIST_LIMIT)
            )
        ).all()
        unread = await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        return list(rows), int(unread or 0)

    async def mark_all_read(self, session: AsyncSession, user_id: UUID) -> int:
        """Mark every unread row of this user read; return how many changed."""
        now = await self.clock.db_now(session)
        marked = await session.scalars(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=now)
            .returning(Notification.id)
        )
        return len(marked.all())
