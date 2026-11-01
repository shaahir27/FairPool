"""T04B01 / F19: a misparse is caught by the confirmation, never silently used.

F19 is the asymmetry the AI rules exist for: the model proposes, deterministic code
decides, and the buyer confirms what the server built. Every test here drives the real
``IntakeService`` over a real pool with ``FakeAI``, so the model output is scripted and
the checks under test are the server's.

The deterministic-check tests pass a ``FakeSearch`` that returns the test's own pool,
because their subject is the checks, not retrieval; ``test_candidate_retrieval_...``
runs the real ``SearchService`` against Postgres to prove the other half. The FakeAI is
keyed by the hash of the canonical input (``ai-schemas.md`` section 8), so a test calls
the service once to record that input, registers the scripted output against it and
calls again: the candidate payload stays owned by the service, not by the test.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.fakes.ai import MODE_INVALID_JSON, FakeAI, FakeAICall
from fairpool.fakes.ai_logger import FakeAiRunLogger
from fairpool.fakes.search import FakeSearch, SearchDocument
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.modules.intake.pipeline import (
    MANUAL_FORM_INSTRUCTION,
    MAX_TURNS,
    IntakeService,
)
from fairpool.modules.search.service import build_search_service
from fairpool.ports import SearchService
from tests.integration.test_join_receipts import open_pool, settings_for

pytestmark = pytest.mark.integration

#: The FakeSearch matches this whole string, so it must name the pool's own document.
MESSAGE = "27-inch 4K monitor"
#: ``open_pool``'s template: fund_by 2026-11-10 plus a 7-day SLA.
LATEST_DELIVERY = "2026-11-17"


def search_for(pool_id: UUID) -> FakeSearch:
    return FakeSearch(
        documents=[
            SearchDocument(
                doc_id=str(pool_id),
                doc_kind="pool",
                pool_id=pool_id,
                lot_id=None,
                product_key="monitor-27-4k",
                title="27-inch 4K monitor",
                content="27-inch 4K monitor black NEW NY NJ PA monitor stand power cable",
                status="OPEN",
            )
        ]
    )


def service(
    ai: FakeAI | None, *, pool_id: UUID | None = None
) -> tuple[IntakeService, FakeAiRunLogger]:
    logger = FakeAiRunLogger()
    search: SearchService = search_for(pool_id) if pool_id is not None else FakeSearch()
    built = IntakeService(
        search=search,
        ai=ai,
        audit=PostgresAuditLog(),
        clock=DbClock(),
        run_logger=logger,
        model="fake-model",
        prompt_version="test/1",
    )
    return built, logger


def proposal(pool_id: UUID, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pool_id": str(pool_id),
        "match_confidence": "high",
        "condition": "NEW",
        "quantity": 1,
        "delivery": {"region": "NY"},
        "required_by": "2026-12-15",
        "max_total": {"amount": "600.00", "currency": "USD"},
        "firm_requirements": [],
        "preferences": ["matte screen"],
        "ambiguities": [],
        "clarifying_question": None,
    }
    base.update(overrides)
    return base


class ConstantFakeAI(FakeAI):
    """``FakeAI`` that answers any input with one scripted output.

    The base fake keys its responses on the canonical input, which includes the turn
    history, so a multi-turn conversation would need one registration per turn. This
    subclass keeps the same call log and the same behaviour with a single answer.
    """

    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__()
        self.response = response

    def _prepare(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            FakeAICall(task=task, input_hash=self.input_hash(task, payload), payload=dict(payload))
        )
        return self.response


async def buyer(session: AsyncSession, tag: str) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name) "
            "VALUES (:id, :email, 'hash', :name)"
        ),
        {"id": user_id, "email": f"{tag}-{user_id}@example.test", "name": f"Buyer {tag}"},
    )
    return user_id


async def script(
    intake: IntakeService,
    session: AsyncSession,
    *,
    user_id: UUID,
    pool_id: UUID,
    overrides: dict[str, Any],
) -> None:
    """Record the canonical input once, then register the scripted output against it."""
    await intake.propose(session, user_id=user_id, message=MESSAGE)
    ai = intake.ai
    assert isinstance(ai, FakeAI)
    ai.register_hash(ai.calls[-1].input_hash, proposal(pool_id, **overrides))


async def count(session: AsyncSession, table: str, where: str = "TRUE", **params: Any) -> int:
    value = await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)
    return int(value or 0)


# ------------------------------------------------------------------------ F19


async def test_f19_ai_misparse_caught_by_confirmation(db_session: AsyncSession) -> None:
    """F19: a date the pool cannot meet becomes a question, never a stored request."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "f19")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    # The model extracted a date the pool cannot meet (latest is LATEST_DELIVERY).
    await script(
        intake,
        db_session,
        user_id=user_id,
        pool_id=pool_id,
        overrides={"required_by": "2026-11-01"},
    )

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "NEEDS_CLARIFICATION"
    assert LATEST_DELIVERY in str(answer["clarifying_question"])
    assert answer["confirmation_card"] is None
    # Nothing was persisted for the misparse: no proposal, no confirmed request.
    assert await count(db_session, "intake_proposals", "user_id = :u", u=user_id) == 0
    assert await count(db_session, "confirmed_requests", "user_id = :u", u=user_id) == 0

    # The manual form still writes exactly the buyer's own bytes.
    record = await ManualIntakeService(PostgresAuditLog()).confirm(
        db_session,
        user_id=user_id,
        pool_id=pool_id,
        payload={
            "delivery": {"region": "NY"},
            "required_by": "2026-12-15",
            "max_total_cents": 60000,
            "firm": [],
            "preferences": [],
        },
    )
    assert record.canonical_request["required_by"] == "2026-12-15"


