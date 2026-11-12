"""CR-17 / FR-AI-06: the model proposes a mandate, the buyer ratifies it.

Contract: ``ai-schemas.md`` section 9, ``api.md`` section 4.4. The proposal is a
proposal: the server stamps the reserved acts, refuses a cap above the one the buyer
stated, refuses scope outside the candidates it supplied, and answers with the manual
form when the model is unavailable. Nothing here mints a token.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from tests.integration.test_join_receipts import login, open_pool, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for()


class ScriptedMandateAI:
    """Answers ``parse_mandate`` with one scripted output and records the request."""

    def __init__(self, output: dict[str, Any] | None = None, *, raises: bool = False) -> None:
        self.output = output
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def parse_mandate(
        self,
        session: AsyncSession,
        *,
        message: str,
        proposal: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        self.calls.append({"message": message, "proposal": proposal, "candidates": candidates})
        if self.raises:
            raise RuntimeError("provider down")
        assert self.output is not None
        return self.output


def mandate_output(
    pool_id: UUID, *, amount: str = "600.00", scope: list[str] | None = None
) -> dict[str, Any]:
    return {
        "pool_scope": {
            "pool_ids": [str(pool_id)] if scope is None else scope,
            "category": "monitor-27-4k",
        },
        "max_total": {"amount": amount, "currency": "USD"},
        "expires": "2099-01-01",
        "conditions": [
            {"predicate": "PRICE_ABOVE", "params": {"amount": "520.00"}, "action": "REASK"}
        ],
        "ambiguities": [],
        "clarifying_question": None,
    }


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


def propose(client: httpx.AsyncClient, csrf: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "message": "My cap is $600 for these monitor pools. Ask me again above $520.",
        "pool_ids": [],
        "max_cap_cents": 60000,
    }
    body.update(overrides)
    return client.post("/api/v1/me/mandate-proposal", headers={"X-CSRF-Token": csrf}, json=body)


async def test_a_valid_proposal_becomes_the_card_with_reserved_acts_stamped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-ok@example.test")
    pool_id = await open_pool(db_session)
    await db_session.flush()
    ai = ScriptedMandateAI(mandate_output(pool_id))
    client._transport.app.state.intake_ai = ai  # type: ignore[attr-defined]

    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "ai"
    assert body["pool_ids"] == [str(pool_id)]
    assert body["category"] is None
    assert body["max_cap_cents"] == 60000
    assert body["reserved"] == ["payment_approval"]
    assert body["conditions"] == [
        {"predicate": "PRICE_ABOVE", "params": {"amount": "520.00"}, "action": "REASK"}
    ]
    assert body["expires_at"].startswith("2099-01-01T23:59:59")
    assert "token" not in body

    assert ai.calls[0]["proposal"] == {"max_total_cents": 60000}
    assert ai.calls[0]["candidates"] == [
        {"pool_id": str(pool_id), "category": "monitor-27-4k", "condition": "NEW"}
    ]


async def test_a_cap_above_the_stated_one_never_reaches_the_buyer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-raised@example.test")
    pool_id = await open_pool(db_session)
    await db_session.flush()
    client._transport.app.state.intake_ai = ScriptedMandateAI(  # type: ignore[attr-defined]
        mandate_output(pool_id, amount="5000.00")
    )

    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "manual"
    assert body["max_cap_cents"] == 60000
    assert body["conditions"] == []


async def test_scope_outside_the_candidates_is_refused(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-scope@example.test")
    pool_id = await open_pool(db_session)
    await db_session.flush()
    client._transport.app.state.intake_ai = ScriptedMandateAI(  # type: ignore[attr-defined]
        mandate_output(pool_id, scope=[str(uuid4())])
    )

    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "manual"


async def test_a_provider_failure_falls_back_to_the_manual_form(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-outage@example.test")
    pool_id = await open_pool(db_session)
    await db_session.flush()
    client._transport.app.state.intake_ai = ScriptedMandateAI(raises=True)  # type: ignore[attr-defined]

    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "manual"
    assert body["pool_ids"] == [str(pool_id)]
    assert body["reserved"] == ["payment_approval"]


async def test_ai_disabled_still_answers_with_the_manual_form(
    client: httpx.AsyncClient,
) -> None:
    csrf = await login(client, "mandate-disabled@example.test")
    client._transport.app.state.intake_ai = None  # type: ignore[attr-defined]

    response = await propose(client, csrf)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "manual"


async def test_the_route_requires_a_session(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/me/mandate-proposal", json={"message": "cap $600", "pool_ids": []}
    )
    assert response.status_code == 401


async def test_an_overlong_message_is_refused(client: httpx.AsyncClient) -> None:
    csrf = await login(client, "mandate-long@example.test")
    response = await propose(client, csrf, message="x" * 2001)
    assert response.status_code == 422


async def test_a_category_proposal_is_resolved_to_explicit_candidate_pools(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-category@example.test")
    pool_id = await open_pool(db_session)
    output = mandate_output(pool_id, scope=[])
    output["pool_scope"]["category"] = "monitor-27-4k"
    client._transport.app.state.intake_ai = ScriptedMandateAI(output)  # type: ignore[attr-defined]
    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.json()["source"] == "ai"
    assert response.json()["pool_ids"] == [str(pool_id)]
    assert response.json()["category"] is None


async def test_a_category_outside_the_candidates_falls_back_to_manual(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-category-refused@example.test")
    pool_id = await open_pool(db_session)
    output = mandate_output(pool_id)
    output["pool_scope"]["category"] = "unrelated-product"
    client._transport.app.state.intake_ai = ScriptedMandateAI(output)  # type: ignore[attr-defined]
    response = await propose(client, csrf, pool_ids=[str(pool_id)])
    assert response.json()["source"] == "manual"


async def test_proposal_finds_public_open_candidates_without_manual_selection(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "mandate-auto@example.test")
    pool_id = await open_pool(db_session)
    await db_session.execute(
        text("UPDATE pools SET search_text = 'monitor 27 inch 4k' WHERE id = :id"),
        {"id": pool_id},
    )
    await open_pool(db_session, status="DRAFT")
    await open_pool(db_session, mode="SIMULATION")
    ai = ScriptedMandateAI(mandate_output(pool_id))
    client._transport.app.state.intake_ai = ai  # type: ignore[attr-defined]
    response = await propose(client, csrf, message="monitor", pool_ids=[])
    assert response.status_code == 200
    assert response.json()["source"] == "ai"
    assert response.json()["pool_ids"] == [str(pool_id)]
    assert [row["pool_id"] for row in ai.calls[0]["candidates"]] == [str(pool_id)]
