"""T03B01 / CR-3: ``POST /api/v1/intake/manual`` over HTTP (the B1 regression).

The route builds its own ``JSONResponse``, so FastAPI never runs
``jsonable_encoder`` over it: every value must already be JSON-native or
Starlette's ``json.dumps`` raises ``TypeError`` and the buyer gets a 500 on a
request the deterministic validator accepted (api.md "Intake"). This is the route-level
proof the service-level tests could not give: a UUID-shaped **string**
``confirmed_request_id`` and the canonical request body, at 201.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.integration.test_join_receipts import login, open_pool, settings_for

pytestmark = pytest.mark.integration

#: A raw UUID text, as api.md §"Intake" specifies (a string, not an object).
UUID_TEXT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
MANUAL_FORM: dict[str, Any] = {
    "delivery": {"region": "NY"},
    "required_by": "2026-11-30",
    "max_total_cents": 60000,
    "firm": [],
    "preferences": [],
}


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for())

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def test_manual_intake_answers_201_with_a_uuid_string_and_the_canonical_request(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "manual-route@example.test")
    pool_id = await open_pool(db_session)

    response = await client.post(
        "/api/v1/intake/manual",
        json={"pool_id": str(pool_id), **MANUAL_FORM},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert sorted(body) == ["canonical_request", "confirmed_request_id"]
    # A string that parses as a UUID: never a JSON object and never a raw repr.
    assert isinstance(body["confirmed_request_id"], str)
    assert UUID_TEXT.match(body["confirmed_request_id"])
    record_id = uuid.UUID(body["confirmed_request_id"])

    canonical = body["canonical_request"]
    assert sorted(canonical) == [
        "condition",
        "currency",
        "delivery",
        "firm",
        "max_total_cents",
        "pool_id",
        "preferences",
        "product_key",
        "quantity",
        "required_by",
        "v",
        "variant",
    ]
    assert canonical["pool_id"] == str(pool_id)
    assert canonical["product_key"] == "monitor-27-4k"
    assert canonical["delivery"] == {"zone_id": "US-EAST", "region": "NY", "country": "US"}
    assert canonical["required_by"] == "2026-11-30"
    assert canonical["max_total_cents"] == 60000
    assert canonical["firm"] == [] and canonical["preferences"] == []

    # The record is the one the join lane consumes: stored, owned and frozen.
    stored = (
        await db_session.execute(
            text(
                "SELECT user_id, pool_id, rules_hash, cap_cents, zone_id "
                "FROM confirmed_requests WHERE id = :id"
            ),
            {"id": record_id},
        )
    ).first()
    assert stored is not None
    assert str(stored[1]) == str(pool_id)
    assert stored[2] == "a" * 64 and stored[3] == 60000 and stored[4] == "US-EAST"


async def test_manual_intake_needs_a_session_and_a_known_pool(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "manual-route-guard@example.test")
    pool_id = await open_pool(db_session)

    async with httpx.AsyncClient(
        transport=client._transport, base_url="https://api.test"
    ) as anonymous_client:
        anonymous = await anonymous_client.post(
            "/api/v1/intake/manual", json={"pool_id": str(pool_id), **MANUAL_FORM}
        )
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "UNAUTHENTICATED"

    unknown = await client.post(
        "/api/v1/intake/manual",
        json={"pool_id": str(uuid.uuid4()), **MANUAL_FORM},
        headers={"X-CSRF-Token": csrf},
    )
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"

    # A payload field the frozen template cannot accept is a rejection, not a 500.
    invalid = await client.post(
        "/api/v1/intake/manual",
        json={"pool_id": str(pool_id), **{**MANUAL_FORM, "max_total_cents": -1}},
        headers={"X-CSRF-Token": csrf},
    )
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "VALIDATION_ERROR"
