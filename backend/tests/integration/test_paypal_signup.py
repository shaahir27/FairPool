"""Owner-requested PayPal-first registration: browser-bound, single-use and atomic."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import text

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.fakes.paypal_identity import FakePayPalIdentity
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.integration
ORIGIN = "http://localhost:5173"
DETAILS = {
    "email": "new-buyer@example.test",
    "display_name": "Pool Buyer",
    "password": "a long test passphrase",
    "password_confirm": "a long test passphrase",
}


def signup_app(db_session):
    app = create_app(make_settings(paypal_login_enabled=True))
    app.state.paypal_signup_identity = FakePayPalIdentity()

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    return app


async def connect(client):
    started = await client.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
    assert started.status_code == 200
    target = urlsplit(started.json()["authorize_url"])
    assert target.path == "/connect"
    assert parse_qs(target.query)["flowEntry"] == ["static"]
    state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
    return await client.get(
        "/api/v1/auth/paypal/callback", params={"state": state, "code": "fake-code-alice"}
    )


async def test_registration_cannot_skip_paypal(db_session):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        result = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert result.status_code == 403
        assert (
            await db_session.scalar(
                text("SELECT count(*) FROM users WHERE email = 'new-buyer@example.test'")
            )
            == 0
        )


async def test_paypal_signup_creates_one_linked_buyer_and_signs_them_in(db_session):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        result = await connect(client)
        assert result.status_code == 303
        assert result.headers["location"] == ORIGIN + "/register/connected"
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "ready"
        result = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert result.status_code == 200
        assert result.json()["csrf_token"]
        assert "HttpOnly" in result.headers["set-cookie"]
        me = (await client.get("/api/v1/me")).json()
        assert me["paypal_linked"] is True and me["display_name"] == "Pool Buyer"
        assert me["role"] == "buyer"
        replay = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert replay.status_code == 403
        assert (
            await db_session.scalar(
                text("SELECT count(*) FROM users WHERE email = 'new-buyer@example.test'")
            )
            == 1
        )


async def test_signup_callback_is_bound_to_its_browser(db_session):
    app = signup_app(db_session)
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as first,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as other,
    ):
        started = await first.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
        state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
        callback = await other.get(
            "/api/v1/auth/paypal/callback", params={"state": state, "code": "fake-code-alice"}
        )
        assert callback.headers["location"].endswith("reason=expired")
        assert not app.state.paypal_signup_identity.calls


async def test_password_mismatch_does_not_consume_signup(db_session):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        await connect(client)
        result = await client.post(
            "/api/v1/auth/register",
            json={**DETAILS, "password_confirm": "different"},
            headers={"Origin": ORIGIN},
        )
        assert result.status_code == 422
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "ready"
        assert (
            await db_session.scalar(
                text("SELECT count(*) FROM users WHERE email = 'new-buyer@example.test'")
            )
            == 0
        )


async def test_same_paypal_account_cannot_register_twice(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        assert (
            await client.post("/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN})
        ).status_code == 200
        client.cookies.clear()
        callback = await connect(client)
        assert callback.headers["location"].endswith("reason=account_exists")
        assert (
            await client.post(
                "/api/v1/auth/register",
                json={**DETAILS, "email": "another@example.test"},
                headers={"Origin": ORIGIN},
            )
        ).status_code == 403
        assert (
            await db_session.scalar(
                text(
                    "SELECT count(*) FROM users WHERE email IN "
                    "('new-buyer@example.test', 'another@example.test')"
                )
            )
            == 1
        )


async def test_signup_refuses_a_cross_site_start(db_session):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        result = await client.post(
            "/api/v1/auth/paypal/start", headers={"Origin": "https://attacker.test"}
        )
        assert result.status_code == 403


async def test_expired_signup_cannot_create_an_account(db_session):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        await connect(client)
        await db_session.execute(
            text(
                "UPDATE paypal_signups SET expires_at = clock_timestamp() - interval '1 second' "
                "WHERE completed_at IS NULL"
            )
        )
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "expired"
        result = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert result.status_code == 403


async def test_provider_failure_never_unlocks_account_setup(db_session):
    app = signup_app(db_session)
    app.state.paypal_signup_identity.failure = "unavailable"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        callback = await connect(client)
        assert callback.headers["location"].endswith("reason=unavailable")
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] != "ready"


async def test_two_ready_browsers_cannot_create_two_accounts_for_one_paypal(db_session):
    app = signup_app(db_session)
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as first,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as other,
    ):
        assert (await connect(first)).headers["location"].endswith("/register/connected")
        assert (await connect(other)).headers["location"].endswith("/register/connected")
        assert (
            await first.post("/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN})
        ).status_code == 200
        result = await other.post(
            "/api/v1/auth/register",
            json={**DETAILS, "email": "another@example.test"},
            headers={"Origin": ORIGIN},
        )
        assert result.status_code == 409
        assert result.json()["error"]["code"] == "PAYPAL_LINK_CONFLICT"


async def test_signup_callback_cannot_exchange_the_same_grant_twice(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        started = await client.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
        state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
        params = {"state": state, "code": "fake-code-alice"}
        await client.get("/api/v1/auth/paypal/callback", params=params)
        await client.get("/api/v1/auth/paypal/callback", params=params)
        assert app.state.paypal_signup_identity.calls == ["exchange_code", "userinfo"]


async def test_paypal_prefill_is_encrypted_browser_bound_and_cleared_on_registration(db_session):
    from fairpool.ports import ProviderProfile

    class WithDetails(FakePayPalIdentity):
        async def userinfo(self, access_token, id_token=None):
            profile = await super().userinfo(access_token, id_token)
            return ProviderProfile(
                account_id=profile.account_id,
                details={
                    "email": "prefill@example.test",
                    "display_name": "Pool Buyer",
                    "address": {"line1": "12 Test Lane"},
                },
            )

    app = signup_app(db_session)
    app.state.paypal_signup_identity = WithDetails()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        response = await client.get("/api/v1/auth/paypal/status")
        assert response.json()["prefill"]["email"] == "prefill@example.test"
        blob = await db_session.scalar(
            text("SELECT profile_enc FROM paypal_signups WHERE profile_enc IS NOT NULL")
        )
        assert b"prefill@example.test" not in bytes(blob) and b"12 Test Lane" not in bytes(blob)
        assert response.headers["cache-control"] == "no-store"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as other:
            assert (await other.get("/api/v1/auth/paypal/status")).json()["prefill"] is None
        assert (
            await client.post("/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN})
        ).status_code == 200
        assert (
            await db_session.scalar(
                text("SELECT count(*) FROM paypal_signups WHERE profile_enc IS NOT NULL")
            )
            == 0
        )


async def test_returning_signed_in_user_cannot_start_signup_again(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        registered = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert registered.status_code == 200
        assert "session" in client.cookies

        # An active signed-in user must not be sent through registration again
        second_start = await client.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
        assert second_start.status_code == 403


async def test_setup_window_expires_after_bounded_ttl(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        # Verify status is ready before expiry
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "ready"

        # Fast-forward expires_at to simulate expiry of the bounded setup window
        await db_session.execute(
            text("UPDATE paypal_signups SET expires_at = now() - interval '1 second'")
        )
        await db_session.commit()

        # Status becomes expired and registration is forbidden
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "expired"
        assert (
            await client.post("/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN})
        ).status_code == 403


async def test_expired_session_allows_ordinary_login(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        reg = await client.post("/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN})
        assert reg.status_code == 200

        # Expire session in the database
        await db_session.execute(text("UPDATE sessions SET expires_at = now() - interval '1 hour'"))
        await db_session.commit()

        # Normal login works with ordinary email and password
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": DETAILS["email"], "password": DETAILS["password"]},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        assert "session" in client.cookies


async def test_repeated_starts_keep_one_pending_attempt_per_browser(db_session):
    """Reloading the page must not pile abandoned attempts into the shared database."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        state = ""
        for _ in range(3):
            started = await client.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
            assert started.status_code == 200
            state = parse_qs(urlsplit(started.json()["authorize_url"]).query)["state"][0]
        assert await db_session.scalar(text("SELECT count(*) FROM paypal_signups")) == 1, (
            "three starts, one row"
        )
        # The reused row still carries a live state, so the one callback works.
        callback = await client.get(
            "/api/v1/auth/paypal/callback", params={"state": state, "code": "fake-code-alice"}
        )
        assert callback.status_code == 303
        assert callback.headers["location"].endswith("/register/connected")
        assert (await client.get("/api/v1/auth/paypal/status")).json()["status"] == "ready"
        assert await db_session.scalar(text("SELECT count(*) FROM paypal_signups")) == 1, (
            "the attempt was filled in, not duplicated"
        )


