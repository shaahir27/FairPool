"""T03B03: Log in with PayPal linking (api.md "Account link", CR-3, paypal-adapter 7a).

Fake versus real, in one line: every provider call below goes through the
``PayPalIdentity`` port into ``FakePayPalIdentity``, which opens no connection,
holds no credential and returns local fixture identifiers. What this file proves is
the state ladder, single use, session binding, keyed storage, the decline and
conflict paths and the relink block. What it cannot prove is a live PayPal login
round trip: that is S1's hand-run Sandbox evidence and the Phase 4 adapter.

HTTP tests run with ``RATE_LIMIT_ENABLED=false`` so the outcomes, not the limiter,
are what the suite proves (config-and-errors.md section 3).
"""

from __future__ import annotations

import ast
import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.config import Settings
from fairpool.db.models.identity import PayPalLink
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.paypal_identity import FAKE_ALICE, FAKE_BOB, FakePayPalIdentity
from fairpool.fakes.vault import FakePaymentVaultProvider
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, key_from_config_value
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.logging import JsonFormatter, RedactionFilter
from fairpool.modules.identity.paypal_login import PayPalLoginService, account_key
from fairpool.modules.identity.service import IdentityService
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import signing_seed
from fairpool.modules.pools.vault import VaultService
from fairpool.ports import PayPalIdentity
from tests.integration.test_triggers import iso_in
from tests.unit.test_settings import make_settings, vault_key

PASSWORD = "a-secure-password"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "fairpool"
#: Local fixture values only: a code nobody issued and the identifier it profiles.
CODE = "fake-code-alice"
RAW_ID = FAKE_ALICE
ACCESS_TOKEN = "fake-access-token-1"
SEED = base64.urlsafe_b64encode(b"receipt-signing-secret-32bytes!!").decode().rstrip("=")


def login_settings(**overrides: Any) -> Settings:
    return make_settings(paypal_login_enabled=True, rate_limit_enabled=False, **overrides)


def service_for(settings: Settings, identity: FakePayPalIdentity) -> PayPalLoginService:
    """The same construction the route does, on the fake port."""
    return PayPalLoginService(
        identity,
        DbClock(),
        PostgresAuditLog(),
        # Read from the same setting the route reads, used only to recompute the
        # expected digest; never printed (rule 2).
        hmac_key=settings.hmac_key.get_secret_value(),
        dedupe_mode=settings.dedupe_mode,
        enabled=settings.paypal_login_enabled,
        client_id=settings.paypal_client_id,
        redirect_uri=settings.paypal_login_redirect_uri,
        checkout_base=settings.paypal_checkout_base,
        state_ttl_s=settings.oauth_state_ttl_s,
    )


def expected_key(settings: Settings, identifier: str) -> str:
    return account_key(settings.hmac_key.get_secret_value(), identifier)


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def session_id_of(cookie_value: str) -> uuid.UUID:
    """The opaque session id the session cookie carries: ``<uuid>.<signature>``."""
    return uuid.UUID(cookie_value.split(".", 1)[0])


async def state_row(db: AsyncSession, state: str) -> Any:
    return (
        await db.execute(
            text(
                "SELECT state, nonce, user_id, session_id, expires_at, consumed_at "
                "FROM oauth_states WHERE state = :state"
            ),
            {"state": state},
        )
    ).first()


async def link_rows(db: AsyncSession, user_id: uuid.UUID) -> list[Any]:
    return list(
        (
            await db.execute(
                text(
                    "SELECT id, paypal_account_key, linked_at, revoked_at FROM paypal_links "
                    "WHERE user_id = :u ORDER BY linked_at, id"
                ),
                {"u": user_id},
            )
        ).all()
    )


async def audit_payloads(db: AsyncSession, actor: uuid.UUID) -> list[str]:
    return list(
        (
            await db.execute(
                text("SELECT payload::text FROM audit_log WHERE actor = :a"), {"a": str(actor)}
            )
        )
        .scalars()
        .all()
    )


