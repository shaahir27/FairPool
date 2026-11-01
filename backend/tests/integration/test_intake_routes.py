"""T04B01 route level: ``POST /intake/messages`` and ``POST /intake/confirm``.

The service tests cover the deterministic checks; these prove the HTTP surface: the
contracted request and response shapes, session + CSRF enforcement, the owner-scoped
confirmation, the 20/min/user limit, and that no raw model output crosses the wire
(only a status, at most one question and the server-built card).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.fakes.ai import FakeAI
from tests.integration.test_intake_validation import MESSAGE, proposal
from tests.integration.test_join_receipts import SEED, login, open_pool, settings_for
from tests.unit.test_settings import make_settings

pytestmark = pytest.mark.integration

MESSAGE_KEYS = {"session_id", "status", "clarifying_question", "confirmation_card"}


@pytest.fixture
async def ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
async def client(db_session: AsyncSession, ai: FakeAI) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for())
    app.state.intake_ai = ai

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def script(ai: FakeAI, client: httpx.AsyncClient, csrf: str, pool_id: UUID) -> None:
    """Record the canonical input through the route, then script the answer."""
    await client.post(
        "/api/v1/intake/messages",
        json={"pool_id": str(pool_id), "message": MESSAGE},
        headers={"X-CSRF-Token": csrf},
    )
    ai.register_hash(ai.calls[-1].input_hash, proposal(pool_id))


async def test_a_turn_returns_the_card_and_its_confirmation_writes_the_request(
    client: httpx.AsyncClient, db_session: AsyncSession, ai: FakeAI
) -> None:
    csrf = await login(client, "intake-route@example.test")
    pool_id = await open_pool(db_session)
    await script(ai, client, csrf, pool_id)

    turn = await client.post(
        "/api/v1/intake/messages",
        json={"pool_id": str(pool_id), "message": MESSAGE},
        headers={"X-CSRF-Token": csrf},
    )

    assert turn.status_code == 200, turn.text
    body = turn.json()
    assert set(body) == MESSAGE_KEYS
    assert body["status"] == "READY_TO_CONFIRM"
    assert body["clarifying_question"] is None
    card = body["confirmation_card"]
    assert set(card) == {
        "proposal_id",
        "pool",
        "delivery",
        "required_by",
        "max_total_cents",
        "firm",
        "preferences",
        "notices",
    }

    confirmed = await client.post(
        "/api/v1/intake/confirm",
        json={"proposal_id": card["proposal_id"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert confirmed.status_code == 201, confirmed.text
    result = confirmed.json()
    assert sorted(result) == ["canonical_request", "confirmed_request_id"]
    assert UUID(result["confirmed_request_id"])
    assert result["canonical_request"]["pool_id"] == str(pool_id)


async def test_a_question_never_leaks_the_models_own_fields(
    client: httpx.AsyncClient, db_session: AsyncSession, ai: FakeAI
) -> None:
    csrf = await login(client, "intake-question@example.test")
    pool_id = await open_pool(db_session)
    await client.post(
        "/api/v1/intake/messages",
        json={"pool_id": str(pool_id), "message": MESSAGE},
        headers={"X-CSRF-Token": csrf},
    )
    ai.register_hash(ai.calls[-1].input_hash, proposal(pool_id, condition="OPEN_BOX"))

    turn = await client.post(
        "/api/v1/intake/messages",
        json={"pool_id": str(pool_id), "message": MESSAGE},
        headers={"X-CSRF-Token": csrf},
    )

    body = turn.json()
    assert body["status"] == "NEEDS_CLARIFICATION"
    assert body["confirmation_card"] is None
    assert "match_confidence" not in turn.text and "ambiguities" not in turn.text


async def test_the_routes_need_a_session_and_a_csrf_token(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    pool_id = await open_pool(db_session)
    async with httpx.AsyncClient(
        transport=client._transport, base_url="https://api.test"
    ) as anonymous:
        turn = await anonymous.post(
            "/api/v1/intake/messages", json={"pool_id": str(pool_id), "message": MESSAGE}
        )
    assert turn.status_code == 401
    assert turn.json()["error"]["code"] == "UNAUTHENTICATED"

    csrf = await login(client, "intake-csrf@example.test")
    missing = await client.post(
        "/api/v1/intake/messages", json={"pool_id": str(pool_id), "message": MESSAGE}
    )
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "FORBIDDEN"
    assert csrf


async def test_confirming_another_buyers_proposal_answers_not_found(
    client: httpx.AsyncClient, db_session: AsyncSession, ai: FakeAI
) -> None:
    csrf = await login(client, "intake-owner@example.test")
    pool_id = await open_pool(db_session)
    await script(ai, client, csrf, pool_id)
    turn = await client.post(
        "/api/v1/intake/messages",
        json={"pool_id": str(pool_id), "message": MESSAGE},
        headers={"X-CSRF-Token": csrf},
    )
    proposal_id = turn.json()["confirmation_card"]["proposal_id"]

    async with httpx.AsyncClient(transport=client._transport, base_url="https://api.test") as other:
        other_csrf = await login(other, "intake-other@example.test")
        refused = await other.post(
            "/api/v1/intake/confirm",
            json={"proposal_id": proposal_id},
            headers={"X-CSRF-Token": other_csrf},
        )

    assert refused.status_code == 404 and refused.json()["error"]["code"] == "NOT_FOUND"


async def test_the_message_route_is_limited_to_20_per_minute_per_user(
    db_session: AsyncSession, ai: FakeAI
) -> None:
    """config-and-errors.md section 3: 20 per minute per user, then 429."""
    app = create_app(make_settings(rate_limit_enabled=True, receipt_signing_key=SEED))
    app.state.intake_ai = ai

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    pool_id = await open_pool(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        csrf = await login(http, "intake-limit@example.test")
        answers: list[Any] = []
        for _ in range(21):
            answers.append(
                await http.post(
                    "/api/v1/intake/messages",
                    json={"pool_id": str(pool_id), "message": MESSAGE},
                    headers={"X-CSRF-Token": csrf},
                )
            )

    assert [answer.status_code for answer in answers[:20]] == [200] * 20
    assert answers[20].status_code == 429
    assert answers[20].json()["error"]["code"] == "RATE_LIMITED"
    assert answers[20].headers.get("Retry-After")
