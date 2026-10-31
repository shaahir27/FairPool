import httpx

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
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
        assert (await client.post("/api/v1/auth/register", json=data)).status_code == 200
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
        assert (await client.get("/api/v1/me")).json()["role"] == "buyer"
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
        assert (await client.get("/api/v1/me")).status_code == 401


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