async def link_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Counted per buyer: the test database is shared, so a global count proves nothing."""
    return int(
        await db.scalar(
            text("SELECT count(*) FROM paypal_links WHERE user_id = :u"), {"u": user_id}
        )
        or 0
    )


async def state_count(db: AsyncSession, user_id: uuid.UUID, *, consumed: bool | None = None) -> int:
    clause = ""
    if consumed is True:
        clause = "AND consumed_at IS NOT NULL"
    elif consumed is False:
        clause = "AND consumed_at IS NULL"
    return int(
        await db.scalar(
            text(f"SELECT count(*) FROM oauth_states WHERE user_id = :u {clause}"), {"u": user_id}
        )
        or 0
    )


class SecretCapture(logging.Handler):
    """The production redaction path (filter, then JSON format), captured in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.addFilter(RedactionFilter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(JsonFormatter().format(record))


# --------------------------------------------------------------------- clients


@pytest.fixture
async def env(db_session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
    """One app, one fake identity, and as many cookie jars as a test needs."""
    settings = login_settings()
    identity = FakePayPalIdentity()
    app = create_app(settings)
    app.state.paypal_identity = identity

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    opened: list[httpx.AsyncClient] = []

    def client() -> httpx.AsyncClient:
        made = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        )
        opened.append(made)
        return made

    yield {"settings": settings, "identity": identity, "client": client, "db": db_session}
    for made in opened:
        await made.aclose()


async def register(client: httpx.AsyncClient, email: str) -> None:
    result = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "display_name": "Buyer " + email[:6]},
    )
    assert result.status_code == 200, result.text


async def sign_in(client: httpx.AsyncClient, email: str) -> str:
    """Log in on this jar and return the CSRF token; a second call makes a second session."""
    result = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert result.status_code == 200, result.text
    return str(result.json()["csrf_token"])


async def new_buyer(client: httpx.AsyncClient, email: str) -> tuple[str, uuid.UUID]:
    await register(client, email)
    csrf = await sign_in(client, email)
    return csrf, await me_id(client)


async def me_id(client: httpx.AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])


async def start(client: httpx.AsyncClient) -> tuple[str, str]:
    """Run ``login/start`` and return (authorize URL, the state it carries)."""
    response = await client.get("/api/v1/paypal/login/start")
    assert response.status_code == 200, response.text
    url = str(response.json()["authorize_url"])
    return url, query(url)["state"]


async def callback(
    client: httpx.AsyncClient, *, code: str | None = CODE, state: str | None
) -> httpx.Response:
    params: dict[str, str] = {}
    if code is not None:
        params["code"] = code
    if state is not None:
        params["state"] = state
    return await client.get("/api/v1/paypal/login/callback", params=params)


def error_code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


async def link_via_http(client: httpx.AsyncClient, code: str = CODE) -> str:
    """The whole flow for this jar; returns the state it consumed."""
    _, state = await start(client)
    result = await callback(client, code=code, state=state)
    assert result.status_code == 200, result.text
    return state


# ----------------------------------------------------------------------- start