async def test_three_questions_then_the_manual_form(db_session: AsyncSession) -> None:
    """ai-schemas.md 2.8: at most three turns, then ``NO_MATCH`` plus the manual form."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "turns")
    # The base fake keys on the input hash, which includes the history; a three-turn
    # conversation needs the same proposal on every turn, so it is scripted once.
    ai = ConstantFakeAI(proposal(pool_id, quantity=2))
    intake, _ = service(ai, pool_id=pool_id)

    first = await intake.propose(db_session, user_id=user_id, message=MESSAGE)
    session_id = UUID(str(first["session_id"]))
    assert first["status"] == "NEEDS_CLARIFICATION"

    answer = first
    for _turn in range(MAX_TURNS - 1):
        answer = await intake.propose(
            db_session, user_id=user_id, message=MESSAGE, session_id=session_id
        )
    assert answer["status"] == "NO_MATCH"
    assert answer["clarifying_question"] == MANUAL_FORM_INSTRUCTION
    assert await count(db_session, "intake_proposals", "user_id = :u", u=user_id) == 0


# ------------------------------------------------------- deterministic checks


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"condition": "REFURBISHED"}, "NEW"),
        ({"delivery": {"region": "ZZ"}}, "pool covers"),
        ({"max_total": {"amount": "600.00", "currency": "EUR"}}, "USD"),
        ({"max_total": {"amount": None, "currency": None}}, "most you will pay"),
        ({"firm_requirements": ["matte screen"]}, "does not offer"),
        ({"required_by": None}, "which date"),
    ],
)
async def test_each_deviation_becomes_one_question(
    db_session: AsyncSession, overrides: dict[str, Any], fragment: str
) -> None:
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "check")
    intake, logger = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=pool_id, overrides=overrides)

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "NEEDS_CLARIFICATION"
    assert fragment in str(answer["clarifying_question"])
    assert logger.calls[-1].ok is True


async def test_a_pool_outside_the_candidates_is_no_match(db_session: AsyncSession) -> None:
    """ai-schemas.md 2.1: a pool id nobody supplied is not a match."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "unknown-pool")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=uuid4(), overrides={})

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "NO_MATCH"
    assert answer["clarifying_question"] == MANUAL_FORM_INSTRUCTION
    assert await count(db_session, "intake_proposals", "user_id = :u", u=user_id) == 0


async def test_a_pool_id_override_must_be_open(db_session: AsyncSession) -> None:
    """The request's optional ``pool_id`` narrows the candidates to that open pool."""
    pool_id = await open_pool(db_session, status="DRAFT")
    user_id = await buyer(db_session, "draft")
    intake, _ = service(FakeAI(), pool_id=pool_id)

    answer = await intake.propose(
        db_session, user_id=user_id, message=MESSAGE, pool_id_override=pool_id
    )

    assert answer["status"] == "NO_MATCH"


