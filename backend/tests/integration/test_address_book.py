"""Saved delivery addresses are private, encrypted, reusable and owner-editable."""

import httpx
from sqlalchemy import text

from tests.integration.test_paypal_signup import DETAILS, ORIGIN, connect, signup_app

ADDRESS = {
    "name": "Pool Buyer",
    "line1": "12 Test Lane",
    "line2": "",
    "city": "Test City",
    "region": "CA",
    "postal_code": "90210",
    "country_code": "US",
}


async def test_signup_saves_encrypted_address_and_owner_can_manage_multiple(db_session):
    app = signup_app(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as client:
        await connect(client)
        response = await client.post(
            "/api/v1/auth/register",
            json={**DETAILS, "delivery_address": ADDRESS},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 200
        csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
        saved = (await client.get("/api/v1/me/addresses")).json()["addresses"]
        assert len(saved) == 1 and saved[0]["is_default"]
        assert saved[0]["address"] == ADDRESS
        blob = await db_session.scalar(
            text("SELECT address_enc FROM user_addresses WHERE id=:id"), {"id": saved[0]["id"]}
        )
        assert b"12 Test Lane" not in bytes(blob)
        added = await client.post(
            "/api/v1/me/addresses",
            json={"address": {**ADDRESS, "line1": "34 Second Lane"}, "is_default": True},
            headers=csrf,
        )
        assert added.status_code == 200
        second = added.json()["id"]
        listed = (await client.get("/api/v1/me/addresses")).json()["addresses"]
        assert len(listed) == 2 and sum(a["is_default"] for a in listed) == 1
        assert next(a for a in listed if a["id"] == second)["is_default"]
        updated = await client.put(
            f"/api/v1/me/addresses/{second}",
            json={"address": {**ADDRESS, "city": "New City"}, "is_default": True},
            headers=csrf,
        )
        assert updated.status_code == 200 and updated.json()["address"]["city"] == "New City"
        assert (
            await client.delete(f"/api/v1/me/addresses/{second}", headers=csrf)
        ).status_code == 204
        remaining = (await client.get("/api/v1/me/addresses")).json()["addresses"]
        assert len(remaining) == 1 and remaining[0]["is_default"]


async def test_address_book_rejects_another_buyer_and_requires_csrf(db_session):
    app = signup_app(db_session)
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as first,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as other,
    ):
        await connect(first)
        r = await first.post(
            "/api/v1/auth/register",
            json={**DETAILS, "delivery_address": ADDRESS},
            headers={"Origin": ORIGIN},
        )
        saved = (await first.get("/api/v1/me/addresses")).json()["addresses"][0]
        assert (
            await first.post("/api/v1/me/addresses", json={"address": ADDRESS})
        ).status_code == 403
        from tests.identity_helpers import provision_buyer

        await provision_buyer(
            other,
            email="other-address@example.test",
            password=DETAILS["password"],
            display_name="Other Buyer",
        )
        login = await other.post(
            "/api/v1/auth/login",
            json={"email": "other-address@example.test", "password": DETAILS["password"]},
        )
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        assert (await other.get("/api/v1/me/addresses")).json()["addresses"] == []
        assert (
            await other.put(
                f"/api/v1/me/addresses/{saved['id']}", json={"address": ADDRESS}, headers=headers
            )
        ).status_code == 404
        assert (
            await other.delete(f"/api/v1/me/addresses/{saved['id']}", headers=headers)
        ).status_code == 404
        assert r.status_code == 200