async def test_start_writes_one_state_row_bound_to_the_initiating_session(
    env: dict[str, Any],
) -> None:
    """api.md: one single-use row, the caller's session id, database-clock expiry."""
    client, db, settings = env["client"](), env["db"], env["settings"]
    await new_buyer(client, "start-ok@example.test")
    user_id = await me_id(client)

    url, state = await start(client)

    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "www.sandbox.paypal.com"
    params = query(url)
    assert params["scope"] == "openid"  # S1: the account-attributes scope was rejected
    assert params["response_type"] == "code"
    assert params["client_id"] == settings.paypal_client_id
    assert params["redirect_uri"] == settings.paypal_login_redirect_uri
    assert len(params["state"]) >= 32 and len(params["nonce"]) >= 32
    assert params["state"] != params["nonce"]
    assert settings.paypal_client_secret.get_secret_value() not in url
    # api.md: the authorize URL is the only thing this route returns.
    assert sorted((await client.get("/api/v1/paypal/login/start")).json()) == ["authorize_url"]

    rows = (
        (
            await db.execute(
                text("SELECT state FROM oauth_states WHERE user_id = :u"), {"u": user_id}
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2 and state in rows, "one row per start, and no other write"
    row = await state_row(db, state)
    assert row is not None
    assert row.user_id == user_id
    assert row.session_id == session_id_of(str(client.cookies.get("session")))
    assert row.consumed_at is None
    ttl_s = await db.scalar(
        text("SELECT EXTRACT(EPOCH FROM (:expires - now()))::int"), {"expires": row.expires_at}
    )
    # I15: the deadline is the database clock plus OAUTH_STATE_TTL_S, never app time.
    assert settings.oauth_state_ttl_s - 5 <= int(ttl_s) <= settings.oauth_state_ttl_s + 5


async def test_start_needs_an_authenticated_session(env: dict[str, Any]) -> None:
    assert (await env["client"]().get("/api/v1/paypal/login/start")).status_code == 401


# ---------------------------------------------------------------------- callback


async def test_callback_links_and_stores_only_the_hmac_of_the_identifier(
    env: dict[str, Any],
) -> None:
    """BD-12 and 7a: the keyed digest lands in paypal_links; the raw id goes nowhere."""
    client, db, settings = env["client"](), env["db"], env["settings"]
    await new_buyer(client, "link-ok@example.test")
    user_id = await me_id(client)
    _, state = await start(client)

    result = await callback(client, state=state)

    assert result.status_code == 200, result.text
    assert result.json() == {"paypal_linked": True}
    assert env["identity"].calls == ["exchange_code", "userinfo"]

    rows = await link_rows(db, user_id)
    assert len(rows) == 1
    key = str(rows[0].paypal_account_key)
    assert key == expected_key(settings, RAW_ID)
    assert len(key) == 64 and all(char in "0123456789abcdef" for char in key)
    assert rows[0].revoked_at is None
    # two_keys: the digest covers the exact identifier. A stripped prefix would key
    # to something else, so nothing was normalised or matched to a payer id.
    assert key != expected_key(settings, RAW_ID.split("-")[-1])
    assert RAW_ID not in str(list(rows[0]))
    assert (await state_row(db, state)).consumed_at is not None
    assert (await client.get("/api/v1/me")).json()["paypal_linked"] is True
    payloads = await audit_payloads(db, user_id)
    assert payloads and all(RAW_ID not in payload and key not in payload for payload in payloads)


async def test_the_rejection_ladder_refuses_before_any_provider_call(
    env: dict[str, Any],
) -> None:
    """Missing, unknown, expired, consumed and cross-session state refuse in that order."""
    client, db, identity = env["client"](), env["db"], env["identity"]
    await new_buyer(client, "ladder@example.test")
    user_id = await me_id(client)

    missing = await callback(client, code=CODE, state=None)
    assert missing.status_code == 422 and error_code(missing) == "VALIDATION_ERROR"
    no_code = await callback(client, code=None, state="a" * 40)
    assert no_code.status_code == 422 and error_code(no_code) == "VALIDATION_ERROR"

    unknown = await callback(client, code=CODE, state="a-state-nobody-wrote")
    assert unknown.status_code == 403 and error_code(unknown) == "FORBIDDEN"

    _, expired = await start(client)
    await db.execute(
        text("UPDATE oauth_states SET expires_at = now() - interval '1 second' WHERE state = :s"),
        {"s": expired},
    )
    stale = await callback(client, code=CODE, state=expired)
    assert stale.status_code == 403 and error_code(stale) == "FORBIDDEN"
    assert (await state_row(db, expired)).consumed_at is None

    _, live = await start(client)
    # The same buyer's second session may not complete a row minted in the first.
    other = env["client"]()
    await sign_in(other, "ladder@example.test")
    cross = await callback(other, code=CODE, state=live)
    assert cross.status_code == 403 and error_code(cross) == "FORBIDDEN"
    assert (await state_row(db, live)).consumed_at is None

    assert (await callback(client, code=CODE, state=live)).status_code == 200
    calls_after_first_link = list(identity.calls)
    replay = await callback(client, code=CODE, state=live)
    assert replay.status_code == 403 and error_code(replay) == "FORBIDDEN"
    assert identity.calls == calls_after_first_link, "a consumed state cannot call again"
    assert len(await link_rows(db, user_id)) == 1
    assert await link_count(db, user_id) == 1
    assert await state_count(db, user_id, consumed=True) == 1, (
        "exactly one of this buyer's states was ever consumed"
    )


async def test_a_provider_decline_writes_nothing(env: dict[str, Any]) -> None:
    """api.md: ``error=access_denied`` is a 400 decline with no row written."""
    client, db, identity = env["client"](), env["db"], env["identity"]
    _, user_id = await new_buyer(client, "decline@example.test")
    _, state = await start(client)

    declined = await client.get(
        "/api/v1/paypal/login/callback", params={"error": "access_denied", "state": state}
    )

    assert declined.status_code == 400, declined.text
    assert error_code(declined) == "PROVIDER_DECLINED"
    assert identity.calls == []
    assert (await state_row(db, state)).consumed_at is None
    assert await link_count(db, user_id) == 0
    assert await state_count(db, user_id, consumed=True) == 0


async def test_an_unavailable_provider_links_nothing(env: dict[str, Any]) -> None:
    """A failed provider call is 502, and the savepoint leaves no consume and no link."""
    client, db = env["client"](), env["db"]
    env["identity"].failure = "unavailable"
    _, user_id = await new_buyer(client, "unavailable@example.test")
    _, state = await start(client)

    result = await callback(client, state=state)

    assert result.status_code == 502 and error_code(result) == "PAYPAL_UNAVAILABLE"
    assert (await state_row(db, state)).consumed_at is None
    assert await link_count(db, user_id) == 0


async def test_a_code_the_provider_refuses_links_nothing(env: dict[str, Any]) -> None:
    """An unknown grant is the same decline shape: 400, nothing written, no link."""
    client, db = env["client"](), env["db"]
    _, user_id = await new_buyer(client, "bad-code@example.test")
    _, state = await start(client)

    result = await callback(client, code="a-code-nobody-issued", state=state)

    assert result.status_code == 400 and error_code(result) == "PROVIDER_DECLINED"
    assert (await state_row(db, state)).consumed_at is None
    assert await link_count(db, user_id) == 0


async def test_duplicate_link_attempts_are_conflicts(env: dict[str, Any]) -> None:
    """One active link per user, one user per active account key: 409 each way."""
    owner, db = env["client"](), env["db"]
    await new_buyer(owner, "owner@example.test")
    owner_id = await me_id(owner)
    await link_via_http(owner)

    _, second_state = await start(owner)
    again = await callback(owner, code="fake-code-bob", state=second_state)
    assert again.status_code == 409 and error_code(again) == "PAYPAL_LINK_CONFLICT"
    assert len(await link_rows(db, owner_id)) == 1

    # Another buyer holding the same provider account: refused (FR-ID-03).
    stranger = env["client"]()
    await new_buyer(stranger, "stranger@example.test")
    stranger_id = await me_id(stranger)
    _, stranger_state = await start(stranger)
    clash = await callback(stranger, code="fake-code-carol", state=stranger_state)
    assert clash.status_code == 409 and error_code(clash) == "PAYPAL_LINK_CONFLICT"
    assert await link_rows(db, stranger_id) == []
    assert len(await link_rows(db, owner_id)) == 1


async def test_unlink_revokes_the_link_and_is_idempotent(env: dict[str, Any]) -> None:
    client, db = env["client"](), env["db"]
    csrf, _ = await new_buyer(client, "unlink@example.test")
    await link_via_http(client)
    user_id = await me_id(client)

    revoked = await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})

    assert revoked.status_code == 200, revoked.text
    assert revoked.json() == {"paypal_linked": False}
    rows = await link_rows(db, user_id)
    assert len(rows) == 1 and rows[0].revoked_at is not None

    again = await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})
    assert again.status_code == 200
    assert await link_count(db, user_id) == 1, "a repeat revoke writes no second row"


