"""T07A05: the Agent API entries lane (api.md section 4.4, FR-AG-01, FR-SL-03).

Proves the acceptance bullets: list and search, ``max_total_usd`` normalisation,
the body idempotency key, scope and cap enforcement, the flat list and withdraw
forms, the allocation/offer view, and that a delegation holder joins through the
same validator and join service the web flow uses (F15). No route here can pay.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.fakes.vault import FakePaymentVaultProvider
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher
from fairpool.modules.pools.vault import VaultService
from tests.integration.test_agent_delegations import create_delegation
from tests.integration.test_join_receipts import login, open_pool, settings_for
from tests.unit.test_settings import vault_key

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
FUTURE = "2099-01-01T00:00:00Z"
REQUIRED_BY = "2026-12-01"
CHECK_HINT = "A human approves payment on PayPal; this API cannot pay."


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


async def buyer(
    client: httpx.AsyncClient,
    email: str,
    *,
    scope: dict[str, Any] | None = None,
    max_cap_cents: int = 60000,
) -> tuple[str, UUID, UUID]:
    """A signed-in buyer with one delegation: (token, user_id, delegation_id)."""
    csrf = await login(client, email)
    created = await create_delegation(
        client, csrf, scope=scope, max_cap_cents=max_cap_cents, expires_at=FUTURE
    )
    me = await client.get("/api/v1/me")
    return created["token"], UUID(str(me.json()["user_id"])), UUID(str(created["id"]))


def agent(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def request_body(pool_id: UUID, **overrides: Any) -> dict[str, Any]:
    request: dict[str, Any] = {
        "delivery": {"region": "NY"},
        "required_by": REQUIRED_BY,
        "max_total_usd": "600.00",
        "firm": [],
        "preferences": [],
    }
    request.update(overrides)
    return {"pool_id": str(pool_id), "request": request}


async def test_agent_join_uses_the_web_validator_and_records_the_delegation(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, user_id, delegation_id = await buyer(client, "agent-join@example.test")
    pool_id = await open_pool(db_session)

    created = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "join-one"},
        json=request_body(pool_id),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["already_entered"] is False
    assert body["pool_id"] == str(pool_id)
    assert body["entry_status"] == "SUBMITTED"
    assert body["checkout_hint"] == CHECK_HINT
    assert body["allocation"] is None and body["offer"] is None
    assert body["checkout_url"] is None

    row = (
        await db_session.execute(
            text(
                "SELECT user_id, cap_cents, submitted_via::text, delegation_id "
                "FROM pool_entries WHERE id = :id"
            ),
            {"id": body["entry_id"]},
        )
    ).one()
    assert row.user_id == user_id
    assert row.cap_cents == 60000
    assert row.submitted_via == "agent"
    assert row.delegation_id == delegation_id


async def test_agent_join_is_idempotent_and_never_confirms_twice(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, user_id, _ = await buyer(client, "agent-replay@example.test")
    pool_id = await open_pool(db_session)
    headers = {**agent(token), "Idempotency-Key": "replay-1"}

    first = await client.post("/agent/v1/entries", headers=headers, json=request_body(pool_id))
    assert first.status_code == 201, first.text
    replay = await client.post("/agent/v1/entries", headers=headers, json=request_body(pool_id))
    assert replay.status_code == 200, replay.text
    assert replay.json()["entry_id"] == first.json()["entry_id"]

    confirmations = await db_session.scalar(
        text("SELECT count(*) FROM confirmed_requests WHERE user_id = :id"), {"id": user_id}
    )
    entries = await db_session.scalar(
        text("SELECT count(*) FROM pool_entries WHERE pool_id = :id"), {"id": pool_id}
    )
    assert (confirmations, entries) == (1, 1)


async def test_agent_idempotency_key_header_and_body_forms(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-key-forms@example.test")
    pool_id = await open_pool(db_session)

    missing = await client.post(
        "/agent/v1/entries", headers=agent(token), json=request_body(pool_id)
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    mismatch = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "header-key"},
        json={**request_body(pool_id), "idempotency_key": "body-key"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    body_only = await client.post(
        "/agent/v1/entries",
        headers=agent(token),
        json={**request_body(pool_id), "idempotency_key": "body-only-key"},
    )
    assert body_only.status_code == 201, body_only.text

    too_long = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "k" * 129},
        json=request_body(pool_id),
    )
    assert too_long.status_code == 422


async def test_agent_cap_and_scope_are_enforced(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-cap@example.test", max_cap_cents=50000)
    pool_id = await open_pool(db_session)

    over = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "cap-1"},
        json=request_body(pool_id),
    )
    assert over.status_code == 403
    assert over.json()["error"]["code"] == "DELEGATION_CAP_EXCEEDED"

    other_pool = await buyer(
        client, "agent-scope-pool@example.test", scope={"pool_ids": [str(uuid4())]}
    )
    out_of_pool = await client.post(
        "/agent/v1/entries",
        headers={**agent(other_pool[0]), "Idempotency-Key": "scope-1"},
        json=request_body(pool_id),
    )
    assert out_of_pool.status_code == 404
    assert out_of_pool.json()["error"]["code"] == "NOT_FOUND"

    category = await buyer(
        client, "agent-scope-category@example.test", scope={"category": "monitors"}
    )
    wrong_category = await client.post(
        "/agent/v1/entries",
        headers={**agent(category[0]), "Idempotency-Key": "scope-2"},
        json=request_body(pool_id),
    )
    assert wrong_category.status_code == 404


async def test_agent_money_forms_are_exclusive_and_exact(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-money@example.test")
    pool_id = await open_pool(db_session)
    both = request_body(pool_id, max_total_cents=60000)
    neither = request_body(pool_id, max_total_usd=None)
    malformed = request_body(pool_id, max_total_usd="600.000")
    for index, body in enumerate((both, neither, malformed)):
        response = await client.post(
            "/agent/v1/entries",
            headers={**agent(token), "Idempotency-Key": f"money-{index}"},
            json=body,
        )
        assert response.status_code == 422, response.text

    # An unsupported firm term is the validator's rejection, not a silent change.
    unsupported = request_body(pool_id, firm=["free shipping"])
    rejected = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "money-firm"},
        json=unsupported,
    )
    assert rejected.status_code == 422


async def test_agent_lists_and_reads_only_its_own_entries(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-read@example.test")
    pool_id = await open_pool(db_session)
    created = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "read-1"},
        json=request_body(pool_id),
    )
    entry_id = created.json()["entry_id"]

    single = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(token))
    assert single.status_code == 200, single.text
    assert single.json()["entry_id"] == entry_id

    filtered = await client.get(f"/agent/v1/entries?pool_id={pool_id}", headers=agent(token))
    assert filtered.status_code == 200
    assert [item["entry_id"] for item in filtered.json()["items"]] == [entry_id]

    by_id = await client.get(f"/agent/v1/entries?entry_id={entry_id}", headers=agent(token))
    assert [item["entry_id"] for item in by_id.json()["items"]] == [entry_id]
    unknown = await client.get(f"/agent/v1/entries/{uuid4()}", headers=agent(token))
    assert unknown.status_code == 404

    outsider, _, _ = await buyer(client, "agent-read-other@example.test")
    denied = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(outsider))
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "NOT_FOUND"


async def test_agent_withdraw_is_idempotent_and_owner_scoped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-withdraw@example.test")
    pool_id = await open_pool(db_session)
    created = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "withdraw-1"},
        json=request_body(pool_id),
    )
    entry_id = created.json()["entry_id"]

    outsider, _, _ = await buyer(client, "agent-withdraw-other@example.test")
    denied = await client.post(
        "/agent/v1/entries/withdraw", headers=agent(outsider), json={"entry_id": entry_id}
    )
    assert denied.status_code == 404

    first = await client.post(
        "/agent/v1/entries/withdraw", headers=agent(token), json={"entry_id": entry_id}
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"entry_id": entry_id, "entry_status": "WITHDRAWN"}
    again = await client.post(
        "/agent/v1/entries/withdraw", headers=agent(token), json={"entry_id": entry_id}
    )
    assert again.status_code == 200
    assert again.json() == first.json()

    status = await db_session.scalar(
        text("SELECT status::text FROM pool_entries WHERE id = :id"), {"id": entry_id}
    )
    assert status == "WITHDRAWN"

    # The DELETE form reaches the same withdrawal for clients that use a path.
    second_pool = await open_pool(db_session)
    second = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "withdraw-2"},
        json=request_body(second_pool),
    )
    deleted = await client.delete(
        f"/agent/v1/entries/{second.json()['entry_id']}", headers=agent(token)
    )
    assert deleted.status_code == 200
    assert deleted.json()["entry_status"] == "WITHDRAWN"


async def test_a_narrowed_delegation_reads_and_withdraws_nothing_outside_its_scope(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The scope that gates a join gates every read and the withdrawal (I11)."""
    csrf = await login(client, "agent-scope-read@example.test")
    open_token = (await create_delegation(client, csrf))["token"]
    pool_id = await open_pool(db_session)
    created = await client.post(
        "/agent/v1/entries",
        headers={**agent(open_token), "Idempotency-Key": "scope-read-1"},
        json=request_body(pool_id),
    )
    assert created.status_code == 201, created.text
    entry_id = created.json()["entry_id"]

    other_pool = await open_pool(db_session)
    narrowed = (await create_delegation(client, csrf, scope={"pool_ids": [str(other_pool)]}))[
        "token"
    ]
    category = (await create_delegation(client, csrf, scope={"category": "monitors"}))["token"]

    listed = await client.get("/agent/v1/entries", headers=agent(narrowed))
    assert listed.status_code == 200
    assert listed.json()["items"] == []

    for token in (narrowed, category):
        read = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(token))
        assert read.status_code == 404
        assert read.json()["error"]["code"] == "NOT_FOUND"
        withdraw = await client.post(
            "/agent/v1/entries/withdraw", headers=agent(token), json={"entry_id": entry_id}
        )
        assert withdraw.status_code == 404
        assert withdraw.json()["error"]["code"] == "NOT_FOUND"

    # Neither refusal changed anything: the wider delegation still reads the entry.
    still = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(open_token))
    assert still.status_code == 200, still.text
    assert still.json()["entry_status"] == "SUBMITTED"