async def test_a_model_failure_falls_back_and_is_logged(db_session: AsyncSession) -> None:
    """FR-IN-08: an unusable model answer is logged and answered with the manual form."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "broken")
    intake, logger = service(FakeAI(mode=MODE_INVALID_JSON), pool_id=pool_id)

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "NO_MATCH"
    assert answer["clarifying_question"] == MANUAL_FORM_INSTRUCTION
    run = logger.calls[-1]
    assert run.ok is False and run.error == "FakeAIInvalidJSON"
    assert run.task == "INTAKE" and run.model == "fake-model" and run.prompt_version == "test/1"


async def test_no_model_configured_still_answers_with_the_manual_form(
    db_session: AsyncSession,
) -> None:
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "no-ai")
    intake, logger = service(None, pool_id=pool_id)

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "NO_MATCH"
    assert logger.calls[-1].ok is False and logger.calls[-1].error == "AIUnavailable"


# ------------------------------------------------------------------ retrieval


async def test_candidate_retrieval_feeds_the_model(db_session: AsyncSession) -> None:
    """T04B01 acceptance: the OPEN candidate list comes from the real search service."""
    admin = await buyer(db_session, "admin")
    pool_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, rules_hash, search_text, created_by) "
            "VALUES (:id, 'LIVE_SANDBOX', 'OPEN', 'Carbon fiber telescope tripod', "
            "CAST(:template AS jsonb), '[]'::jsonb, CAST(:timeline AS jsonb), false, "
            "'allocation_v1', :rules_hash, :search_text, :admin)"
        ),
        {
            "id": pool_id,
            # What publish derives from title, variant, condition, bundle and regions.
            "search_text": "Carbon fiber telescope tripod carbon NEW tripod carry bag NY",
            "template": json.dumps(
                {
                    "product_key": "telescope-tripod",
                    "variant": "carbon",
                    "title": "Carbon fiber telescope tripod",
                    "condition": "NEW",
                    "quantity": 1,
                    "currency": "USD",
                    "bundle_contents": ["tripod", "carry bag"],
                    "delivery_sla_days": 7,
                    "fund_by": "2026-11-10",
                    "min_return_days": 14,
                    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY"]}],
                }
            ),
            "timeline": json.dumps(
                {
                    "open_at": "2026-11-01T00:00:00.000000Z",
                    "close_at": "2026-12-01T00:00:00.000000Z",
                    "beacon_delay_s": 10,
                    "bid_window_s": 120,
                    "offer_window_s": 180,
                    "fund_deadline_s": 600,
                    "capture_grace_s": 120,
                    "pending_wait_s": 120,
                    "max_refill_waves": 1,
                    "authorization_age_guard_s": 216000,
                }
            ),
            "rules_hash": "a" * 64,
            "admin": admin,
        },
    )
    user_id = await buyer(db_session, "retrieval")
    logger = FakeAiRunLogger()
    ai = FakeAI()
    intake = IntakeService(
        search=build_search_service(settings_for()),
        ai=ai,
        audit=PostgresAuditLog(),
        clock=DbClock(),
        run_logger=logger,
        model="fake-model",
    )
    message = "carbon fiber telescope tripod"

    await intake.propose(db_session, user_id=user_id, message=message)
    candidates = ai.calls[-1].payload["candidates"]
    assert [candidate["pool_id"] for candidate in candidates] == [str(pool_id)]
    ai.register_hash(
        ai.calls[-1].input_hash,
        proposal(
            pool_id,
            max_total={"amount": "250.00", "currency": "USD"},
            preferences=[],
        ),
    )

    answer = await intake.propose(db_session, user_id=user_id, message=message)

    assert answer["status"] == "READY_TO_CONFIRM", answer
    assert answer["confirmation_card"]["pool"]["id"] == str(pool_id)


# --------------------------------------------------------------- confirmation


async def test_the_intake_card_notice_does_not_promise_a_hold(
    db_session: AsyncSession,
) -> None:
    """Q-2026-11-01-19: the primary mode places no hold, so the card promises none.

    ``api.md``'s ``no_charge`` sentence says PayPal places a hold; under
    ``PAYMENT_MODE=vault_charge`` nothing is ever held (vault-charge.md section 1) and
    the card cannot know a lot's stamped mode yet, so its notice must not claim one.
    """
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "notice")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=pool_id, overrides={})

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    notice = answer["confirmation_card"]["notices"]["no_charge"]
    assert notice.lower().startswith("nothing is charged now")
    assert "hold" not in notice.lower()


async def test_a_valid_proposal_confirms_the_canonical_request(
    db_session: AsyncSession,
) -> None:
    """T04B01 acceptance: the card is server-built and the confirm writes the request."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "confirm")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=pool_id, overrides={})

    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    assert answer["status"] == "READY_TO_CONFIRM"
    card = answer["confirmation_card"]
    assert card["pool"]["id"] == str(pool_id)
    assert card["pool"]["latest_delivery"] == LATEST_DELIVERY
    assert card["delivery"] == {"zone_id": "US-EAST", "region": "NY"}
    assert card["max_total_cents"] == 60000
    assert card["preferences"] == ["matte screen"]
    assert card["notices"]["no_charge"]
    # The card never carries the model's own words: only the server's fields.
    assert "match_confidence" not in json.dumps(card)

    record = await intake.confirm(
        db_session, user_id=user_id, proposal_id=UUID(card["proposal_id"])
    )

    assert str(record.pool_id) == str(pool_id)
    assert record.canonical_request["required_by"] == "2026-12-15"
    assert record.cap_cents == 60000 and record.zone_id == "US-EAST"
    stored = (
        await db_session.execute(
            text("SELECT proposal, consumed_at FROM intake_proposals WHERE id = :id"),
            {"id": UUID(card["proposal_id"])},
        )
    ).one()
    assert stored.consumed_at is not None
    assert stored.proposal == {
        "delivery": {"region": "NY"},
        "required_by": "2026-12-15",
        "max_total_cents": 60000,
        "firm": [],
        "preferences": ["matte screen"],
    }

    # A second confirm replays the same request instead of writing another one.
    replay = await intake.confirm(
        db_session, user_id=user_id, proposal_id=UUID(card["proposal_id"])
    )
    assert replay.id == record.id
    assert await count(db_session, "confirmed_requests", "user_id = :u", u=user_id) == 1