async def test_a_revoked_link_does_not_block_a_later_link(env: dict[str, Any]) -> None:
    """Both unique indexes are partial on active links, so relink after a revoke works."""
    client, db, settings = env["client"](), env["db"], env["settings"]
    csrf, _ = await new_buyer(client, "relink@example.test")
    await link_via_http(client)
    await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})

    _, next_state = await start(client)
    assert (await callback(client, code="fake-code-bob", state=next_state)).status_code == 200

    stored = {
        (str(row.paypal_account_key), row.revoked_at is not None)
        for row in await link_rows(db, await me_id(client))
    }
    assert stored == {
        (expected_key(settings, RAW_ID), True),
        (expected_key(settings, FAKE_BOB), False),
    }


# ------------------------------------------------------------------ feature gate


async def test_disabled_feature_refuses_every_route_and_writes_no_row(
    db_session: AsyncSession,
) -> None:
    """PAYPAL_LOGIN_ENABLED=false: 403 FEATURE_DISABLED, no row, no provider call."""
    identity = FakePayPalIdentity()
    app = create_app(make_settings(paypal_login_enabled=False, rate_limit_enabled=False))
    app.state.paypal_identity = identity

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        csrf, user_id = await new_buyer(client, "gated@example.test")
        responses = [
            await client.get("/api/v1/paypal/login/start"),
            await client.get("/api/v1/paypal/login/callback", params={"code": CODE, "state": "x"}),
            await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf}),
        ]
        for response in responses:
            assert response.status_code == 403, response.text
            assert error_code(response) == "FEATURE_DISABLED"

    assert identity.calls == []
    assert await state_count(db_session, user_id) == 0
    assert await link_count(db_session, user_id) == 0


