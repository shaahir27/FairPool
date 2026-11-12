import httpx

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from tests.unit.test_settings import make_settings


async def test_auth_http_cookie_csrf_roles_logout_and_public_buyer_only(db_session):
    app = create_app(make_settings())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as client:
        data = {
            "email": "buyer@example.test",
            "password": "a secure password",
            "display_name": "Buyer",
        }
        assert (
            await client.post("/api/v1/auth/register", json={**data, "role": "admin"})
        ).status_code == 422
        # Existing/operator-provisioned accounts retain their ordinary sign-in.
        await IdentityService("test-signing-key", DbClock()).register(db_session, **data)
        response = await client.post(
            "/api/v1/auth/login", json={"email": data["email"], "password": data["password"]}
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert (
            "HttpOnly" in cookie
            and "Secure" in cookie
            and "SameSite=lax" in cookie
            and "Max-Age=86400" in cookie
        )
        csrf = response.json()["csrf_token"]
        me = await client.get("/api/v1/me", headers={"Origin": "http://localhost:5173"})
        assert me.json()["role"] == "buyer"
        assert me.headers.get("X-CSRF-Token") == csrf
        assert me.headers.get("Cache-Control") == "no-store"
        assert "x-csrf-token" in me.headers.get("Access-Control-Expose-Headers", "").lower()
        assert (
            await client.post("/api/v1/admin/pools", json={}, headers={"X-CSRF-Token": csrf})
        ).status_code == 403
        assert (await client.post("/api/v1/auth/logout")).status_code == 403
        assert (
            await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})
        ).status_code == 403
        assert (
            await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        ).status_code == 200
        signed_out = await client.get("/api/v1/me")
        assert signed_out.status_code == 401
        assert "X-CSRF-Token" not in signed_out.headers


async def test_auth_rate_limit_applies_to_invalid_requests(db_session):
    app = create_app(make_settings())

    async def db():
        yield db_session

    app.dependency_overrides[database_session] = db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as client:
        for _ in range(10):
            assert (await client.post("/api/v1/auth/login", json={})).status_code == 422
        result = await client.post("/api/v1/auth/register", json={})
        assert result.status_code == 429 and result.headers["Retry-After"]
        assert result.json()["error"]["code"] == "RATE_LIMITED"