async def test_another_buyers_proposal_answers_like_an_unknown_one(
    db_session: AsyncSession,
) -> None:
    pool_id = await open_pool(db_session)
    owner = await buyer(db_session, "owner")
    other = await buyer(db_session, "other")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=owner, pool_id=pool_id, overrides={})
    answer = await intake.propose(db_session, user_id=owner, message=MESSAGE)
    proposal_id = UUID(answer["confirmation_card"]["proposal_id"])

    with pytest.raises(ApplicationError) as foreign:
        await intake.confirm(db_session, user_id=other, proposal_id=proposal_id)
    assert foreign.value.code == "NOT_FOUND"

    with pytest.raises(ApplicationError) as unknown:
        await intake.confirm(db_session, user_id=other, proposal_id=uuid4())
    assert unknown.value.code == "NOT_FOUND"


async def test_an_expired_proposal_is_request_invalid(db_session: AsyncSession) -> None:
    """CR-4: past ``expires_at`` the proposal cannot be confirmed or invented."""
    pool_id = await open_pool(db_session)
    user_id = await buyer(db_session, "expired")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=pool_id, overrides={})
    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)
    proposal_id = UUID(answer["confirmation_card"]["proposal_id"])
    await db_session.execute(
        text("UPDATE intake_proposals SET expires_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": proposal_id},
    )

    with pytest.raises(ApplicationError) as expired:
        await intake.confirm(db_session, user_id=user_id, proposal_id=proposal_id)

    assert expired.value.code == "REQUEST_INVALID"


async def test_the_proposal_expires_at_the_pool_close_when_that_is_sooner(
    db_session: AsyncSession,
) -> None:
    """CR-4: ``expires_at = min(now + 30 minutes, the pool's close_at)``."""
    pool_id = await open_pool(db_session, close_in=600)
    user_id = await buyer(db_session, "close-soon")
    intake, _ = service(FakeAI(), pool_id=pool_id)
    await script(intake, db_session, user_id=user_id, pool_id=pool_id, overrides={})
    answer = await intake.propose(db_session, user_id=user_id, message=MESSAGE)

    row = (
        await db_session.execute(
            text(
                "SELECT p.expires_at, (pools.timeline->>'close_at')::timestamptz AS close_at "
                "FROM intake_proposals p JOIN pools ON pools.id = p.pool_id WHERE p.id = :id"
            ),
            {"id": UUID(answer["confirmation_card"]["proposal_id"])},
        )
    ).one()
    assert row.expires_at == row.close_at
