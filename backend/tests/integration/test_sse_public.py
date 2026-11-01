"""T03B01: the public SSE feed (api.md "Server-sent events", CR-3).

The feed is public, emits only ``pool_status``, ``lot_status`` and ``tick``
with server time, opens short read sessions (no transaction or lock held for
the life of a stream) and stops cleanly when the client disconnects.

httpx's ASGITransport buffers responses, so the endless stream is exercised at
the raw ASGI level: the test drives the app with its own ``send``/``receive``,
reads the first frame, then cancels the task the way a disconnect would.
Setup rows are committed because the feed's short read sessions are separate
connections.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from fairpool.api.app import create_app
from fairpool.modules.pools.events import stream_pool_events
from tests.integration.test_join_receipts import open_pool, settings_for, wipe_join_data

pytestmark = pytest.mark.integration


async def make_pool(
    db_engine: AsyncEngine, *, status: str = "OPEN", close_in: int = 3600
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        # open_pool writes pools + its admin user and rolls back with the
        # fixture; here it runs inside a committed transaction instead.
        pool_id = await open_pool(session, status=status, close_in=close_in)
    return pool_id


async def make_lot(
    db_engine: AsyncEngine, pool_id: uuid.UUID, lot_order: int, status: str
) -> uuid.UUID:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    lot_id = uuid.uuid4()
    async with maker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, "
                "min_seats, status, bid_open_at, bid_close_at) "
                "VALUES (:id, :pool, 'US-EAST', 0, :order, 3, 2, "
                "CAST(:status AS lot_status), now(), now())"
            ),
            {"id": lot_id, "pool": pool_id, "order": lot_order, "status": status},
        )
    return lot_id


async def set_pool_status(db_engine: AsyncEngine, pool_id: uuid.UUID, status: str) -> None:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        await session.execute(
            text("UPDATE pools SET status = CAST(:s AS pool_status) WHERE id = :id"),
            {"s": status, "id": pool_id},
        )


def allowed_events_only(frames: list[str]) -> None:
    for frame in frames:
        for block in frame.strip().split("\n\n"):
            if not block:
                continue
            lines = block.split("\n")
            assert lines[0].startswith("event: "), block
            name = lines[0].removeprefix("event: ")
            assert name in {"pool_status", "lot_status", "tick"}, name
            data: dict[str, Any] = json.loads(lines[1].removeprefix("data: "))
            if name == "tick":
                assert list(data) == ["server_time"]
            else:
                assert "personal" not in json.dumps(data)


@pytest.fixture
def factory(db_engine: AsyncEngine) -> async_sessionmaker[Any]:
    return async_sessionmaker(db_engine, expire_on_commit=False)


async def test_stream_emits_only_public_status_and_tick(db_engine: AsyncEngine, factory):
    pool_id = await make_pool(db_engine)
    lot_id = await make_lot(db_engine, pool_id, 1, "PLANNED")
    agen = stream_pool_events(factory, pool_id, interval_s=0.05)
    frame = await agen.__anext__()
    await agen.aclose()  # client disconnect: the generator must stop cleanly
    allowed_events_only([frame])
    assert "event: pool_status" in frame
    assert '"status":"OPEN"' in frame
    assert lot_id.hex in frame.replace("-", "")
    assert "event: lot_status" in frame
    assert "event: tick" in frame
    assert '"server_time"' in frame
    # No salts, caps, identities or entry data can ride the public feed.
    forbidden = ("cap", "salt", "email", "entry", "paypal", "request")
    low = frame.lower()
    for word in forbidden:
        assert word not in low, word
    await wipe_join_data(db_engine, pool_id, [])


async def test_stream_re_emits_only_changed_state(db_engine: AsyncEngine, factory):
    pool_id = await make_pool(db_engine)
    agen = stream_pool_events(factory, pool_id, interval_s=0.05)
    first = await agen.__anext__()
    assert "event: pool_status" in first
    # Nothing changed: no status events on the second poll, only a tick.
    second = await agen.__anext__()
    assert second.count("event:") == 1 and "event: tick" in second
    # The pool closes: the next poll carries pool_status with the new value.
    await set_pool_status(db_engine, pool_id, "CLOSED")
    third = await agen.__anext__()
    assert "event: pool_status" in third and '"status":"CLOSED"' in third
    allowed_events_only([first, second, third])
    await agen.aclose()
    await wipe_join_data(db_engine, pool_id, [])


async def test_stream_holds_no_transaction_or_lock(db_engine: AsyncEngine, factory):
    """A concurrent writer can lock the pool row while a stream is live."""
    pool_id = await make_pool(db_engine)
    agen = stream_pool_events(factory, pool_id, interval_s=5.0)
    await agen.__anext__()  # between polls the generator holds no session
    blocker = await db_engine.connect()
    try:
        result = await asyncio.wait_for(
            blocker.execute(
                text("SELECT id FROM pools WHERE id = :id FOR UPDATE"), {"id": pool_id}
            ),
            timeout=2.0,
        )
        assert result is not None  # would hang if the stream held the pool row
    finally:
        await blocker.close()
        await agen.aclose()
    await wipe_join_data(db_engine, pool_id, [])


async def _drive_first_stream_frame(app: Any, path: str) -> tuple[int, dict[str, str], str]:
    received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    request_seen = {"done": False}

    async def receive() -> dict[str, Any]:
        # BaseHTTPMiddleware rejects a second http.request: deliver the empty
        # body once, then block the way a real keep-alive connection would.
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
        "headers": [],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, receive, send))
    try:
        start = await asyncio.wait_for(received.get(), timeout=5.0)
        assert start["type"] == "http.response.start"
        headers = dict((k.lower().decode(), v.decode()) for k, v in start["headers"])
        text = ""
        while not text:
            message = await asyncio.wait_for(received.get(), timeout=5.0)
            assert message["type"] == "http.response.body"
            text = str(message["body"].decode())
        return int(start["status"]), headers, text
    finally:
        task.cancel()  # client disconnect
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_route_is_public_streams_events_and_stops_on_disconnect(
    db_engine: AsyncEngine, factory
):
    pool_id = await make_pool(db_engine)
    await make_lot(db_engine, pool_id, 1, "BIDDING")
    app = create_app(settings_for())
    app.state.engine = db_engine
    app.state.session_factory = factory

    status, headers, frame = await _drive_first_stream_frame(app, f"/api/v1/pools/{pool_id}/events")
    assert status == 200  # public: no session cookie was sent at all
    assert headers["content-type"].startswith("text/event-stream")
    allowed_events_only([frame])
    assert "event: pool_status" in frame and "event: lot_status" in frame and "event: tick" in frame
    await wipe_join_data(db_engine, pool_id, [])


async def test_unknown_or_draft_pool_is_404(db_engine: AsyncEngine, factory):
    draft = await make_pool(db_engine, status="DRAFT")
    app = create_app(settings_for())
    app.state.engine = db_engine
    app.state.session_factory = factory

    async def get_status(path: str) -> int:
        done = asyncio.Event()
        box: dict[str, int] = {}

        request_seen = {"done": False}

        async def receive() -> dict[str, Any]:
            if not request_seen["done"]:
                request_seen["done"] = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                box["status"] = int(message["status"])
                done.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "headers": [],
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "server": ("test", 80),
            "client": ("127.0.0.1", 50000),
            "root_path": "",
        }
        await app(scope, receive, send)
        await asyncio.wait_for(done.wait(), timeout=5.0)
        return box["status"]

    assert await get_status(f"/api/v1/pools/{uuid.uuid4()}/events") == 404
    assert await get_status(f"/api/v1/pools/{draft}/events") == 404
    await wipe_join_data(db_engine, draft, [])
