"""T03B03: the ``DEDUPE_MODE`` behaviour and the disclosure copy (api.md, S1, OD-P3-4).

Same honest scope as ``test_login_linking``: the provider is
``FakePayPalIdentity`` behind the ``PayPalIdentity`` port, so this file proves the
three modes' storage rules and their wording, and proves nothing about a live
PayPal login round trip.

``two_keys`` is the recorded S1 outcome: the login identifier and the checkout
``payer_id`` are two identifiers, each deduplicated on its own, with no equality
requirement and no prefix stripping. ``full`` would add that equality requirement
and is refused here because equivalence was never proved. ``checkout_only`` stores
no login key at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.config import Settings
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.paypal_identity import FAKE_ALICE, FakePayPalIdentity
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.paypal_login import PayPalLoginService, disclosure
from fairpool.modules.identity.service import IdentityService, Principal
from tests.integration.test_login_linking import (
    CODE,
    callback,
    ensure_active_link,
    expected_key,
    insert_pool,
    join_pool,
    link_rows,
    login_settings,
    new_buyer,
    start,
    state_count,
    state_row,
)
from tests.unit.test_settings import make_settings

MODES = ("full", "two_keys", "checkout_only")


@pytest.fixture
async def mode_client(db_session: AsyncSession) -> Any:
    """A login app for one mode, with its own fake identity and cookie jar."""

    async def build(**overrides: Any) -> tuple[httpx.AsyncClient, FakePayPalIdentity, Settings]:
        settings = login_settings(**overrides)
        identity = FakePayPalIdentity()
        app = create_app(settings)
        app.state.paypal_identity = identity

        async def session() -> AsyncIterator[AsyncSession]:
            yield db_session

        app.dependency_overrides[database_session] = session
        return (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test"),
            identity,
            settings,
        )

    return build


# ------------------------------------------------------------------- two_keys


async def test_two_keys_links_the_login_account_and_the_entry_copies_that_key(
    db_session: AsyncSession, mode_client: Any
) -> None:
    """The login key is its own identifier, deduplicated on its own (S1, FR-ID-03)."""
    client, identity, settings = await mode_client()
    async with client:
        _, user_id = await new_buyer(client, "two-keys@example.test")
        pool_id = await insert_pool(db_session, require_link=True)
        assert await state_count(db_session, user_id) == 0
        await ensure_active_link(db_session, user_id, settings, FAKE_ALICE)
        entry_id = await join_pool(db_session, user_id, pool_id)

        stored = (
            await db_session.execute(
                text("SELECT paypal_account_key FROM pool_entries WHERE id = :e"), {"e": entry_id}
            )
        ).scalar_one()

        link = (await link_rows(db_session, user_id))[0]
        assert stored == expected_key(settings, FAKE_ALICE) == link.paypal_account_key
        assert identity.calls == []

        # A checkout payer identifier is a different identifier and keys differently:
        # two_keys deduplicates the two separately and strips no prefix to force a
        # match, so neither side can silently satisfy the other.
        payer_key = expected_key(settings, "PAYERIDXYZ123")
        assert payer_key != stored
        assert payer_key != expected_key(settings, "PAYERID")
        assert stored != expected_key(settings, FAKE_ALICE.lower())


async def test_two_keys_never_requires_the_login_key_to_equal_a_payer_key(
    db_session: AsyncSession, mode_client: Any
) -> None:
    """The link stands on its own: nothing here reads an order, a payer or a vault."""
    client, identity, _ = await mode_client(dedupe_mode="two_keys")
    async with client:
        _, user_id = await new_buyer(client, "no-equality@example.test")
        _, state = await start(client)
        assert (await callback(client, code=CODE, state=state)).status_code == 200
        assert (await callback(client, code="fake-code-bob", state=state)).status_code == 403
        assert identity.calls == ["exchange_code", "userinfo"], "the replay never called again"

    rows = await link_rows(db_session, user_id)
    assert len(rows) == 1 and rows[0].revoked_at is None


# ---------------------------------------------------------------- checkout_only


async def test_checkout_only_completes_the_login_and_stores_no_login_key(
    db_session: AsyncSession, mode_client: Any
) -> None:
    """``checkout_only`` keeps the weaker disclosure and persists nothing (decisions 4)."""
    client, identity, _ = await mode_client(dedupe_mode="checkout_only")
    async with client:
        _, user_id = await new_buyer(client, "checkout-only@example.test")
        _, state = await start(client)

        result = await callback(client, code=CODE, state=state)

        assert result.status_code == 200, result.text
        assert result.json() == {"paypal_linked": False}
        assert identity.calls == ["exchange_code", "userinfo"]
        assert (await state_row(db_session, state)).consumed_at is not None
        assert await link_rows(db_session, user_id) == []
        assert await state_count(db_session, user_id, consumed=True) == 1

        # And an entry made in this mode carries no login key at all (db-schema.md).
        pool_id = await insert_pool(db_session)
        entry_id = await join_pool(db_session, user_id, pool_id, dedupe_mode="checkout_only")
        assert (
            await db_session.scalar(
                text("SELECT paypal_account_key FROM pool_entries WHERE id = :e"), {"e": entry_id}
            )
            is None
        )
        assert (
            await db_session.scalar(
                text("SELECT count(*) FROM pool_entries WHERE id = :e"), {"e": entry_id}
            )
            == 1
        )


async def test_checkout_only_still_refuses_a_replayed_state(
    db_session: AsyncSession, mode_client: Any
) -> None:
    client, identity, _ = await mode_client(dedupe_mode="checkout_only")
    async with client:
        await new_buyer(client, "replay-only@example.test")
        _, state = await start(client)
        assert (await callback(client, code=CODE, state=state)).status_code == 200

        replay = await callback(client, code=CODE, state=state)

        assert replay.status_code == 403
        assert identity.calls == ["exchange_code", "userinfo"]


# ------------------------------------------------------------------------- full


async def test_full_is_refused_because_equivalence_was_never_proved(
    db_session: AsyncSession, mode_client: Any
) -> None:
    """OD-P3-4: ``full`` is unreachable rather than quietly downgraded to two_keys."""
    client, identity, _ = await mode_client(dedupe_mode="full")
    async with client:
        csrf, user_id = await new_buyer(client, "full-mode@example.test")
        started = await client.get("/api/v1/paypal/login/start")
        callback_result = await callback(client, code=CODE, state="a-state-that-was-never-minted")
        revoked = await client.delete("/api/v1/paypal/link", headers={"X-CSRF-Token": csrf})

        for response in (started, callback_result, revoked):
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "FEATURE_DISABLED"

    assert identity.calls == []
    assert await state_count(db_session, user_id) == 0
    assert await link_rows(db_session, user_id) == []
    assert disclosure("full").proves.count("OD-P3-4") == 1


# ------------------------------------------------------------------ disclosures


def test_every_mode_disclosure_says_what_it_proves_and_what_it_does_not() -> None:
    """FR-ID-02, FR-ID-03 and I13: account-level control, never person-level claims."""
    claimed = ("one human per account", "one person per account", "same person")
    for mode in MODES:
        entry = disclosure(mode)
        assert entry.mode == mode
        assert entry.summary and entry.proves and entry.does_not_prove
        for phrase in claimed:
            assert phrase not in entry.proves, f"{mode} claims {phrase}"
            assert phrase not in entry.summary, f"{mode} claims {phrase}"
        assert "one human per account" in entry.does_not_prove, f"{mode} hides the limit"

    two_keys = disclosure("two_keys")
    assert "separate" in two_keys.summary
    assert "checkout" in two_keys.summary
    only = disclosure("checkout_only")
    assert "no PayPal Login account" in only.summary
    assert disclosure("full").proves.startswith("Nothing in this build")


def test_the_disclosure_is_what_the_join_screen_would_render() -> None:
    """The text is the product's, not an implementation note: no brand, no over-claim."""
    for mode in MODES:
        entry = disclosure(mode)
        text_blob = " ".join((entry.summary, entry.proves, entry.does_not_prove))
        assert "PayPal" in text_blob
        for brand in ("Amazon", "Best Buy", "Micro Center", "Newegg"):
            assert brand not in text_blob  # FR-HK-06: no brand names in product copy
        assert len(entry.does_not_prove) > 40, f"{mode} disclosure is too thin to be honest"


