"""T07B03/PT-16: the FairPool MCP server exposes exactly four tools and no payment.

Contract: ``api.md`` section 4.5, ``testing-strategy.md`` (test_mcp_contract at
IG-7, PT-16). The test drives a real JSON-RPC handshake through the mounted
``/mcp`` app of the parent FastAPI application with a committed delegation token,
so the transport, the delegation auth and one tool call are all proved together.
Every tool is a call into the Agent API; none of them can create an order,
authorize, capture, void or refund (I1, I2, rule 22).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.modules.identity.delegations import hash_token
from fairpool.modules.mcp.tools import TOOL_NAMES, TOOL_SPECS
from tests.conftest import database_url
from tests.integration.test_join_receipts import open_pool, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for(database_url=database_url())
EXPECTED_TOOLS = {"list_pools", "enter_pool", "list_entries", "withdraw_entry"}
PAYMENT_VERB = re.compile(
    r"\b(?:authorize|capture|void|refund|charge|payout|create[\s_-]*order)\b", re.IGNORECASE
)


def rpc(request_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


async def committed_delegation(engine: AsyncEngine) -> tuple[str, UUID]:
    """A delegation row the MCP transport's own connection can see (it commits)."""
    token = f"fpd_{secrets.token_hex(4)}_{secrets.token_urlsafe(32)[:43]}"
    user_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name, role) "
                "VALUES (:id, :email, 'hash', 'MCP Buyer', 'buyer')"
            ),
            {"id": user_id, "email": f"mcp-{user_id}@example.test"},
        )
        await connection.execute(
            text(
                "INSERT INTO delegations (id, user_id, token_hash, scope, max_cap_cents, "
                "expires_at) VALUES (:id, :user, :hash, CAST(:scope AS jsonb), 60000, "
                "now() + interval '1 hour')"
            ),
            {
                "id": uuid4(),
                "user": user_id,
                "hash": hash_token(SETTINGS.hmac_key.get_secret_value(), token),
                "scope": '{"pool_ids": [], "category": null}',
            },
        )
    return token, user_id


async def forget(engine: AsyncEngine, user_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM delegations WHERE user_id = :id"), {"id": user_id}
        )
        await connection.execute(text("DELETE FROM sessions WHERE user_id = :id"), {"id": user_id})
        await connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


def test_there_are_exactly_four_tools_and_no_payment_tool() -> None:
    names = [spec["name"] for spec in TOOL_SPECS]
    assert names == ["list_pools", "enter_pool", "list_entries", "withdraw_entry"]
    assert set(names) == TOOL_NAMES == EXPECTED_TOOLS
    for spec in TOOL_SPECS:
        assert spec["inputSchema"]["type"] == "object"
        assert not PAYMENT_VERB.search(spec["name"]), spec["name"]
        assert not PAYMENT_VERB.search(str(spec["inputSchema"])), spec["name"]
    enter = next(spec for spec in TOOL_SPECS if spec["name"] == "enter_pool")
    properties = enter["inputSchema"]["properties"]
    assert {"max_total_usd", "max_total_cents"} <= set(properties)
    assert set(enter["inputSchema"]["required"]) == {
        "pool_id",
        "delivery_region",
        "idempotency_key",
    }


async def test_initialize_list_and_one_tool_call_through_the_parent_app(
    client: httpx.AsyncClient, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    token, user_id = await committed_delegation(db_engine)
    pool_id = await open_pool(db_session)
    title = f"MCP pool {pool_id}"
    await db_session.execute(
        text("UPDATE pools SET title = :title, search_text = :title WHERE id = :id"),
        {"title": title, "id": pool_id},
    )
    headers = {"Authorization": f"Bearer {token}"}
    try:
        initialized = await client.post(
            "/mcp",
            headers=headers,
            json=rpc(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1"},
                },
            ),
        )
        assert initialized.status_code == 200, initialized.text
        init = initialized.json()["result"]
        assert init["serverInfo"] == {"name": "fairpool", "version": "0.1.0"}
        assert "tools" in init["capabilities"]

        listed = await client.post("/mcp", headers=headers, json=rpc(2, "tools/list"))
        assert listed.status_code == 200, listed.text
        tools = listed.json()["result"]["tools"]
        assert {tool["name"] for tool in tools} == EXPECTED_TOOLS

        called = await client.post(
            "/mcp",
            headers=headers,
            json=rpc(
                3,
                "tools/call",
                {"name": "list_pools", "arguments": {"q": title, "limit": 10}},
            ),
        )
        assert called.status_code == 200, called.text
        result = called.json()["result"]
        assert result["isError"] is False, result
        pools = json.loads(result["content"][0]["text"])
        assert [item["pool_id"] for item in pools] == [str(pool_id)]
    finally:
        await forget(db_engine, user_id)


async def test_missing_or_invalid_bearer_is_a_json_401(client: httpx.AsyncClient) -> None:
    anonymous = await client.post("/mcp", json=rpc(1, "initialize"))
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "DELEGATION_INVALID"

    bogus = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer fpd_00000000_" + "A" * 43},
        json=rpc(1, "initialize"),
    )
    assert bogus.status_code == 401
    assert bogus.json()["error"]["code"] == "DELEGATION_INVALID"

    # GET is the stream form: it must also refuse an unauthenticated caller.
    stream = await client.get("/mcp")
    assert stream.status_code == 401


async def test_notifications_are_accepted_without_a_response(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, user_id = await committed_delegation(db_engine)
    try:
        response = await client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert response.status_code == 202
        assert response.content == b""
    finally:
        await forget(db_engine, user_id)