async def test_agent_withdraw_never_deletes_the_saved_permission(
    db_session: AsyncSession,
) -> None:
    """Rule 22: the agent lane withdraws the entry and never performs a PayPal write."""
    settings = settings_for(vault_token_key=vault_key(), vault_real_save_enabled=True)
    provider = FakePaymentVaultProvider()
    app = create_app(settings)
    app.state.vault_provider = provider

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        token, _, _ = await buyer(http, "agent-vault@example.test")
        pool_id = await open_pool(db_session)
        created = await http.post(
            "/agent/v1/entries",
            headers={**agent(token), "Idempotency-Key": "vault-withdraw"},
            json=request_body(pool_id),
        )
        assert created.status_code == 201, created.text
        entry_id = UUID(str(created.json()["entry_id"]))

        # A live saved permission exists, so the old vault leg would have deleted it.
        vault = VaultService(
            DbClock(),
            PostgresAuditLog(),
            AesGcmCipher.from_config_value(vault_key()),
            provider,
            consent_version="v1",
            setup_ttl_s=900,
            real_save_enabled=True,
        )
        redirect = await vault.start(db_session, entry_id=entry_id)
        await vault.complete(db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id)

        withdrawn = await http.post(
            "/agent/v1/entries/withdraw", headers=agent(token), json={"entry_id": str(entry_id)}
        )
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json() == {
            "entry_id": str(entry_id),
            "entry_status": "WITHDRAWN",
        }

    assert [call for call in provider.calls if call.startswith("delete:")] == []
    status = await db_session.scalar(
        text("SELECT status::text FROM vault_tokens WHERE entry_id = :id"), {"id": entry_id}
    )
    assert status == "ACTIVE", "the saved permission waits for the buyer's settings page"