# ----------------------------------------------------------------------- secrets


async def test_no_credential_or_identifier_appears_in_a_log_line_or_response_body(
    env: dict[str, Any],
) -> None:
    """Rule 2 and 7a: the code, the token, the raw id, the state and the URL stay out."""
    client, db, settings = env["client"](), env["db"], env["settings"]
    csrf, _ = await new_buyer(client, "secrets@example.test")
    _, state = await start(client)
    user_id = await me_id(client)

    handler = SecretCapture()
    # Our own logger tree, at the level production runs it at: the flow's records,
    # not the test client's request bookkeeping.
    app_logger = logging.getLogger("fairpool")
    previous = app_logger.level
    app_logger.addHandler(handler)
    app_logger.setLevel(logging.INFO)
    bodies: list[str] = []
    try:
        bodies.append((await callback(client, state=state)).text)
        bodies.append((await client.get("/api/v1/me")).text)
        url, _ = await start(client)
        bodies.append(json.dumps({"authorize_url": url}))
        bodies.append(
            (await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})).text
        )
    finally:
        app_logger.setLevel(previous)
        app_logger.removeHandler(handler)

    row = await state_row(db, state)
    leaked = {
        "raw identifier": RAW_ID,
        "authorization code": CODE,
        "bearer token": ACCESS_TOKEN,
        "state": state,
        "nonce": str(row.nonce),
        "keyed digest": expected_key(settings, RAW_ID),
        "hmac key": settings.hmac_key.get_secret_value(),
    }
    assert handler.lines, "the flow logged nothing to check"
    for line in handler.lines:
        for label, value in leaked.items():
            assert value not in line, f"the {label} reached a log line"
        assert url not in line, "the authorize URL is never a log line"
    # The one body that may name a state at all is the start response, and it
    # carries its own fresh state, never the one the link consumed (api.md).
    for body in bodies:
        for label, value in leaked.items():
            assert value not in body, f"the {label} reached a response body"

    stored = " ".join(
        (
            await db.execute(
                text(
                    "SELECT paypal_account_key || '|' || coalesce(revoked_at::text, '') "
                    "FROM paypal_links WHERE user_id = :u"
                ),
                {"u": user_id},
            )
        )
        .scalars()
        .all()
    )
    assert RAW_ID not in stored and CODE not in stored
    assert expected_key(settings, RAW_ID) in stored


# ---------------------------------------------------------------- vault separation


def vault_service(provider: FakePaymentVaultProvider | None = None) -> VaultService:
    """The vault lane's port and fake, used through its public service API (DEP-5)."""
    return VaultService(
        DbClock(),
        FakeAuditLog(),
        AesGcmCipher(key_from_config_value(vault_key())),
        provider or FakePaymentVaultProvider(),
        consent_version="v1",
        setup_ttl_s=900,
        real_save_enabled=True,
    )


