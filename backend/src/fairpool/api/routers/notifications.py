"""The in-app notification inbox (T09B05, CR-13).

Two session routes over the existing ``notifications`` table: an owner-scoped list and
an idempotent mark-read. The principal decides whose rows are read or marked, never a
request parameter, so another user's notifications are neither listed nor touched.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import Principal
from fairpool.modules.notify.inbox import NotificationInbox

router = APIRouter()


def _inbox() -> NotificationInbox:
    # The API layer owns the database clock; the module only sees the port.
    return NotificationInbox(DbClock())


@router.get(
    "/api/v1/me/notifications",
    response_model=schemas.NotificationsResponse,
    operation_id="me_notifications_list",
)
async def me_notifications_list(
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.NotificationsResponse:
    items, unread = await _inbox().list_for_user(db, principal.user_id)
    return schemas.NotificationsResponse(
        items=[
            schemas.NotificationView(
                id=row.id,
                kind=row.kind,
                payload=row.payload,
                created_at=row.created_at,
                read_at=row.read_at,
            )
            for row in items
        ],
        unread=unread,
    )


@router.post(
    "/api/v1/me/notifications/read",
    response_model=schemas.NotificationReadResponse,
    operation_id="me_notifications_read",
)
async def me_notifications_read(
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.NotificationReadResponse:
    marked = await _inbox().mark_all_read(db, principal.user_id)
    return schemas.NotificationReadResponse(marked=marked, unread=0)
