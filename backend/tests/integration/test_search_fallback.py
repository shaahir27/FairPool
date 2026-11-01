"""T03B02: one port, two backends, and a fallback that never fails the caller.

Postgres is the always-runnable half and carries every assertion here. The Elastic
half runs against a clearly named recording client (a mock: unit evidence, not
Elastic behaviour, rule 18) plus one live parity test that states out loud when it
was not executed (OD-P3-3). No test here opens a network connection.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.search.elastic import ElasticSearchBackend
from fairpool.adapters.search.postgres import PostgresSearchBackend
from fairpool.adapters.search.projection import (
    LOT_DOC,
    POOL_DOC,
    PublicDocument,
    public_documents_select,
)
from fairpool.api.app import create_app
from fairpool.api.deps import database_session, require_admin
from fairpool.fakes.beacon import FakeBeacon
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.identity.service import Principal
from fairpool.modules.pools.service import PoolService
from fairpool.modules.search.handlers import search_index_handler
from fairpool.modules.search.indexer import SearchDocumentIndexer
from fairpool.modules.search.service import SearchRoutingService
from fairpool.ports import SearchHit, SimilarityResult
from tests.unit.test_search_projection import (
    INFERENCE_ID,
    RecordingClient,
    StatusError,
    document,
)
from tests.unit.test_settings import make_settings

URL = "https://elastic.example.test"
API_KEY = "dummy-key-never-logged"


def new_id() -> uuid.UUID:
    return uuid.UUID(str(uuid.uuid4()))


async def add_pool(
    session: AsyncSession,
    *,
    title: str = "Fictional zephyr pool",
    status: str = "OPEN",
    product_key: str = "zephyr-quixote-9k",
    search_text: str = "Fictional zephyr pool zephyr-quixote-9k black NEW quixote NY",
    zone_id: str = "US-EAST",
) -> uuid.UUID:
    pool_id = new_id()
    admin = new_id()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', 'admin', 'Test Admin')"
        ),
        {"id": admin, "email": f"admin-{pool_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO pools (id, mode, status, title, template, lot_plan, timeline, "
            "require_paypal_link, rule_version, created_by, search_text) "
            "VALUES (:id, 'LIVE_SANDBOX', CAST(:status AS pool_status), :title, "
            "CAST(:template AS jsonb), '[]'::jsonb, CAST(:timeline AS jsonb), "
            "false, 'allocation_v1', :created_by, :search_text)"
        ),
        {
            "id": pool_id,
            "status": status,
            "title": title,
            "search_text": search_text,
            "created_by": admin,
            "template": json.dumps(
                {
                    "product_key": product_key,
                    "variant": "black",
                    "title": title,
                    "condition": "NEW",
                    "quantity": 1,
                    "currency": "USD",
                    "bundle_contents": ["quixote", "stand"],
                    "delivery_sla_days": 7,
                    "fund_by": "2026-11-10",
                    "min_return_days": 14,
                    "zones": [{"zone_id": zone_id, "label": "US East", "regions": ["NY"]}],
                }
            ),
            "timeline": json.dumps(
                {
                    "open_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                    "close_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                }
            ),
        },
    )
    return pool_id


async def add_lot(
    session: AsyncSession,
    pool_id: uuid.UUID,
    *,
    status: str = "BIDDING",
    zone_id: str = "US-EAST",
    seats: int = 3,
    lot_order: int = 0,
) -> uuid.UUID:
    lot_id = new_id()
    await session.execute(
        text(
            "INSERT INTO lots (id, pool_id, zone_id, lot_index, lot_order, seats, min_seats, "
            "status, bid_open_at, bid_close_at) VALUES (:id, :pool, :zone, 0, :order, "
            ":seats, 2, CAST(:status AS lot_status), now(), now())"
        ),
        {
            "id": lot_id,
            "pool": pool_id,
            "zone": zone_id,
            "order": lot_order,
            "seats": seats,
            "status": status,
        },
    )
    return lot_id


def elastic(client: Any) -> ElasticSearchBackend:
    return ElasticSearchBackend(
        url=URL,
        api_key=API_KEY,
        inference_id=INFERENCE_ID,
        index_prefix="fairpool",
        timeout_ms=1000,
        client=client,
    )


def service(
    *, backend: str = "elastic", client: Any | None = None, similarity_check_enabled: bool = True
) -> SearchRoutingService:
    """The service under test: Postgres is real, Elastic is a named mock."""
    return SearchRoutingService(
        postgres=PostgresSearchBackend(),
        elastic=elastic(client if client is not None else RecordingClient()),
        backend=backend,
        similarity_check_enabled=similarity_check_enabled,
    )


def response_of(*documents: PublicDocument) -> dict[str, Any]:
    return {
        "hits": {
            "hits": [
                {
                    "_id": str(doc.doc_id),
                    "_score": 1.0,
                    "_source": {
                        "doc_kind": doc.doc_kind,
                        "pool_id": str(doc.pool_id),
                        "lot_id": str(doc.lot_id) if doc.lot_id else None,
                        "status": doc.status,
                        "product_key": doc.product_key,
                        "condition": doc.condition,
                        "title": doc.title,
                    },
                }
                for doc in documents
            ]
        }
    }


async def pending_jobs(session: AsyncSession, kind: str = "search.index") -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text("SELECT payload, concurrency_key, dedupe_key, status FROM jobs WHERE kind=:kind"),
            {"kind": kind},
        )
    ).all()
    return [{"payload": row[0], "ck": row[1], "dedupe": row[2], "status": row[3]} for row in rows]


# --- the Postgres backend covers both kinds, in the shared shape --------------------


async def test_postgres_backend_returns_pool_and_lot_documents(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    hits = await PostgresSearchBackend().search(
        db_session, q="quixote 9k", kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
    )
    assert {hit.doc_kind for hit in hits} == {POOL_DOC, LOT_DOC}
    assert {hit.doc_id for hit in hits} == {str(pool_id), str(lot_id)}
    assert all(isinstance(hit, SearchHit) for hit in hits)
    assert all(hit.score > 0 for hit in hits)


async def test_status_filter_narrows_both_kinds(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool", status="OPEN")
    lot_id = await add_lot(db_session, pool_id, status="BIDDING")
    pools = await PostgresSearchBackend().search(
        db_session, q="quixote", kinds=[POOL_DOC], status=["OPEN"], limit=10
    )
    lots = await PostgresSearchBackend().search(
        db_session, q="quixote", kinds=[LOT_DOC], status=["BIDDING"], limit=10
    )
    assert [hit.doc_id for hit in pools] == [str(pool_id)]
    assert [hit.doc_id for hit in lots] == [str(lot_id)]
    other = await PostgresSearchBackend().search(
        db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=["FUNDED"], limit=10
    )
    assert other == []


async def test_empty_query_returns_nothing(db_session: AsyncSession) -> None:
    await add_pool(db_session, title="Fictional zephyr pool")
    assert (
        await PostgresSearchBackend().search(
            db_session, q="   ", kinds=[POOL_DOC], status=None, limit=10
        )
    ) == []


async def test_both_backends_return_the_identical_hit_shape(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    postgres_hits = await PostgresSearchBackend().search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    client = RecordingClient(
        response=response_of(document(pool_id=pool_id, doc_kind=POOL_DOC, lot_id=None))
    )
    elastic_hits = await elastic(client).search(
        None, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert postgres_hits and elastic_hits
    for hit in (*postgres_hits, *elastic_hits):
        assert isinstance(hit, SearchHit)
    assert [tuple(vars(hit)) for hit in postgres_hits] == [tuple(vars(hit)) for hit in elastic_hits]
    assert type(elastic_hits[0].pool_id) is type(postgres_hits[0].pool_id)


# --- fallback: Elastic is best-effort, Postgres is the answer ----------------------


async def test_inference_failure_falls_back_to_postgres(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    # The recorded S8 failure mode: the local inference endpoint returned 429.
    client = RecordingClient(error=StatusError(429))
    hits = await service(client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert [hit.doc_id for hit in hits] == [str(pool_id)]


async def test_permission_and_missing_index_failures_fall_back(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    for status_code in (401, 403, 404):
        hits = await service(client=RecordingClient(error=StatusError(status_code))).search(
            db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
        )
        assert [hit.doc_id for hit in hits] == [str(pool_id)], status_code


async def test_timeout_falls_back_within_the_search_budget(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")

    class SlowClient:
        async def search(self, **kwargs: Any) -> Any:
            await asyncio.sleep(5)
            raise AssertionError("unreachable")

    started = asyncio.get_running_loop().time()
    hits = await service(client=SlowClient()).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert asyncio.get_running_loop().time() - started < 2
    assert [hit.doc_id for hit in hits] == [str(pool_id)]


async def test_an_empty_index_answers_from_postgres(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient(response={"hits": {"hits": []}})
    hits = await service(client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert [hit.doc_id for hit in hits] == [str(pool_id)]


async def test_stale_and_private_hits_are_dropped_after_hydration(
    db_session: AsyncSession,
) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    draft_id = await add_pool(db_session, title="Fictional draft monitor pool", status="DRAFT")
    stale = document(pool_id=draft_id, doc_kind=POOL_DOC, lot_id=None)
    gone = document(pool_id=new_id(), doc_kind=POOL_DOC, lot_id=None)
    live = document(pool_id=pool_id, doc_kind=POOL_DOC, lot_id=None)
    client = RecordingClient(response=response_of(stale, live, gone))
    hits = await service(client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert [hit.doc_id for hit in hits] == [str(pool_id)]


async def test_hydration_refreshes_a_hit_that_moved(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    stale_title = document(pool_id=pool_id, doc_kind=POOL_DOC, lot_id=None, title="Old title")
    client = RecordingClient(response=response_of(stale_title))
    (hit,) = await service(client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert hit.title == "Fictional zephyr pool"  # the committed row, not the index
    assert hit.score == 1.0  # the retrieval score stays


async def test_the_page_is_topped_up_from_the_fallback(db_session: AsyncSession) -> None:
    first = await add_pool(db_session, title="Fictional zephyr pool one")
    second = await add_pool(db_session, title="Fictional zephyr pool two")
    # The mock answers with one document only (a partially populated index).
    client = RecordingClient(response=response_of(document(pool_id=first, doc_kind=POOL_DOC)))
    hits = await service(client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=2
    )
    assert len(hits) == 2
    assert {hit.doc_id for hit in hits} == {str(first), str(second)}


async def test_postgres_only_backend_does_not_query_elastic(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient(error=AssertionError("must not be called"))
    hits = await service(backend="postgres", client=client).search(
        db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5
    )
    assert [hit.doc_id for hit in hits] == [str(pool_id)]


# --- the advisory similarity check (never a gate) ----------------------------------


async def test_similarity_check_ranks_the_lots_own_document(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    client = RecordingClient(
        response=response_of(
            document(pool_id=pool_id, lot_id=lot_id, doc_kind=LOT_DOC, status="BIDDING")
        )
    )
    result = await service(client=client).similarity_check(
        db_session, lot_id=lot_id, text="zephyr quixote 9k black NEW"
    )
    assert result == SimilarityResult(1, lot_id, "zephyr-quixote-9k")
    # The advisory leg is the recorded semantic-only request over open lots.
    op, kwargs = client.calls[0]
    assert op == "search"
    assert kwargs["body"]["query"]["bool"]["must"][0]["semantic"]["field"] == "content_embedding"
    assert {"terms": {"doc_kind": ["lot"]}} in kwargs["body"]["query"]["bool"]["filter"]
    assert {"terms": {"status": ["BIDDING"]}} in kwargs["body"]["query"]["bool"]["filter"]


async def test_similarity_check_on_an_outage_returns_no_flag(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    result = await service(client=RecordingClient(error=StatusError(429))).similarity_check(
        db_session, lot_id=lot_id, text="zephyr quixote 9k"
    )
    assert result == SimilarityResult(None, None, None)


async def test_similarity_check_is_skipped_when_disabled_or_empty(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    client = RecordingClient()
    disabled = service(client=client, similarity_check_enabled=False)
    assert await disabled.similarity_check(db_session, lot_id=lot_id, text="quixote") == (
        SimilarityResult(None, None, None)
    )
    empty = service(client=client)
    assert await empty.similarity_check(db_session, lot_id=lot_id, text="   ") == (
        SimilarityResult(None, None, None)
    )
    assert client.calls == []


async def test_similarity_check_over_postgres_never_raises(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    result = await service(backend="postgres").similarity_check(
        db_session, lot_id=lot_id, text="zephyr quixote 9k"
    )
    assert isinstance(result, SimilarityResult)
    assert result.top_product_key == "zephyr-quixote-9k"


# --- indexing: repeatable, projected from the row, never blocking ------------------


async def test_upsert_is_repeatable_and_keyed_by_the_row_id(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient()
    indexer = SearchDocumentIndexer(elastic=elastic(client))
    await indexer.upsert(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    await indexer.upsert(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    writes = [kwargs for name, kwargs in client.calls if name == "index"]
    assert [write["id"] for write in writes] == [str(pool_id), str(pool_id)]


async def test_upsert_rereads_the_committed_row_and_the_handler_uses_ids_only(
    db_session: AsyncSession,
) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient()
    handler = search_index_handler(SearchDocumentIndexer(elastic=elastic(client)))
    payload = {"pool_id": str(pool_id), "doc_kind": POOL_DOC, "doc_id": str(pool_id)}
    await handler(db_session, payload)
    await db_session.execute(
        text("UPDATE pools SET title = 'Renamed monitor pool' WHERE id = :id"), {"id": pool_id}
    )
    await handler(db_session, payload)  # the same job delivered twice (at-least-once)
    writes = [kwargs["document"] for name, kwargs in client.calls if name == "index"]
    assert len(writes) == 2
    assert writes[0]["title"] == "Fictional zephyr pool"
    assert writes[1]["title"] == "Renamed monitor pool"
    assert set(payload) <= {"pool_id", "doc_kind", "doc_id"}  # payload carries ids only


async def test_a_lot_that_leaves_the_visible_set_is_deleted(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    client = RecordingClient()
    indexer = SearchDocumentIndexer(elastic=elastic(client))
    await indexer.upsert(db_session, doc_kind=LOT_DOC, doc_id=lot_id)
    await db_session.execute(
        text("UPDATE lots SET status = 'CANCELLED'::lot_status WHERE id = :id"), {"id": lot_id}
    )
    await indexer.upsert(db_session, doc_kind=LOT_DOC, doc_id=lot_id)
    names = [name for name, _ in client.calls]
    assert names == ["indices.exists", "index", "indices.exists", "delete"]


async def test_delete_repeats_safely(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient()
    indexer = SearchDocumentIndexer(elastic=elastic(client))
    await indexer.delete(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    await indexer.delete(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    assert [name for name, _ in client.calls].count("delete") == 2


async def test_an_indexing_outage_never_raises_and_never_blocks_publication(
    db_session: AsyncSession,
) -> None:
    pool_service = PoolService(DbClock(), PostgresAuditLog(), PostgresJobQueue(), FakeBeacon())
    admin = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', 'admin', 'Publisher')"
        ),
        {"id": admin, "email": f"publisher-{admin}@example.test"},
    )
    now = await DbClock().db_now(db_session)
    pool = await pool_service.create(
        db_session,
        actor_id=admin,
        payload=_pool_input(now),
    )
    client = RecordingClient(error=StatusError(429))
    indexer = SearchDocumentIndexer(elastic=elastic(client))
    published = await pool_service.publish(db_session, pool.id, actor_id=admin)
    assert str(published.status) == "PUBLISHED"
    jobs = await pending_jobs(db_session)
    assert [job["payload"]["doc_id"] for job in jobs] == [str(pool.id)]
    assert all(job["status"] == "PENDING" for job in jobs)
    # The job runs later; a dead Elastic index is logged, not raised.
    await search_index_handler(indexer)(db_session, jobs[0]["payload"])
    assert [name for name, _ in client.calls] == ["indices.exists", "index"]


def _pool_input(now: datetime) -> Any:
    from fairpool.domain.pool_config import PoolInput

    return PoolInput.model_validate(
        {
            "title": "Fictional publication pool",
            "template": {
                "product_key": "zephyr-quixote-9k",
                "variant": "black",
                "title": "Monitor",
                "condition": "NEW",
                "quantity": 1,
                "currency": "USD",
                "bundle_contents": ["monitor"],
                "delivery_sla_days": 7,
                "fund_by": "2026-12-01",
                "min_return_days": 14,
                "zones": [{"zone_id": "US-EAST", "label": "East", "regions": ["NY"]}],
            },
            "lot_plan": [{"zone_id": "US-EAST", "lots": [{"seats": 3, "min_seats": 2}]}],
            "timeline": {
                "open_at": (now + timedelta(minutes=1)).isoformat(),
                "close_at": (now + timedelta(minutes=4)).isoformat(),
            },
            "require_paypal_link": False,
            "rule_version": "allocation_v1",
        }
    )


# --- the admin reindex route -------------------------------------------------------


async def test_reindex_requires_admin_without_a_session(db_session: AsyncSession) -> None:
    app = create_app(make_settings())

    async def db() -> Any:
        yield db_session

    app.dependency_overrides[database_session] = db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as client:
        response = await client.post("/api/v1/admin/search/reindex")
    assert response.status_code == 401


async def test_reindex_pages_and_re_enqueues_one_job_per_document(
    db_session: AsyncSession,
) -> None:
    first = await add_pool(db_session, title="Fictional zephyr pool one")
    second = await add_pool(db_session, title="Fictional zephyr pool two")
    lot_id = await add_lot(db_session, first)
    draft = await add_pool(db_session, title="Fictional draft pool", status="DRAFT")

    # The route pages over the committed catalogue, which in this shared test database
    # also holds rows other suites committed, so the expected set comes from the same
    # projection the route reads. The promise under test is the partition and the
    # per-document re-enqueue, not the size of the catalogue.
    expected = {
        (doc_kind, str(doc_id))
        for doc_kind, doc_id in (await db_session.execute(public_documents_select())).all()
    }
    assert {(POOL_DOC, str(first)), (POOL_DOC, str(second)), (LOT_DOC, str(lot_id))} <= expected
    assert (POOL_DOC, str(draft)) not in expected  # a DRAFT pool is never reindexed

    app = create_app(make_settings())

    async def db() -> Any:
        yield db_session

    app.dependency_overrides[database_session] = db
    app.dependency_overrides[require_admin] = lambda: Principal(
        user_id=uuid.uuid4(), session_id=uuid.uuid4(), role="admin"
    )
    step = 2
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as client:
        documents = 0
        page = 0
        while True:
            body = (
                await client.post(f"/api/v1/admin/search/reindex?page={page}&page_size={step}")
            ).json()
            assert body["page"] == page
            assert body["page_size"] == step
            assert body["documents"] <= step
            # One job per document on this page, nothing more and nothing skipped.
            assert body["enqueued"] == body["documents"]
            documents += body["documents"]
            if not body["has_more"]:
                break
            page += 1
        assert documents == len(expected)
        assert page == -(-len(expected) // step) - 1  # the last page index, ceil(total/step)

        # A second pass over the same page coalesces on the dedupe key: no duplicate work.
        repeat = (await client.post("/api/v1/admin/search/reindex?page=0&page_size=2")).json()
        assert repeat["documents"] == min(2, len(expected))
        assert repeat["enqueued"] == 0
        assert (
            await client.post("/api/v1/admin/search/reindex?page=0&page_size=0")
        ).status_code == 422
        assert (await client.post("/api/v1/admin/search/reindex?page=-1")).status_code == 422

    jobs = await pending_jobs(db_session)
    seen = {(job["payload"]["doc_kind"], job["payload"]["doc_id"]) for job in jobs}
    assert seen == expected
    assert len(jobs) == len(expected)  # no page enqueued the same document twice
    assert all(
        job["dedupe"] == f"search:{job['payload']['doc_kind']}:{job['payload']['doc_id']}"
        for job in jobs
    )
    assert all(job["ck"] == job["dedupe"] for job in jobs)
    # Reindex payloads carry ids only: no indexed text leaves this route (rule 23).
    assert all(set(job["payload"]) <= {"doc_kind", "doc_id"} for job in jobs)


async def test_reindex_response_model_matches_the_route() -> None:
    schema = create_app(make_settings()).openapi()
    ref = schema["paths"]["/api/v1/admin/search/reindex"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert ref.endswith("SearchReindexResponse")
    assert set(schema["components"]["schemas"]["SearchReindexResponse"]["properties"]) == {
        "page",
        "page_size",
        "documents",
        "enqueued",
        "has_more",
    }


# --- live parity: explicit about what was not run (OD-P3-3) -----------------------


async def _await_elastic_document(
    live: ElasticSearchBackend, doc_id: str, attempts: int = 20
) -> list[SearchHit]:
    """Poll for a document this test just wrote.

    The adapter indexes without an explicit refresh, and Elastic is near-real-time: a
    document becomes searchable on the index's own refresh interval, not on write. The
    contract promises at-least-once indexing, never same-millisecond visibility, so the
    live parity check waits instead of asserting an instant nobody committed to.
    """
    hits: list[SearchHit] = []
    for _ in range(attempts):
        hits = await live.search(
            None, q="quixote 9k", kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
        )
        if any(hit.doc_id == doc_id for hit in hits):
            return hits
        await asyncio.sleep(0.5)
    return hits


async def test_backends_agree_on_the_same_public_documents(db_session: AsyncSession) -> None:
    """Live Elastic parity; recorded as not executed when no cluster is configured.

    The gate is `ELASTICSEARCH_URL` plus the client library being importable: with a
    URL and a client present this test really calls that cluster (a missing key or an
    unreachable host is a failure, not a skip), and a skip is reported as a skip with
    its reason, never counted as a pass (OD-P3-3, D-P3-02).
    """
    url = os.environ.get("ELASTICSEARCH_URL", "")
    key = os.environ.get("ELASTICSEARCH_API_KEY", "")
    if not url:
        pytest.skip(
            "NOT RUN (OD-P3-3): ELASTICSEARCH_URL is empty in this environment, so the "
            "Elastic half of this parity check did not execute. The Postgres backend "
            "assertions above are the only live search evidence here."
        )
    try:
        importlib.import_module("elasticsearch")
    except ImportError:
        pytest.skip(
            "NOT RUN (D-P3-02): ELASTICSEARCH_URL is set but the official async client "
            "is not installed here, so no live Elastic call was made. Installing the "
            "pinned client is the fix; pretending otherwise would be a fake pass."
        )
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    await add_lot(db_session, pool_id)
    live = ElasticSearchBackend(
        url=url,
        api_key=key,
        inference_id=os.environ.get("ELASTIC_INFERENCE_ID", ""),
        index_prefix=os.environ.get("ELASTIC_INDEX_PREFIX", "fairpool"),
        timeout_ms=1500,
    )
    try:
        await live.upsert(
            PublicDocument(
                doc_kind=POOL_DOC,
                pool_id=pool_id,
                lot_id=None,
                status="OPEN",
                product_key="zephyr-quixote-9k",
                condition="NEW",
                title="Fictional zephyr pool",
                content="Fictional zephyr pool monitor-27-4k black NEW monitor NY",
            )
        )
        elastic_hits = await _await_elastic_document(live, str(pool_id))
    finally:
        # S8 deleted its temporary documents the same way: a live run leaves nothing behind.
        await live.delete(doc_kind=POOL_DOC, doc_id=pool_id)
        await live.close()
    postgres_hits = await PostgresSearchBackend().search(
        db_session, q="quixote 9k", kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
    )
    assert {hit.doc_kind for hit in elastic_hits} <= {POOL_DOC, LOT_DOC}
    assert {hit.doc_id for hit in postgres_hits} >= {str(pool_id)}
    # Parity, stated exactly: the document this test wrote is found by both backends
    # and describes the same row in both, with only the retrieval score allowed to differ.
    shared = [hit.doc_id for hit in elastic_hits if hit.doc_id == str(pool_id)]
    assert len(shared) == 1
    elastic_hit = next(hit for hit in elastic_hits if hit.doc_id == str(pool_id))
    postgres_hit = next(hit for hit in postgres_hits if hit.doc_id == str(pool_id))
    assert _shape(elastic_hit) == _shape(postgres_hit)


def _shape(hit: SearchHit) -> dict[str, object]:
    """Everything a hit says about its row except the retrieval score (the float)."""
    return {key: value for key, value in vars(hit).items() if key != "score"}


# --- the public pools list goes through the service ------------------------------


async def test_pools_list_q_uses_the_search_service(db_session: AsyncSession) -> None:
    """T03B02 acceptance: `GET /api/v1/pools?q=` retrieves through SearchService.

    Before T03B02 this route ran a keyword LIKE and the service existed but was
    unreachable from the public surface. A DRAFT pool must stay invisible here just
    as it is invisible to the indexer, and a pool that does not match is absent
    rather than ranked low (FR-IG-01, INT-1).
    """
    target = await add_pool(
        db_session,
        title="Ceramic kettle fictional pool",
        search_text="Ceramic kettle copper pour-over",
    )
    other = await add_pool(
        db_session,
        title="Linen basket fictional pool",
        search_text="Linen basket folded storage",
    )
    draft = await add_pool(
        db_session,
        title="Ceramic kettle fictional draft",
        status="DRAFT",
        search_text="Ceramic kettle copper draft",
    )

    app = create_app(make_settings())

    async def db() -> Any:
        yield db_session

    app.dependency_overrides[database_session] = db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as client:
        found = (await client.get("/api/v1/pools", params={"q": "kettle copper"})).json()
        empty = (await client.get("/api/v1/pools", params={"q": "tungsten carbide"})).json()

    ids = {row["pool_id"] for row in found}
    assert str(target) in ids
    assert str(other) not in ids
    assert str(draft) not in ids
    assert empty == []
    # Every row the ranked path returns is a public pool summary, which is the shape
    # api.md fixes for this route; the unfiltered listing is not asserted here because
    # the shared test database holds rows other suites committed (D-P3-01).
    assert all({"pool_id", "title", "status", "seats"} <= set(row) for row in found)