async def _buyer(db: AsyncSession, email: str) -> Any:
    settings = login_settings()
    identity_service = IdentityService(settings.secret_key.get_secret_value(), DbClock())
    await identity_service.register(
        db, email=email, password=PASSWORD, display_name="Buyer " + email[:6]
    )
    login = await identity_service.login(db, email=email, password=PASSWORD)
    return settings, await identity_service.authenticate(db, login.cookie)


async def test_unlinking_keeps_a_saved_permission(env: dict[str, Any]) -> None:
    """Two separate resources: revoking the login link never deletes a permission."""
    db = env["db"]
    settings, principal = await _buyer(db, "unlink-vault@example.test")
    pool_id = await insert_pool(db)
    entry_id = await join_pool(db, principal.user_id, pool_id)
    vault = vault_service()
    redirect = await vault.start(db, entry_id=entry_id)
    await vault.complete(db, entry_id=entry_id, setup_token_id=redirect.setup_token_id)
    await ensure_active_link(db, principal.user_id, settings, RAW_ID)
    # ES-03 first: an entry that still stands blocks the unlink, and that is F16.
    await join_service().withdraw(db, pool_id=pool_id, user_id=principal.user_id)

    result = await service_for(settings, env["identity"]).unlink(db, principal)

    assert result.revoked is True
    permission = (
        await db.execute(
            text(
                "SELECT status, token_ciphertext IS NOT NULL, token_nonce IS NOT NULL "
                "FROM vault_tokens WHERE entry_id = :e"
            ),
            {"e": entry_id},
        )
    ).first()
    assert str(permission[0]) == "ACTIVE" and permission[1] is True and permission[2] is True
    assert (await link_rows(db, principal.user_id))[-1].revoked_at is not None


