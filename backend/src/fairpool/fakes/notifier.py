"""In-memory notifier fake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fairpool.ports import AsyncSession


@dataclass(frozen=True)
class NotifyCall:
    user_id: UUID
    kind: str
    payload: dict[str, Any]


class FakeNotifier:
    """Records notifications without writing rows."""

    def __init__(self) -> None:
        self.calls: list[NotifyCall] = []

    async def notify(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append(NotifyCall(user_id=user_id, kind=kind, payload=dict(payload)))
