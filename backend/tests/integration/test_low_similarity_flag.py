"""T07B05: the LOW_SIMILARITY advisory after a confirmed bid (INT-1, ai-schemas.md section 7).

The check is retrieval, not judgement: it writes one WARNING flag when another
product outranks the bid's own lot, and it never changes the bid's status. Every
branch the contract names is a test here: own lot first, same product first, no
free text, search unavailable, and one row per revision.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.api.merchant_api.app import app as merchant_api_app
from fairpool.db.models.auction import Bid
from fairpool.fakes.ai import FakeAI
from fairpool.fakes.search import FakeSearch
from fairpool.modules.search.similarity import advise_confirmed_bid
from fairpool.ports import SimilarityResult
from tests.integration.test_bid_sealing import bidding_world, lot_with_deadline
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_merchant_api_keys import create_key, merchant
from tests.integration.test_quote_confirm import (
    REVIEWED_TEXT,
    confirm,
    flags_for,
    save_bid_form,
    script_reconcile,
    seeded_merchant,
    stored_bid,
)

pytestmark = pytest.mark.integration

SETTINGS = settings_for()

#: A reconcile answer with nothing to say: the bid stays CONFIRMED.
CLEAN = {"consistent": True, "flags": []}


class BrokenSearch(FakeSearch):
    """Search that is down: the advisory leg must skip, never fail the confirm."""

    async def similarity_check(self, session: Any, *, lot_id: UUID, text: str) -> SimilarityResult:
        del text
        raise RuntimeError(f"search backend unavailable for lot {lot_id}")


@asynccontextmanager
async def harness(
    db_session: AsyncSession, *, search: FakeSearch, ai: FakeAI
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)
    app.state.search_service = search
    app.state.auction_ai = ai

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def confirmed_bid(
    client: httpx.AsyncClient, db_session: AsyncSession, lot_id: UUID, *, quote_text: str
) -> UUID:
    csrf = await seeded_merchant(client, db_session)
    bid_id = await save_bid_form(client, csrf, lot_id, quote_text=quote_text)
    assert await confirm(client, csrf, bid_id) == "CONFIRMED"
    return bid_id


@asynccontextmanager
async def agent_api_harness(
    db_session: AsyncSession, *, search: FakeSearch, ai: FakeAI
) -> AsyncIterator[httpx.AsyncClient]:
    """The mounted Merchant Agent API: a sub-app does not inherit the parent's state."""
    app = create_app(SETTINGS)
    merchant_api_app.state.search_service = search
    merchant_api_app.state.auction_ai = ai

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    merchant_api_app.dependency_overrides[database_session] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://api.test"
        ) as http:
            yield http
    finally:
        merchant_api_app.dependency_overrides.clear()
        for name in ("search_service", "auction_ai"):
            if hasattr(merchant_api_app.state, name):
                delattr(merchant_api_app.state, name)


async def test_a_different_product_ranked_first_writes_one_warning(
    db_session: AsyncSession,
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = FakeSearch(similarity={lot_id: SimilarityResult(2, uuid4(), "desk-lamp-9")})
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text=REVIEWED_TEXT)

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None and str(bid.status) == "CONFIRMED", "a WARNING changes nothing"
    rows = await flags_for(db_session, bid)
    assert [(str(row.code), str(row.severity)) for row in rows] == [("LOW_SIMILARITY", "WARNING")]
    assert len(str(rows[0].evidence)) <= 200, "the evidence column limit (db-schema.md)"
    run = (
        await db_session.execute(
            text("SELECT task, tokens_in, tokens_out, error FROM ai_runs WHERE id = :id"),
            {"id": rows[0].ai_run_id},
        )
    ).one()
    assert str(run[0]) == "SIM_TEXT"
    assert (run[1], run[2], run[3]) == (0, 0, None)
    assert search.similarity_calls[0].lot_id == lot_id
    assert REVIEWED_TEXT in search.similarity_calls[0].text