async def test_deleting_a_permission_keeps_the_account_link(env: dict[str, Any]) -> None:
    """And the other way round: a deleted permission never unlinks the account."""
    db = env["db"]
    settings, principal = await _buyer(db, "delete-vault@example.test")
    pool_id = await insert_pool(db)
    entry_id = await join_pool(db, principal.user_id, pool_id)
    await ensure_active_link(db, principal.user_id, settings, RAW_ID)
    vault = vault_service()
    redirect = await vault.start(db, entry_id=entry_id)
    await vault.complete(db, entry_id=entry_id, setup_token_id=redirect.setup_token_id)

    deleted = await vault.withdraw(db, entry_id=entry_id)

    assert deleted.status == "DELETED"
    active = (
        (
            await db.execute(
                select(PayPalLink).where(
                    PayPalLink.user_id == principal.user_id, PayPalLink.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(active) == 1
    assert active[0].paypal_account_key == expected_key(settings, RAW_ID)
    # The link table never held a credential either: only the keyed digest.
    assert RAW_ID not in active[0].paypal_account_key


# ------------------------------------------------------------------ static proofs


def imported_names(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def sql_literals(path: Path) -> list[str]:
    return [
        node.value.strip()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lstrip().upper().startswith(("SELECT ", "UPDATE ", "INSERT "))
    ]


def test_the_login_module_reaches_no_host_and_writes_no_other_table() -> None:
    """The boundary is import-shaped, not wording-shaped (rules 1, 2, 3, 14, 27)."""
    path = SOURCE / "modules" / "identity" / "paypal_login.py"
    names = imported_names(path)
    assert not {"httpx", "aiohttp", "requests", "urllib3", "socket", "ssl"} & {
        name.split(".")[0] for name in names
    }
    assert not any(name.startswith("fairpool.adapters") for name in names), names
    assert not any(name.startswith("fairpool.fakes") for name in names), names
    assert "fairpool.ports" in names and "fairpool.db.models.identity" in names

    statements = sql_literals(path)
    assert statements
    for statement in statements:
        for table in ("vault_tokens", "vault_setup_attempts", "buyer_orders", "ledger_entries"):
            assert table not in statement, f"{statement} touches {table}"

    # The provider identifier has exactly one use in the module: the HMAC call.
    source = path.read_text(encoding="utf-8")
    assert source.count("profile.account_id") == 1


def test_the_phase_three_identity_path_is_the_port_and_the_fake() -> None:
    """Nothing here claims a live provider: the real client does not exist yet."""
    fake = FakePayPalIdentity()
    assert isinstance(fake, PayPalIdentity)
    assert set(vars(fake)) <= {"accounts", "failure", "calls", "_tokens"}

    wiring = (SOURCE / "wiring.py").read_text(encoding="utf-8")
    assert "PayPalIdentity" not in wiring, "Phase 4 wires the adapter in wiring.py"
    adapter_files = {path.name for path in (SOURCE / "adapters" / "paypal").iterdir()}
    assert not [name for name in adapter_files if "identity" in name], (
        "no real login client exists yet: Phase 3 CI proves the fake"
    )


# --------------------------------------------------------------------- pool setup

POOL_TEMPLATE: dict[str, Any] = {
    "product_key": "monitor-27-4k",
    "variant": "black",
    "title": "27-inch 4K monitor",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "delivery_sla_days": 7,
    "fund_by": "2026-11-10",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
}
POOL_TIMELINE: dict[str, Any] = {
    "open_at": iso_in(-60),
    "close_at": iso_in(3600),
    "beacon_delay_s": 10,
    "bid_window_s": 120,
    "offer_window_s": 180,
    "fund_deadline_s": 600,
    "capture_grace_s": 120,
    "pending_wait_s": 120,
    "max_refill_waves": 1,
    "authorization_age_guard_s": 216000,
}


async def insert_pool(db: AsyncSession, *, require_link: bool = False) -> uuid.UUID:
    """A published OPEN pool with frozen rules, written here so no other lane is needed."""
    pool_id = uuid.uuid4()
    admin = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Admin', 'admin')"
        ),
        {"id": admin, "email": f"admin-{pool_id}@example.test"},
    )
    await db.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', 'OPEN', 'Monitor pool', CAST(:template AS jsonb), "
            "'[]'::jsonb, CAST(:timeline AS jsonb), :require_link, 'allocation_v1', "
            ":rules_hash, :created_by)"
        ),
        {
            "id": pool_id,
            "template": json.dumps(POOL_TEMPLATE),
            "timeline": json.dumps(POOL_TIMELINE),
            "require_link": require_link,
            "rules_hash": "a" * 64,
            "created_by": admin,
        },
    )
    return pool_id


def join_service(dedupe_mode: str = "two_keys") -> JoinService:
    return JoinService(
        DbClock(),
        PostgresAuditLog(),
        PostgresIdempotencyStore(),
        signing_seed=signing_seed(SEED),
        dedupe_mode=dedupe_mode,
    )


async def join_pool(
    db: AsyncSession, user_id: uuid.UUID, pool_id: uuid.UUID, *, dedupe_mode: str = "two_keys"
) -> uuid.UUID:
    """A real SUBMITTED entry through the join lane, keyed from the user's link."""
    record = await ManualIntakeService(PostgresAuditLog()).confirm(
        db,
        user_id=user_id,
        pool_id=pool_id,
        payload={
            "delivery": {"region": "NY"},
            "required_by": "2026-11-30",
            "max_total_cents": 60000,
            "firm": [],
            "preferences": [],
        },
    )
    outcome = await join_service(dedupe_mode).join(
        db,
        pool_id=pool_id,
        user_id=user_id,
        confirmed_request_id=record.id,
        idempotency_key=f"login-{user_id}-{pool_id}",
    )
    return uuid.UUID(str(outcome.body["entry_id"]))


async def ensure_active_link(
    db: AsyncSession, user_id: uuid.UUID, settings: Settings, identifier: str
) -> None:
    """Make sure the user holds one active link, without re-running the callback."""
    existing = await db.scalar(
        select(PayPalLink.id).where(PayPalLink.user_id == user_id, PayPalLink.revoked_at.is_(None))
    )
    if existing is None:
        await db.execute(
            text("INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:i, :u, :k)"),
            {"i": uuid.uuid4(), "u": user_id, "k": expected_key(settings, identifier)},
        )