# ------------------------------------------------------------------- mode gate


async def test_the_login_routes_share_the_contracted_per_ip_rate_limit(
    db_session: AsyncSession,
) -> None:
    """config-and-errors.md section 3: these routes are "everything else", 120/min/IP."""
    app = create_app(make_settings(paypal_login_enabled=True))

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await new_buyer(client, "login-rate@example.test")
        for index in range(120):
            # A refused callback still counts: the limiter guards the route, not
            # the success path, and it writes nothing along the way.
            refused = await callback(client, code=CODE, state=f"never-minted-{index}")
            assert refused.status_code == 403, (index, refused.text)

        limited = await client.get("/api/v1/paypal/login/start")
        assert limited.status_code == 429, limited.text
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert int(limited.headers["Retry-After"]) >= 1
        # Only these three routes carry this bucket; the rest of the API is untouched.
        assert (await client.get("/api/v1/me")).status_code == 200


async def test_the_service_refuses_full_before_touching_the_database(
    db_session: AsyncSession,
) -> None:
    """The gate is the service's, so no caller has to remember it."""
    settings: Settings = login_settings(dedupe_mode="full")
    service = PayPalLoginService(
        FakePayPalIdentity(),
        DbClock(),
        PostgresAuditLog(),
        hmac_key=settings.hmac_key.get_secret_value(),
        dedupe_mode=settings.dedupe_mode,
        enabled=settings.paypal_login_enabled,
        client_id=settings.paypal_client_id,
        redirect_uri=settings.paypal_login_redirect_uri,
        checkout_base=settings.paypal_checkout_base,
        state_ttl_s=settings.oauth_state_ttl_s,
    )
    principal = await _principal(db_session, "gate@example.test")

    with pytest.raises(ApplicationError) as raised:
        await service.start(db_session, principal)
    assert raised.value.code == "FEATURE_DISABLED"
    with pytest.raises(ApplicationError) as again:
        await service.unlink(db_session, principal)
    assert again.value.code == "FEATURE_DISABLED"
    assert await state_count(db_session, principal.user_id) == 0


async def _principal(db: AsyncSession, email: str) -> Principal:
    settings = login_settings()
    service = IdentityService(settings.secret_key.get_secret_value(), DbClock())
    await service.register(db, email=email, password="a-secure-password", display_name="Buyer")
    login = await service.login(db, email=email, password="a-secure-password")
    return await service.authenticate(db, login.cookie)