async def test_a_finished_signup_reports_registered_not_a_form_to_refill(db_session):
    """A second tab holding the old cookie must not be walked through signup again."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        await connect(client)
        cookie = client.cookies.get("fairpool_signup")
        assert cookie
        result = await client.post(
            "/api/v1/auth/register", json=DETAILS, headers={"Origin": ORIGIN}
        )
        assert result.status_code == 200
        stale = await client.get(
            "/api/v1/auth/paypal/status", headers={"Cookie": f"fairpool_signup={cookie}"}
        )
        assert stale.json()["status"] == "registered"
        # The cleared prefill means a stale tab can no longer read anyone's details.
        assert stale.json()["prefill"] is None
        # And the same browser can never create a second account from that row.
        again = await client.post(
            "/api/v1/auth/register",
            json={**DETAILS, "email": "second-buyer@example.test"},
            headers={"Origin": ORIGIN, "Cookie": f"fairpool_signup={cookie}"},
        )
        assert again.status_code == 403


async def test_the_authorize_request_asks_for_the_documented_attribute_scopes(db_session):
    """Without the URI-form account scope PayPal grants no attributes at all (CR-6)."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=signup_app(db_session)), base_url="https://api.test"
    ) as client:
        started = await client.post("/api/v1/auth/paypal/start", headers={"Origin": ORIGIN})
        assert started.status_code == 200
    scope = parse_qs(urlsplit(started.json()["authorize_url"]).query)["scope"][0]
    assert scope.split() == [
        "openid",
        "profile",
        "email",
        "address",
        "https://uri.paypal.com/services/paypalattributes",
    ]
