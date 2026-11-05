"""T08B02: the merchant SSE feed (``GET /api/v1/merchant/events``).

The feed mirrors the public pool feed: short read sessions on the database clock,
no transaction or lock held for the life of a stream, and only ``tick``,
``lot_open``, ``bid_status`` and ``checkout_progress`` frames. Nothing on the
feed is buyer data: only lot, bid and status identifiers.

The generator opens its own read sessions, so the test binds its session factory
to the same connection the fixture transaction already holds; the reads see the
uncommitted world and the fixture still rolls everything back.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.modules.merchants.events import stream_merchant_events
from tests.integration.test_join_receipts import PASSWORD, login, settings_for
from tests.integration.test_open_checkout import build_world

pytestmark = pytest.mark.integration

ALLOWED = {"tick", "lot_open", "bid_status", "checkout_progress"}


def shared_factory(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    """Read sessions on the fixture's connection, so committed visibility is not needed."""
    bind = session.bind
    assert bind is not None
    return async_sessionmaker(
        bind=bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def add_bidding_lot(session: AsyncSession, pool_id: uuid.UUID) -> uuid.UUID:
    lot_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, 'US-EAST', 1, 2, 2, 2, "
            "'BIDDING', now(), now() + interval '1 hour')"
        ),
        {"id": lot_id, "pool": pool_id},
    )
    await session.flush()
    return lot_id


async def add_award(session: AsyncSession, lot_id: uuid.UUID, merchant_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, "
            "item_cents, moq, totals, valid_until, rule_version, award_hash) VALUES "
            "(:id, :lot, NULL, :merchant, 0, 47000, 2, '{}'::jsonb, now(), "
            "'ranking_v1', :hash)"
        ),
        {"id": uuid.uuid4(), "lot": lot_id, "merchant": merchant_id, "hash": "0" * 64},
    )
    await session.execute(
        text("UPDATE lots SET status = 'AWARDED' WHERE id = :lot"), {"lot": lot_id}
    )
    await session.flush()


async def add_bid(session: AsyncSession, lot_id: uuid.UUID, merchant_id: uuid.UUID) -> uuid.UUID:
    bid_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO bids (id, lot_id, merchant_id, status, current_revision) "
            "VALUES (:id, :lot, :merchant, 'CONFIRMED', 1)"
        ),
        {"id": bid_id, "lot": lot_id, "merchant": merchant_id},
    )
    await session.flush()
    return bid_id


def frames_are_safe(frame: str) -> None:
    blocks = [block for block in frame.strip().split("\n\n") if block]
    assert blocks, frame
    for block in blocks:
        lines = block.split("\n")
        assert lines[0].startswith("event: "), block
        name = lines[0].removeprefix("event: ")
        assert name in ALLOWED, name
        data: dict[str, Any] = json.loads(lines[1].removeprefix("data: "))
        if name == "tick":
            assert list(data) == ["server_time"]
        rendered = json.dumps(data).lower()
        for forbidden in ("email", "name", "address", "line1", "postal"):
            assert forbidden not in rendered, (name, forbidden)


async def test_the_feed_emits_lot_open_bid_status_and_checkout_progress(
    db_session: AsyncSession,
) -> None:
    world = await build_world(
        db_session, lot_status="BIDDING", with_award=False, seats=2, seated=2, waitlisted=0
    )
    bidding_lot = await add_bidding_lot(db_session, world.pool_id)
    awarded_lot = world.lot_id
    await add_award(db_session, awarded_lot, world.merchant_id)
    bid_id = await add_bid(db_session, bidding_lot, world.merchant_id)
    factory = shared_factory(db_session)

    generator = stream_merchant_events(factory, world.merchant_id, interval_s=0.05)
    first = await generator.__anext__()
    frames_are_safe(first)
    assert "event: lot_open" in first
    assert str(bidding_lot) in first
    assert "event: bid_status" in first
    assert "event: checkout_progress" in first
    assert str(awarded_lot) in first
    assert "event: tick" in first

    unchanged = await generator.__anext__()
    frames_are_safe(unchanged)
    assert unchanged.count("event:") == 1 and "event: tick" in unchanged

    await db_session.execute(
        text("UPDATE bids SET status = 'REJECTED' WHERE id = :id"), {"id": bid_id}
    )
    await db_session.flush()
    changed = await generator.__anext__()
    frames_are_safe(changed)
    assert "event: bid_status" in changed and '"status":"REJECTED"' in changed
    await generator.aclose()


async def _drive_first_stream_frame(
    app: Any, path: str, *, headers: list[tuple[bytes, bytes]]
) -> tuple[int, dict[str, str], str]:
    received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    request_seen = {"done": False}

    async def receive() -> dict[str, Any]:
        if not request_seen["done"]:
            request_seen["done"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        received.put_nowait(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "headers": headers,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "server": ("api.test", 443),
        "client": ("127.0.0.1", 50000),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        start = await asyncio.wait_for(received.get(), timeout=5.0)
        assert start["type"] == "http.response.start"
        response_headers = dict(
            (key.lower().decode(), value.decode()) for key, value in start["headers"]
        )
        body = ""
        while not body:
            message = await asyncio.wait_for(received.get(), timeout=5.0)
            assert message["type"] == "http.response.body"
            body = str(message["body"].decode())
        return int(start["status"]), response_headers, body
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_the_route_needs_a_merchant_and_streams_on_connect(
    db_session: AsyncSession,
) -> None:
    app = create_app(settings_for())

    async def session():
        yield db_session

    app.dependency_overrides[database_session] = session
    factory = shared_factory(db_session)
    app.state.session_factory = factory
    world = await build_world(
        db_session, lot_status="BIDDING", with_award=False, seats=2, seated=2, waitlisted=0
    )

    anonymous = await _drive_first_stream_frame(app, "/api/v1/merchant/events", headers=[])
    assert anonymous[0] == 401

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await login(client, "sse-merchant@example.test")
        await db_session.execute(
            text("UPDATE users SET role = 'merchant' WHERE email = :email"),
            {"email": "sse-merchant@example.test"},
        )
        await db_session.flush()
        relogin = await client.post(
            "/api/v1/auth/login",
            json={"email": "sse-merchant@example.test", "password": PASSWORD},
        )
        assert relogin.status_code == 200
        profile = await client.post(
            "/api/v1/merchant/profile",
            headers={"X-CSRF-Token": str(relogin.json()["csrf_token"])},
            json={"display_name": "Demo SSE", "attestations": {}},
        )
        assert profile.status_code == 200, profile.text
        cookie = client.cookies.get("__Host-session")
        assert cookie

    status, headers, frame = await _drive_first_stream_frame(
        app,
        "/api/v1/merchant/events",
        headers=[(b"cookie", f"__Host-session={cookie}".encode())],
    )
    assert status == 200
    assert headers["content-type"].startswith("text/event-stream")
    frames_are_safe(frame)
    assert "event: lot_open" in frame and "event: tick" in frame
    assert str(world.lot_id) in frame