async def test_agent_views_allocation_and_offer_for_the_human_hand_off(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-view@example.test")
    pool_id = await open_pool(db_session)
    created = await client.post(
        "/agent/v1/entries",
        headers={**agent(token), "Idempotency-Key": "view-1"},
        json=request_body(pool_id),
    )
    entry_id = UUID(str(created.json()["entry_id"]))

    lot_id = uuid4()
    now = datetime.now(UTC)
    await db_session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, 'US-EAST', 0, 0, 2, 1, "
            "'BIDDING', :open_at, :close_at)"
        ),
        {
            "id": lot_id,
            "pool": pool_id,
            "open_at": now - timedelta(minutes=5),
            "close_at": now + timedelta(hours=1),
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, "
            "lot_id, status) VALUES (:id, :pool, :entry, 'US-EAST', 5, :hash, NULL, "
            "'WAITLISTED')"
        ),
        {"id": uuid4(), "pool": pool_id, "entry": entry_id, "hash": "b" * 64},
    )
    order_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, total_cents, breakdown, "
            "offer_expires_at) VALUES (:id, :lot, :entry, 'OFFERED', 52613, CAST('{}' AS jsonb), "
            ":expires)"
        ),
        {"id": order_id, "lot": lot_id, "entry": entry_id, "expires": now + timedelta(minutes=3)},
    )

    waiting = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(token))
    assert waiting.status_code == 200, waiting.text
    body = waiting.json()
    assert body["allocation"] == {
        "status": "WAITLISTED",
        "zone_id": "US-EAST",
        "rank": 5,
        "lot_id": None,
        "waitlist_position": 3,
    }
    assert body["offer"]["buyer_order_id"] == str(order_id)
    assert body["offer"]["status"] == "OFFERED"
    assert body["checkout_url"] == f"{SETTINGS.frontend_base_url}/offers/{order_id}"

    await db_session.execute(
        text("UPDATE allocations SET status = 'SEATED', lot_id = :lot WHERE pool_id = :pool"),
        {"lot": lot_id, "pool": pool_id},
    )
    seated = await client.get(f"/agent/v1/entries/{entry_id}", headers=agent(token))
    allocation = seated.json()["allocation"]
    assert allocation["status"] == "SEATED"
    assert allocation["lot_id"] == str(lot_id)
    assert allocation["waitlist_position"] is None


