"""Behaviour of the deterministic port fakes (T01B02)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain import hashing
from fairpool.fakes import (
    DEFAULT_PAYEE,
    FakeAI,
    FakeAICall,
    FakeAIInvalidJSON,
    FakeAiRunLogger,
    FakeAITimeout,
    FakeAllocationRead,
    FakeBeacon,
    FakeMerchantAuth,
    FakeMerchantDirectory,
    FakeNotifier,
    FakeSearch,
    FakeSearchIndexer,
    MerchantAuthError,
    SearchDocument,
    make_award_fixture,
)
from fairpool.ports import (
    AIClient,
    AiRunLogger,
    AllocationReadService,
    BeaconClient,
    MerchantAuth,
    MerchantDirectory,
    MerchantPrincipal,
    Notifier,
    SearchIndexer,
    SearchService,
    SimilarityResult,
)

SESSION = cast(AsyncSession, None)
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
MERCHANT_ID = UUID("22222222-2222-4222-8222-222222222222")
POOL_ID = UUID("33333333-3333-4333-8333-333333333333")
LOT_ID = UUID("44444444-4444-4444-8444-444444444444")
OTHER_LOT_ID = UUID("55555555-5555-4555-8555-555555555555")


def test_fakes_satisfy_their_ports() -> None:
    fixture = make_award_fixture()
    assert isinstance(FakeNotifier(), Notifier)
    assert isinstance(FakeBeacon(), BeaconClient)
    assert isinstance(FakeAiRunLogger(), AiRunLogger)
    assert isinstance(FakeAI(), AIClient)
    assert isinstance(FakeSearch(), SearchService)
    assert isinstance(FakeSearchIndexer(), SearchIndexer)
    assert isinstance(FakeMerchantAuth(), MerchantAuth)
    assert isinstance(FakeAllocationRead(fixture), AllocationReadService)
    assert isinstance(FakeMerchantDirectory(), MerchantDirectory)


async def test_notifier_records_notifications() -> None:
    notifier = FakeNotifier()
    await notifier.notify(SESSION, user_id=USER_ID, kind="offer_created", payload={"lot_id": "x"})
    assert notifier.calls[0].user_id == USER_ID
    assert notifier.calls[0].kind == "offer_created"
    assert notifier.calls[0].payload == {"lot_id": "x"}


async def test_beacon_returns_fixed_values_and_honours_unavailable() -> None:
    announced = {"source": "demo"}
    fetched = {
        "source": "demo",
        "randomness": "ab" * 32,
        "signature": "cd" * 64,
    }
    close_at = datetime(2026, 11, 2, 10, 3, tzinfo=UTC)
    beacon = FakeBeacon(announced=announced, fetched=fetched)
    assert await beacon.announce(close_at=close_at, delay_s=10) == announced
    assert await beacon.fetch(announced) == fetched
    assert beacon.announce_calls[0].delay_s == 10

    unavailable = FakeBeacon(announced=announced, available=False)
    assert await unavailable.fetch(announced) is None
    assert unavailable.fetch_calls[0].announced == announced


async def test_ai_logger_records_runs_and_returns_deterministic_ids() -> None:
    logger = FakeAiRunLogger()
    run_id = await logger.log(
        SESSION,
        task="INTAKE",
        model="test-model",
        prompt_version="v1",
        input_hash="a" * 64,
        output={"match_confidence": "high"},
        ok=True,
        error=None,
        latency_ms=12,
        tokens_in=20,
        tokens_out=30,
    )
    repeated = await FakeAiRunLogger().log(
        SESSION,
        task="INTAKE",
        model="test-model",
        prompt_version="v1",
        input_hash="a" * 64,
        output={"match_confidence": "high"},
        ok=True,
        error=None,
        latency_ms=12,
        tokens_in=20,
        tokens_out=30,
    )
    assert isinstance(run_id, UUID)
    assert run_id == repeated
    assert logger.calls[0].tokens_out == 30
    assert logger.calls[0].output == {"match_confidence": "high"}


async def test_fake_ai_serves_all_four_methods_from_the_hash_table() -> None:
    fake = FakeAI()
    intake_input = {"message": "need a monitor", "candidates": [], "history": []}
    quote_input = {"quote_text": "470 each", "lot_requirement": {"product_key": "monitor"}}
    reconcile_input = {
        "lot_requirement": {"product_key": "monitor"},
        "bid_structured": {"moq": 2},
        "text": "470 each",
    }
    sim_input = {"kind": "buyer_message", "facts": {"cap_cents": 60000}}
    intake_hash = fake.register("parse_intake", intake_input, {"match_confidence": "high"})
    fake.register("parse_quote", quote_input, {"moq": 2})
    fake.register("reconcile_offer", reconcile_input, {"consistent": True, "flags": []})
    fake.register("sim_text", sim_input, "SIMULATED message")

    assert await fake.parse_intake(
        SESSION,
        message="need a monitor",
        candidates=[],
        history=[],
    ) == {"match_confidence": "high"}
    assert await fake.parse_quote(
        SESSION,
        quote_text="470 each",
        lot_requirement={"product_key": "monitor"},
    ) == {"moq": 2}
    assert await fake.reconcile_offer(
        SESSION,
        lot_requirement={"product_key": "monitor"},
        bid_structured={"moq": 2},
        text="470 each",
    ) == {"consistent": True, "flags": []}
    assert (
        await fake.sim_text(
            SESSION,
            kind="buyer_message",
            facts={"cap_cents": 60000},
        )
        == "SIMULATED message"
    )

    assert intake_hash == FakeAI.input_hash("parse_intake", intake_input)
    assert [call.task for call in fake.calls] == [
        "parse_intake",
        "parse_quote",
        "reconcile_offer",
        "sim_text",
    ]
    assert fake.calls[0] == FakeAICall(
        task="parse_intake",
        input_hash=intake_hash,
        payload=intake_input,
    )


async def test_fake_ai_can_simulate_invalid_json_and_timeout() -> None:
    invalid = FakeAI(mode="invalid_json")
    with pytest.raises(FakeAIInvalidJSON):
        await invalid.parse_intake(SESSION, message="x", candidates=[], history=[])
    timeout = FakeAI(mode="timeout")
    with pytest.raises(FakeAITimeout):
        await timeout.sim_text(SESSION, kind="buyer_message", facts={})


async def test_search_matches_substrings_and_applies_filters() -> None:
    docs = (
        SearchDocument(
            doc_id="pool-1",
            doc_kind="pool",
            pool_id=POOL_ID,
            lot_id=None,
            product_key="monitor-27-4k",
            title="27-inch 4K monitor",
            content="black monitor with stand",
            status="OPEN",
        ),
        SearchDocument(
            doc_id="lot-1",
            doc_kind="lot",
            pool_id=POOL_ID,
            lot_id=LOT_ID,
            product_key="monitor-27-4k",
            title="US East monitor lot",
            content="delivery to NY",
            status="BIDDING",
        ),
        SearchDocument(
            doc_id="lot-2",
            doc_kind="lot",
            pool_id=POOL_ID,
            lot_id=OTHER_LOT_ID,
            product_key="keyboard",
            title="Keyboard lot",
            content="mechanical keyboard",
            status="BIDDING",
        ),
    )
    service = FakeSearch(documents=docs)

    hits = await service.search(
        SESSION,
        q="MONITOR",
        kinds=["lot"],
        status=["BIDDING"],
        limit=10,
    )
    assert [hit.doc_id for hit in hits] == ["lot-1"]
    assert hits[0].score == 1.0
    assert service.search_calls[0].kinds == ("lot",)

    pooled = await service.search(SESSION, q="monitor", kinds=["pool"], status=None, limit=10)
    assert [hit.doc_id for hit in pooled] == ["pool-1"]
    limited = await service.search(
        SESSION,
        q="monitor",
        kinds=["pool", "lot"],
        status=None,
        limit=1,
    )
    assert len(limited) == 1
    assert await service.search(SESSION, q="nomatch", kinds=["lot"], status=None, limit=10) == []


async def test_search_similarity_results_are_scripted() -> None:
    service = FakeSearch()
    scripted = SimilarityResult(own_rank=2, top_lot_id=LOT_ID, top_product_key="keyboard")
    service.script_similarity(LOT_ID, scripted)
    assert await service.similarity_check(SESSION, lot_id=LOT_ID, text="quote") == scripted
    assert service.similarity_calls[0].text == "quote"
    assert await service.similarity_check(
        SESSION, lot_id=OTHER_LOT_ID, text="other"
    ) == SimilarityResult(None, None, None)


async def test_search_indexer_records_upserts_and_deletes() -> None:
    indexer = FakeSearchIndexer()
    await indexer.upsert(SESSION, doc_kind="pool", doc_id=POOL_ID)
    await indexer.upsert(SESSION, doc_kind="lot", doc_id=LOT_ID)
    await indexer.delete(SESSION, doc_kind="lot", doc_id=LOT_ID)
    assert [(item.doc_kind, item.doc_id) for item in indexer.upserts] == [
        ("pool", POOL_ID),
        ("lot", LOT_ID),
    ]
    assert [(item.doc_kind, item.doc_id) for item in indexer.deletes] == [("lot", LOT_ID)]


async def test_merchant_auth_rejects_unknown_and_revoked_keys() -> None:
    principal = MerchantPrincipal(
        merchant_id=MERCHANT_ID,
        scopes=frozenset({"merchant:read"}),
        via="api_key",
    )
    session_principal = MerchantPrincipal(
        merchant_id=MERCHANT_ID,
        scopes=frozenset({"merchant:write"}),
        via="session",
    )
    auth = FakeMerchantAuth(
        api_keys={"tok-1": principal},
        sessions={USER_ID: session_principal},
    )
    assert await auth.from_api_key(SESSION, "tok-1") == principal
    assert await auth.from_session(SESSION, USER_ID) == session_principal

    with pytest.raises(MerchantAuthError) as unknown:
        await auth.from_api_key(SESSION, "unknown")
    assert str(unknown.value) == "API_KEY_INVALID"

    auth.revoke("tok-1")
    with pytest.raises(MerchantAuthError) as revoked:
        await auth.from_api_key(SESSION, "tok-1")
    assert str(revoked.value) == "API_KEY_INVALID"

    with pytest.raises(MerchantAuthError):
        await auth.from_session(SESSION, OTHER_LOT_ID)
    assert auth.calls[0].principal == hashing.sha256_hex("tok-1")
    assert "tok-1" not in repr(auth.calls)


async def test_allocation_fake_promotes_within_cap_and_skips_over_cap() -> None:
    fixture = make_award_fixture()
    service = FakeAllocationRead(fixture)
    assert await service.get_lot(SESSION, fixture.lot.id) == fixture.lot
    assert await service.get_award(SESSION, fixture.lot.id) == fixture.award

    priced_out = fixture.priced_out
    seated = await service.list_seated(SESSION, fixture.lot.id)
    assert {seat.entry_id for seat in seated} == {
        seat.entry_id for seat in fixture.seats if seat.entry_id != priced_out
    }

    over_cap, within_cap = fixture.waitlist
    assert over_cap.cap_cents < fixture.award.totals[over_cap.entry_id].total_cents
    assert within_cap.cap_cents >= fixture.award.totals[within_cap.entry_id].total_cents

    promoted = await service.next_candidates(SESSION, fixture.lot.id, count=2)
    assert [seat.entry_id for seat in promoted] == [within_cap.entry_id]
    assert service.status_of(within_cap.entry_id) == "SEATED"
    assert service.lot_id_of(within_cap.entry_id) == fixture.lot.id
    assert service.status_of(over_cap.entry_id) == "WAITLISTED"
    assert len(await service.list_seated(SESSION, fixture.lot.id)) == 3
    assert await service.next_candidates(SESSION, fixture.lot.id, count=1) == []
    assert [call.method for call in service.calls] == [
        "get_lot",
        "get_award",
        "list_seated",
        "next_candidates",
        "list_seated",
        "next_candidates",
    ]


async def test_merchant_directory_returns_fixture_payee() -> None:
    directory = FakeMerchantDirectory(payees={DEFAULT_PAYEE.merchant_id: DEFAULT_PAYEE})
    assert await directory.get_payee(SESSION, DEFAULT_PAYEE.merchant_id) == DEFAULT_PAYEE
    with pytest.raises(KeyError):
        await directory.get_payee(SESSION, MERCHANT_ID)
    assert directory.calls[0].merchant_id == DEFAULT_PAYEE.merchant_id