async def test_the_own_lot_ranked_first_writes_no_flag(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = FakeSearch(similarity={lot_id: SimilarityResult(1, lot_id, "monitor-27-4k")})
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text=REVIEWED_TEXT)

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None
    assert await flags_for(db_session, bid) == []


async def test_the_same_product_ranked_first_writes_no_flag(
    db_session: AsyncSession,
) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    # The lot's own document is not in the top hits, but the top hit is the same product.
    search = FakeSearch(similarity={lot_id: SimilarityResult(None, uuid4(), "monitor-27-4k")})
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text=REVIEWED_TEXT)

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None
    assert await flags_for(db_session, bid) == []


async def test_no_free_text_means_no_check(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = FakeSearch(similarity={lot_id: SimilarityResult(2, uuid4(), "desk-lamp-9")})
    ai = FakeAI()

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text="")

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None
    assert await flags_for(db_session, bid) == []
    assert search.similarity_calls == []


async def test_a_failing_search_never_fails_the_confirm(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = BrokenSearch()
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text=REVIEWED_TEXT)

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None and str(bid.status) == "CONFIRMED"
    assert await flags_for(db_session, bid) == []


async def test_one_warning_row_per_revision(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = FakeSearch(similarity={lot_id: SimilarityResult(3, uuid4(), "desk-lamp-9")})
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with harness(db_session, search=search, ai=ai) as client:
        bid_id = await confirmed_bid(client, db_session, lot_id, quote_text=REVIEWED_TEXT)

    bid = await db_session.get(Bid, bid_id)
    assert bid is not None
    assert len(await flags_for(db_session, bid)) == 1
    # A second run of the same check (a retried advise) must not stack rows.
    for _ in range(2):
        await advise_confirmed_bid(
            db_session,
            settings=SETTINGS,
            search=search,
            bid_id=bid_id,
        )
    rows = await flags_for(db_session, bid)
    assert len(rows) == 1
    assert str(rows[0].code) == "LOW_SIMILARITY"


async def test_the_agent_api_door_writes_the_same_warning(db_session: AsyncSession) -> None:
    """PT-15 parity: an API-key bid and a console bid run the one advisory hook."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    search = FakeSearch(similarity={lot_id: SimilarityResult(2, uuid4(), "desk-lamp-9")})
    ai = FakeAI()
    script_reconcile(ai, text=REVIEWED_TEXT, answer=CLEAN)

    async with agent_api_harness(db_session, search=search, ai=ai) as client:
        csrf, _merchant_id = await merchant(client, db_session, "api-sim@example.test")
        created = await create_key(client, csrf, ["bids:write", "bids:read"])
        headers = {"Authorization": f"Bearer {created['key']}"}
        response = await client.put(
            f"/merchant-api/v1/lots/{lot_id}/bid",
            headers={**headers, "Idempotency-Key": "agent-api-similarity"},
            json={"structured": stored_bid(), "notes": REVIEWED_TEXT, "confirmed": True},
        )
        assert response.status_code == 200, response.text
        bid_id = UUID(str(response.json()["bid_id"]))
        # The advisory row is readable through the same scoped bid view as the console's.
        read_back = await client.get(f"/merchant-api/v1/bids/{bid_id}", headers=headers)
        assert read_back.status_code == 200, read_back.text

    flags = read_back.json()["flags"]
    assert len(flags) == 1
    assert (flags[0]["code"], flags[0]["severity"], flags[0]["field"]) == (
        "LOW_SIMILARITY",
        "WARNING",
        "product_key",
    )
    assert response.json()["status"] == "CONFIRMED"
    bid = await db_session.get(Bid, bid_id)
    assert bid is not None and str(bid.status) == "CONFIRMED", "a WARNING changes nothing"
    rows = await flags_for(db_session, bid)
    assert [(str(row.code), str(row.severity)) for row in rows] == [("LOW_SIMILARITY", "WARNING")]
    assert search.similarity_calls[0].lot_id == lot_id
    assert REVIEWED_TEXT in search.similarity_calls[0].text
