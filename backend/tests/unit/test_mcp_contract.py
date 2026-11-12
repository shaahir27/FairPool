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
        # CR-17: committing a savepoint keeps locks in the fixture's outer transaction.
        connection = await db_session.connection()
        await db_session.rollback()
        await connection.rollback()
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


async def test_a_missing_required_argument_is_invalid_params(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    """-32602 names the forgotten parameter instead of surfacing a -32603."""
    token, user_id = await committed_delegation(db_engine)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        withdraw = await client.post(
            "/mcp",
            headers=headers,
            json=rpc(1, "tools/call", {"name": "withdraw_entry", "arguments": {}}),
        )
        assert withdraw.status_code == 200, withdraw.text
        assert withdraw.json()["error"]["code"] == -32602
        assert "entry_id" in withdraw.json()["error"]["message"]

        enter = await client.post(
            "/mcp",
            headers=headers,
            json=rpc(
                2,
                "tools/call",
                {"name": "enter_pool", "arguments": {"pool_id": str(uuid4())}},
            ),
        )
        assert enter.json()["error"]["code"] == -32602
        assert "delivery_region" in enter.json()["error"]["message"]
    finally:
        await forget(db_engine, user_id)


async def test_an_oversized_body_is_a_413_before_any_dispatch(
    client: httpx.AsyncClient,
) -> None:
    """64 KiB is the POST cap: the body is refused before auth or any tool call."""
    over = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"pad": "x" * (64 * 1024)},
    }
    refused = await client.post(
        "/mcp",
        headers={"Authorization": "Bearer fpd_00000000_" + "A" * 43},
        json=over,
    )
    assert refused.status_code == 413, refused.text
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_a_batch_over_twenty_messages_is_a_413(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    token, user_id = await committed_delegation(db_engine)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        refused = await client.post(
            "/mcp", headers=headers, json=[rpc(i, "ping") for i in range(21)]
        )
        assert refused.status_code == 413, refused.text
        assert refused.json()["error"]["code"] == "VALIDATION_ERROR"

        accepted = await client.post(
            "/mcp", headers=headers, json=[rpc(i, "ping") for i in range(20)]
        )
        assert accepted.status_code == 200
        assert len(accepted.json()) == 20
    finally:
        await forget(db_engine, user_id)


async def test_the_transport_reuses_the_apps_session_factory(
    db_engine: AsyncEngine,
) -> None:
    """One pool for the API and /mcp: the transport never builds or disposes its own."""
    app = create_app(SETTINGS)
    token, user_id = await committed_delegation(db_engine)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as http:
            headers = {"Authorization": f"Bearer {token}"}
            first = await http.post("/mcp", headers=headers, json=rpc(1, "ping"))
            assert first.status_code == 200, first.text
            factory = app.state.session_factory
            second = await http.post("/mcp", headers=headers, json=rpc(2, "ping"))
            assert second.status_code == 200, second.text
            assert app.state.session_factory is factory
    finally:
        await forget(db_engine, user_id)
        await app.state.engine.dispose()


async def test_market_buyer_really_enters_through_mcp(
    client: httpx.AsyncClient, db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    from tools.agent_market import Market

    token, user_id = await committed_delegation(db_engine)
    pool_id = await open_pool(db_session)
    market = Market(setting=SETTINGS, factory=None, http=client, db=None)
    market.delegations = [(token, user_id)]
    market.pool_id = pool_id
    try:
        await market.buyers()
        count = await db_session.scalar(
            text("SELECT count(*) FROM pool_entries WHERE pool_id = :pool AND user_id = :user"),
            {"pool": pool_id, "user": user_id},
        )
        assert count == 1, "a successful market report must represent a persisted buyer entry"
        assert all(step["ok"] for step in market.report["buyer_agents"])
        assert market.report["buyer_agents"][0]["hint"] is not None
        other_pool = await open_pool(db_session)
        other = await client.post(
            "/agent/v1/entries",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "other-market"},
            json={
                "pool_id": str(other_pool),
                "request": {
                    "delivery": {"region": "NY"},
                    "required_by": "2026-12-01",
                    "max_total_cents": 52000,
                    "firm": [],
                    "preferences": [],
                },
            },
        )
        assert other.status_code == 201
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def factory() -> AsyncIterator[AsyncSession]:
            yield db_session

        market.factory = factory
        await market.money()
        assert sum(row["count"] for row in market.report["money"]["entries_by_surface"]) == 1
    finally:
        connection = await db_session.connection()
        await db_session.rollback()
        await connection.rollback()
        await forget(db_engine, user_id)


@pytest.mark.parametrize(
    "tool_result",
    [
        {"isError": True, "content": [{"type": "text", "text": "refused"}]},
        {},
        None,
    ],
)
async def test_market_reports_mocked_mcp_tool_errors_as_failure(
    tool_result: dict[str, Any] | None,
) -> None:
    from tools.agent_market import Market

    def reply(request: httpx.Request) -> httpx.Response:
        message = json.loads(request.content)
        result: dict[str, Any] | None
        if message["method"] == "tools/list":
            result = {"tools": TOOL_SPECS}
        else:
            result = tool_result
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(reply), base_url="https://api.test"
    ) as http:
        market = Market(setting=SETTINGS, factory=None, http=http, db=None)
        market.delegations = [("unit-test-placeholder", UUID(int=1))]
        market.pool_id = UUID(int=2)
        await market.buyers()
    assert not any(step["ok"] for step in market.report["buyer_agents"])


@pytest.mark.parametrize("failure", [None, "buyer", "merchant", "breach", "payment"])
def test_market_exit_gate_refuses_failed_participation(failure: str | None) -> None:
    from tools import agent_market

    report: dict[str, Any] = {
        "buyer_agents": [{"ok": failure != "buyer"}],
        "merchant_agents": [{"ok": failure != "merchant"}],
        "breaches_succeeded": int(failure == "breach"),
        "paypal_writes_from_ai_surface": int(failure == "payment"),
    }
    assert agent_market.report_succeeded(report) is (failure is None)


def test_market_cli_runs_actual_buyer_and_merchant_paths(migrated_db: None, tmp_path: Any) -> None:
    import subprocess
    import sys
    from pathlib import Path

    output = tmp_path / "market.json"
    result = subprocess.run(
        [sys.executable, "tools/agent_market.py", "--self-check", "--out", str(output)],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, "the actual market CLI must complete every participant action"
    report = json.loads(output.read_text())
    assert all(step["ok"] for step in report["buyer_agents"] + report["merchant_agents"])
    assert report["buyer_agents"][0]["hint"] is not None
    assert report["breaches_succeeded"] == report["paypal_writes_from_ai_surface"] == 0