async def test_agent_pools_lists_open_pools_and_searches(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await buyer(client, "agent-pools@example.test")
    pool_id = await open_pool(db_session)
    title = f"Agent API pool {pool_id}"
    await db_session.execute(
        text("UPDATE pools SET title = :title, search_text = :title WHERE id = :id"),
        {"title": title, "id": pool_id},
    )

    listed = await client.get("/agent/v1/pools", headers=agent(token))
    assert listed.status_code == 200, listed.text
    items = listed.json()
    assert items, "the disposable database has at least one open pool"
    assert set(items[0]) == {"pool_id", "title", "status", "template", "timeline", "rules_hash"}
    assert {item["status"] for item in items} == {"OPEN"}

    # The unique title makes the search answer deterministic even when the
    # disposable database holds other suites' open pools.
    searched = await client.get("/agent/v1/pools", headers=agent(token), params={"q": title})
    assert searched.status_code == 200, searched.text
    assert [item["pool_id"] for item in searched.json()] == [str(pool_id)]
    assert searched.json()[0]["rules_hash"] == "a" * 64
    assert searched.json()[0]["template"]["product_key"] == "monitor-27-4k"

    empty = await client.get("/agent/v1/pools?q=nothing-matches-this", headers=agent(token))
    assert empty.status_code == 200
    assert empty.json() == []


async def test_agent_pools_only_lists_pools_the_delegation_may_enter(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The scope that gates a join gates the pool search too (I11)."""
    csrf = await login(client, "agent-pools-scope@example.test")
    mine = await open_pool(db_session)
    other = await open_pool(db_session)
    other_title = f"Agent API pool outside the scope {other}"
    await db_session.execute(
        text("UPDATE pools SET title = :title, search_text = :title WHERE id = :id"),
        {"title": other_title, "id": other},
    )
    token = (await create_delegation(client, csrf, scope={"pool_ids": [str(mine)]}))["token"]

    listed = await client.get("/agent/v1/pools", headers=agent(token))
    assert listed.status_code == 200, listed.text
    assert [item["pool_id"] for item in listed.json()] == [str(mine)]

    searched = await client.get("/agent/v1/pools", headers=agent(token), params={"q": other_title})
    assert searched.status_code == 200, searched.text
    assert searched.json() == []


async def test_me_entries_reads_the_page_in_a_constant_number_of_queries(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """The buyer list must not get slower per entry: the page reads in one pass.

    The first draft asked twice per entry (allocation, offer), which is invisible
    with one row and a round-trip storm with a real history. Four entries fit in
    five SELECTs including the session lookup; per-entry reads needed nine.
    """
    token, _, _ = await buyer(client, "me-entries-page@example.test")
    for _ in range(4):
        pool_id = await open_pool(db_session)
        joined = await client.post(
            "/agent/v1/entries",
            headers={**agent(token), "Idempotency-Key": str(uuid4())},
            json=request_body(pool_id),
        )
        assert joined.status_code in {200, 201}, joined.text

    bind = db_session.get_bind()
    target = getattr(bind, "sync_engine", getattr(bind, "engine", bind))
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(target, "before_cursor_execute", record)
    try:
        listed = await client.get("/api/v1/me/entries")
    finally:
        event.remove(target, "before_cursor_execute", record)

    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) >= 4
    assert len(statements) <= 5, f"{len(statements)} SELECTs for one page of entries"
