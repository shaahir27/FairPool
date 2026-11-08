"""T09B05 / CR-13: the in-app notification inbox reads.

The rows are written by the modules that produce the events; these tests prove the two
reads the contract adds: an owner-scoped list newest first and an idempotent mark-read,
with the unread count matching ``GET /api/v1/me``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.db.models.platform import Notification
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.integration

PASSWORD = "a secure password"


async def signed_in_user(session: AsyncSession, email: str) -> tuple[httpx.AsyncClient, str]:
    """A registered buyer with a live session cookie and the CSRF token login returned."""
    app = create_app(make_settings())

    async def db() -> object:
        yield session

    app.dependency_overrides[database_session] = db
    await IdentityService("test-signing-key", DbClock()).register(
        session, email=email, password=PASSWORD, display_name=email.split("@")[0]
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    )
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return client, response.json()["csrf_token"]


def notification(
    user_id: UUID, kind: str, *, created_at: datetime, payload: dict[str, object] | None = None
) -> Notification:
    return Notification(
        id=uuid4(),
        user_id=user_id,
        kind=kind,
        payload=payload or {},
        created_at=created_at,
    )


async def test_list_is_owner_scoped_newest_first_and_anonymous_is_401(
    db_session: AsyncSession,
) -> None:
    buyer_a, _ = await signed_in_user(db_session, "notify-a@example.test")
    buyer_b, _ = await signed_in_user(db_session, "notify-b@example.test")
    me_a = (await buyer_a.get("/api/v1/me")).json()
    me_b = (await buyer_b.get("/api/v1/me")).json()
    now = datetime.now(UTC)
    older = notification(
        UUID(me_a["user_id"]), "lot.cancelled", created_at=now - timedelta(hours=2)
    )
    newer = notification(UUID(me_a["user_id"]), "lot.awarded", created_at=now - timedelta(hours=1))
    foreign = notification(UUID(me_b["user_id"]), "bid.lost", created_at=now)
    db_session.add_all([older, newer, foreign])
    await db_session.flush()

    response = await buyer_a.get("/api/v1/me/notifications")
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(newer.id), str(older.id)]
    assert body["items"][0]["kind"] == "lot.awarded"
    assert set(body["items"][0]) == {"id", "kind", "payload", "created_at", "read_at"}
    assert body["unread"] == 2
    assert str(foreign.id) not in {item["id"] for item in body["items"]}

    other = await buyer_b.get("/api/v1/me/notifications")
    assert [item["id"] for item in other.json()["items"]] == [str(foreign.id)]

    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(make_settings())),
        base_url="https://example.test",
    )
    assert (await anonymous.get("/api/v1/me/notifications")).status_code == 401

    await buyer_a.aclose()
    await buyer_b.aclose()
    await anonymous.aclose()


async def test_list_is_capped_at_fifty_rows(db_session: AsyncSession) -> None:
    buyer, _ = await signed_in_user(db_session, "notify-limit@example.test")
    user_id = UUID((await buyer.get("/api/v1/me")).json()["user_id"])
    start = datetime.now(UTC) - timedelta(days=1)
    db_session.add_all(
        [
            notification(
                user_id,
                "lot.funded",
                created_at=start + timedelta(minutes=index),
                payload={"index": index},
            )
            for index in range(55)
        ]
    )
    await db_session.flush()

    body = (await buyer.get("/api/v1/me/notifications")).json()
    assert len(body["items"]) == 50
    # Newest first, and the unread count covers every row rather than the page.
    assert body["items"][0]["payload"] == {"index": 54}
    assert body["unread"] == 55
    await buyer.aclose()


async def test_mark_read_is_idempotent_and_unread_parity_holds(db_session: AsyncSession) -> None:
    buyer_a, csrf_a = await signed_in_user(db_session, "notify-read-a@example.test")
    buyer_b, _ = await signed_in_user(db_session, "notify-read-b@example.test")
    user_a = UUID((await buyer_a.get("/api/v1/me")).json()["user_id"])
    user_b = UUID((await buyer_b.get("/api/v1/me")).json()["user_id"])
    now = datetime.now(UTC)
    db_session.add_all(
        [
            notification(user_a, "buyer_order.rejected", created_at=now - timedelta(minutes=2)),
            notification(user_a, "entry.rejected", created_at=now - timedelta(minutes=1)),
            notification(user_b, "bid.flagged", created_at=now),
        ]
    )
    await db_session.flush()

    assert (await buyer_a.get("/api/v1/me")).json()["unread_notifications"] == 2
    assert (await buyer_a.get("/api/v1/me/notifications")).json()["unread"] == 2

    first = await buyer_a.post("/api/v1/me/notifications/read", headers={"X-CSRF-Token": csrf_a})
    assert first.status_code == 200
    assert first.json() == {"marked": 2, "unread": 0}
    assert (await buyer_a.get("/api/v1/me")).json()["unread_notifications"] == 0
    assert (await buyer_a.get("/api/v1/me/notifications")).json()["unread"] == 0
    assert all(
        item["read_at"] is not None
        for item in (await buyer_a.get("/api/v1/me/notifications")).json()["items"]
    )

    second = await buyer_a.post("/api/v1/me/notifications/read", headers={"X-CSRF-Token": csrf_a})
    assert second.status_code == 200
    assert second.json() == {"marked": 0, "unread": 0}

    # Another user's rows are neither marked nor counted on the caller's behalf.
    assert (await buyer_b.get("/api/v1/me")).json()["unread_notifications"] == 1
    assert (await buyer_b.get("/api/v1/me/notifications")).json()["items"][0]["read_at"] is None

    assert (await buyer_a.post("/api/v1/me/notifications/read")).status_code == 403
    await buyer_a.aclose()
    await buyer_b.aclose()
