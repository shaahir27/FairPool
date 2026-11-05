"""T06A07: the merchant key lifecycle over HTTP, and PT-15 through a key's principal.

What the contract puts at the edge (``api.md`` section 4.2, ``db-schema.md``
``merchant_api_keys``):

* create answers 201 with the secret once, and the row keeps only its HMAC;
* the list shows the prefix and never anything that could be recombined into a key;
* creating a key needs the three attestations, so a bot cannot bid for a merchant who
  has not accepted the rules (FR-IG-04);
* revoke stops the key immediately and keeps the row the audit names;
* every refusal is the same ``API_KEY_INVALID``, and a key can read only its own
  merchant's bids (PT-15).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.merchant_api.app import app as merchant_api_app
from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.modules.merchants.api_keys import hash_key
from fairpool.modules.merchants.auth import PostgresMerchantAuth
from fairpool.ports import MerchantPrincipal
from tests.integration.test_bid_sealing import (
    bidding_world,
    lot_with_deadline,
    service,
    structured,
)
from tests.integration.test_join_receipts import PASSWORD, login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
HMAC_KEY = SETTINGS.hmac_key.get_secret_value()
ATTESTED = {
    key: {"accepted": True}
    for key in ("inventory_reserved", "map_compliance", "delivery_terms_accurate")
}
KEY_SHAPE = re.compile(r"^fpm_[0-9a-f]{8}_[A-Za-z0-9_-]{43}$")


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


async def merchant(
    client: httpx.AsyncClient, db_session: AsyncSession, email: str, *, attested: bool = True
) -> tuple[str, UUID]:
    """A merchant account: its console CSRF token and its ``merchants`` row id."""
    await login(client, email)
    await db_session.execute(
        text("UPDATE users SET role = 'merchant' WHERE email = :email"), {"email": email}
    )
    await db_session.flush()
    result = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200
    csrf = str(result.json()["csrf_token"])
    profile = await client.post(
        "/api/v1/merchant/profile",
        headers={"X-CSRF-Token": csrf},
        json={
            "display_name": f"Merchant {email[:5]}",
            "payee_email": email,
            "attestations": ATTESTED if attested else {},
        },
    )
    assert profile.status_code == 200, profile.text
    return csrf, UUID(str(profile.json()["merchant_id"]))


def key_auth() -> PostgresMerchantAuth:
    return PostgresMerchantAuth(clock=DbClock(), hmac_key=HMAC_KEY)


async def stored_key(db_session: AsyncSession, key_id: UUID) -> dict[str, Any]:
    row = await db_session.execute(
        text(
            "SELECT key_prefix, key_hash, scopes, last_used_at, revoked_at, name "
            "FROM merchant_api_keys WHERE id = :id"
        ),
        {"id": str(key_id)},
    )
    return dict(row.mappings().one())


async def create_key(
    client: httpx.AsyncClient, csrf: str, scopes: list[str], *, name: str = "bot"
) -> dict[str, Any]:
    created = await client.post(
        "/api/v1/merchant/api-keys",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "scopes": scopes},
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def test_create_shows_the_secret_once_and_stores_only_its_hmac(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, _ = await merchant(client, db_session, "once@example.test")
    body = await create_key(client, csrf, ["lots:read", "bids:write"], name="pricing-bot")
    assert set(body) == {"id", "name", "key", "scopes"}
    assert body["name"] == "pricing-bot"
    assert body["scopes"] == ["bids:write", "lots:read"]
    assert KEY_SHAPE.match(body["key"]), body["key"]

    row = await stored_key(db_session, UUID(body["id"]))
    assert row["key_hash"] == hash_key(HMAC_KEY, body["key"])
    assert body["key"].split("_")[1] == row["key_prefix"]
    assert row["revoked_at"] is None
    assert row["last_used_at"] is None
    # Nothing that carries the secret is written to the audit trail (I14). The ``_`` in a
    # LIKE pattern is a single-character wildcard, so this is a looser search than the
    # exact key and still finds nothing.
    leaked = await db_session.scalar(
        text("SELECT count(*) FROM audit_log WHERE payload::text LIKE :like"),
        {"like": f"%{body['key']}%"},
    )
    assert int(leaked or 0) == 0

    listed = await client.get("/api/v1/merchant/api-keys")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert set(items[0]) == {"id", "name", "key_prefix", "scopes", "last_used_at", "revoked_at"}
    assert items[0]["key_prefix"] == row["key_prefix"]


async def test_a_key_acts_as_its_own_merchant_and_stops_being_one_when_revoked(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, merchant_id = await merchant(client, db_session, "acts@example.test")
    body = await create_key(client, csrf, ["bids:read"])
    key_id = UUID(body["id"])

    principal = await key_auth().from_api_key(db_session, body["key"])
    assert principal.merchant_id == merchant_id
    assert principal.via == "api_key"
    assert principal.scopes == frozenset({"bids:read"})
    assert (await stored_key(db_session, key_id))["last_used_at"] is not None

    revoked = await client.delete(
        f"/api/v1/merchant/api-keys/{key_id}", headers={"X-CSRF-Token": csrf}
    )
    assert revoked.status_code == 200, revoked.text
    assert (await stored_key(db_session, key_id))["revoked_at"] is not None
    with pytest.raises(ApplicationError) as caught:
        await key_auth().from_api_key(db_session, body["key"])
    assert caught.value.code == "API_KEY_INVALID"

    actions = await db_session.scalars(
        text("SELECT action FROM audit_log WHERE subject_type = 'merchant_api_key'")
    )
    assert sorted(str(action) for action in actions) == [
        "merchant_api_key.created",
        "merchant_api_key.revoked",
    ]
    # Revoking twice is not an error and writes no second audit row.
    again = await client.delete(
        f"/api/v1/merchant/api-keys/{key_id}", headers={"X-CSRF-Token": csrf}
    )
    assert again.status_code == 200
    actions = await db_session.scalars(
        text("SELECT count(*) FROM audit_log WHERE action = 'merchant_api_key.revoked'")
    )
    assert int(list(actions)[0]) == 1


async def test_an_unknown_or_malformed_key_is_the_same_answer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """No branch here discloses whether a prefix exists (``api.md`` section 4.3)."""
    csrf, _ = await merchant(client, db_session, "refuse@example.test")
    await create_key(client, csrf, ["lots:read"])
    for bearer in (
        f"fpm_deadbeef_{'x' * 43}",  # a well-formed key that was never issued
        f"fpn_deadbeef_{'x' * 43}",  # our shape, a prefix that is not ours
        "fpm_dead_beef",  # malformed
        "fpm_deadbeef_",  # the prefix with no secret
    ):
        with pytest.raises(ApplicationError) as caught:
            await key_auth().from_api_key(db_session, bearer)
        assert caught.value.code == "API_KEY_INVALID"


async def test_a_second_merchant_cannot_revoke_another_merchants_key(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, _ = await merchant(client, db_session, "owner@example.test")
    body = await create_key(client, csrf, ["lots:read"])
    key_id = UUID(body["id"])
    other_csrf, _ = await merchant(client, db_session, "other@example.test")

    stolen = await client.delete(
        f"/api/v1/merchant/api-keys/{key_id}", headers={"X-CSRF-Token": other_csrf}
    )
    missing = await client.delete(
        f"/api/v1/merchant/api-keys/{uuid4()}", headers={"X-CSRF-Token": other_csrf}
    )
    # Not there, rather than forbidden: a 403 would confirm the key exists (I11).
    assert stolen.status_code == 404
    assert missing.status_code == 404
    assert (await stored_key(db_session, key_id))["revoked_at"] is None


async def test_an_unattested_merchant_gets_no_key_and_a_bad_scope_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, _ = await merchant(client, db_session, "raw@example.test", attested=False)
    refused = await client.post(
        "/api/v1/merchant/api-keys",
        headers={"X-CSRF-Token": csrf},
        json={"name": "bot", "scopes": ["lots:read"]},
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"

    attested_csrf, _ = await merchant(client, db_session, "ready@example.test")
    for payload in (
        {"name": "bot", "scopes": ["admin:write"]},
        {"name": "bot", "scopes": []},
        {"name": "", "scopes": ["lots:read"]},
    ):
        bad = await client.post(
            "/api/v1/merchant/api-keys", headers={"X-CSRF-Token": attested_csrf}, json=payload
        )
        assert bad.status_code == 422, bad.text
        assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    listed = await client.get("/api/v1/merchant/api-keys", headers={"X-CSRF-Token": attested_csrf})
    assert listed.json()["items"] == []


async def test_the_121st_request_in_a_minute_is_rate_limited(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """config-and-errors.md section 3: 120 a minute per key, and nothing is exempt."""
    from fairpool.api.deps import MERCHANT_KEY_LIMIT

    csrf, _ = await merchant(client, db_session, "limit@example.test")
    body = await create_key(client, csrf, ["lots:read"])
    limited_app = create_app(SETTINGS.model_copy(update={"rate_limit_enabled": True}))

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    limited_app.dependency_overrides[database_session] = session
    # The mounted sub-app solves its own dependencies, so its override is separate.
    merchant_api_app.dependency_overrides[database_session] = session
    headers = {"Authorization": f"Bearer {body['key']}"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=limited_app), base_url="https://api.test"
        ) as http:
            for _ in range(MERCHANT_KEY_LIMIT):
                allowed = await http.get("/merchant-api/v1/lots", headers=headers)
                assert allowed.status_code == 200, allowed.text
            refused = await http.get("/merchant-api/v1/lots", headers=headers)
    finally:
        merchant_api_app.dependency_overrides.clear()

    assert refused.status_code == 429, refused.text
    assert refused.json()["error"]["code"] == "RATE_LIMITED"
    assert int(refused.headers["Retry-After"]) >= 1


async def test_key_auth_reads_the_key_without_a_row_lock(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A ``FOR UPDATE`` here queues every concurrent request that shares one key."""
    csrf, _ = await merchant(client, db_session, "nolock@example.test")
    body = await create_key(client, csrf, ["lots:read"])
    statements: list[str] = []
    connection = db_session.bind
    assert connection is not None
    sync_connection = connection.sync_connection  # type: ignore[union-attr]

    def capture(*args: Any, **kwargs: Any) -> None:
        statements.append(str(args[2]))

    event.listen(sync_connection, "before_cursor_execute", capture)
    try:
        await key_auth().from_api_key(db_session, body["key"])
    finally:
        event.remove(sync_connection, "before_cursor_execute", capture)
    reads = [statement for statement in statements if "merchant_api_keys" in statement]
    assert reads, statements
    assert not any("FOR UPDATE" in statement.upper() for statement in reads)


async def test_pt15_a_key_never_reads_another_merchants_bid(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PT-15: the principal a key resolves to is the only merchant it can see (INT-9)."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)

    alpha_csrf, alpha_merchant = await merchant(client, db_session, "alpha15@example.test")
    saved = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": alpha_csrf},
        json={"structured": structured()},
    )
    assert saved.status_code == 200, saved.text
    bid_id = UUID(saved.json()["bid_id"])

    beta_csrf, beta_merchant = await merchant(client, db_session, "beta15@example.test")
    body = await create_key(client, beta_csrf, ["bids:read"])
    principal: MerchantPrincipal = await key_auth().from_api_key(db_session, body["key"])
    assert principal.merchant_id == beta_merchant

    with pytest.raises(ApplicationError) as caught:
        await service().get(db_session, merchant_id=principal.merchant_id, bid_id=bid_id)
    assert caught.value.code == "NOT_FOUND"

    # The same read succeeds for the merchant that owns the bid, so the refusal seals.
    bid, _revision, _flags = await service().get(
        db_session, merchant_id=alpha_merchant, bid_id=bid_id
    )
    assert bid.merchant_id == alpha_merchant
