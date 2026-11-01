"""T03B02 privacy boundary: the search projection cannot carry buyer or merchant secrets.

Rule 23, INT-1 and FR-IG-01 say search is retrieval over public documents only: never
buyer entries, requests, caps, users, links, tokens or private quote text. This file
puts a marker value in every one of those private columns, then proves the marker
cannot come out of the projection, either backend, the index write or the SQL the
projection compiles - and that a hit whose row has since turned private or stale is
dropped after hydration against current Postgres visibility.

The Elastic client here is the clearly named recording mock from
``tests/unit/test_search_projection.py``: it proves what our code sends, not what
Elastic stores (rule 18). No test in this file opens a network connection.
"""

from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import fields
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.search.elastic import (
    EMBEDDING_FIELD,
    ElasticSearchBackend,
    hits_of,
    index_mappings,
    semantic_request,
)
from fairpool.adapters.search.postgres import PostgresSearchBackend
from fairpool.adapters.search.projection import (
    LOT_DOC,
    POOL_DOC,
    PUBLIC_FIELDS,
    lot_content,
    pool_content,
    public_documents_select,
    read_public_document,
)
from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import LotStatus, PoolStatus
from fairpool.domain import hashing
from fairpool.modules.search.indexer import SearchDocumentIndexer
from fairpool.modules.search.service import SearchRoutingService
from fairpool.ports import SearchHit, SearchIndexer, SearchService
from tests.integration.test_search_fallback import add_lot, add_pool, response_of
from tests.unit.test_search_projection import INFERENCE_ID, RecordingClient, document

pytestmark = pytest.mark.integration

# One marker per private column. None of them may ever appear in a search artefact.
MARKERS = {
    "user_email": "private-buyer-marker@example.test",
    "request_body": "canonical-request-marker-7c41",
    "request_hash": hashing.sha256_hex("canonical-request-marker-7c41"),
    "account_key": "paypal-account-key-marker-2f9d",
    "vault_token_label": "payment-token-id-marker-5b70",
    "quote_text": "merchant-quote-text-marker-9ad4",
    "notes": "buyer-notes-marker-3e18",
    "receipt_signature": "receipt-signature-marker-6c22",
}
CAP_MARKER = 61337

PRIVATE_TABLES = (
    "pool_entries",
    "entry_receipts",
    "bid_revisions",
    "bids",
    "merchants",
    "vault_tokens",
    "paypal_links",
    "users",
    "buyer_orders",
    "sessions",
)


def new_id() -> uuid.UUID:
    return uuid.UUID(str(uuid.uuid4()))


async def seed_private_data(session: AsyncSession, pool_id: uuid.UUID, lot_id: uuid.UUID) -> None:
    """One row in every private table a search artefact must never reach."""
    buyer = new_id()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', 'buyer', 'Private Buyer')"
        ),
        {"id": buyer, "email": MARKERS["user_email"]},
    )
    entry = new_id()
    await session.execute(
        text(
            "INSERT INTO pool_entries (id, pool_id, user_id, paypal_account_key, "
            "canonical_request, request_hash, cap_cents, zone_id, status, submitted_via) "
            "VALUES (:id, :pool, :user, :account, CAST(:request AS jsonb), :hash, :cap, "
            "'US-EAST', 'SUBMITTED', 'human')"
        ),
        {
            "id": entry,
            "pool": pool_id,
            "user": buyer,
            "account": MARKERS["account_key"],
            "cap": CAP_MARKER,
            "hash": MARKERS["request_hash"],
            "request": json.dumps(
                {
                    "pool_id": str(pool_id),
                    "currency": "USD",
                    "max_total_cents": CAP_MARKER,
                    "line": MARKERS["request_body"],
                    "firm": [],
                    "preferences": [],
                }
            ),
        },
    )
    await session.execute(
        text(
            "INSERT INTO vault_tokens (id, entry_id, user_id, status, token_label, cap_cents, "
            "consent_version, consent_text_sha256, consented_at) "
            "VALUES (:id, :entry, :user, 'ACTIVE', :label, :cap, 'consent_v1', :sha, now())"
        ),
        {
            "id": new_id(),
            "entry": entry,
            "user": buyer,
            "label": MARKERS["vault_token_label"],
            "cap": CAP_MARKER,
            "sha": MARKERS["request_hash"],
        },
    )
    await session.execute(
        text("INSERT INTO paypal_links (id, user_id, paypal_account_key) VALUES (:id, :u, :k)"),
        {"id": new_id(), "u": buyer, "k": MARKERS["account_key"]},
    )
    merchant_user = new_id()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, role, display_name) "
            "VALUES (:id, :email, 'hash', 'merchant', 'Private Merchant')"
        ),
        {"id": merchant_user, "email": f"merchant-{merchant_user}@example.test"},
    )
    merchant = new_id()
    await session.execute(
        text("INSERT INTO merchants (id, user_id, display_name) VALUES (:id, :user, 'Vendor')"),
        {"id": merchant, "user": merchant_user},
    )
    bid = new_id()
    await session.execute(
        text(
            "INSERT INTO bids (id, lot_id, merchant_id, status) VALUES (:id, :lot, :m, 'CONFIRMED')"
        ),
        {"id": bid, "lot": lot_id, "m": merchant},
    )
    await session.execute(
        text(
            "INSERT INTO bid_revisions (id, bid_id, revision, structured, quote_text, notes, "
            "receipt_hash, receipt_signature) VALUES (:id, :bid, 1, '{}'::jsonb, :quote, :notes, "
            ":hash, :signature)"
        ),
        {
            "id": new_id(),
            "bid": bid,
            "quote": MARKERS["quote_text"],
            "notes": MARKERS["notes"],
            "hash": MARKERS["request_hash"],
            "signature": MARKERS["receipt_signature"],
        },
    )


def backend_with(client: Any) -> ElasticSearchBackend:
    return ElasticSearchBackend(
        url="https://elastic.example.test",
        api_key="dummy-key-never-logged",
        inference_id=".jina-embeddings-v5-text-small",
        index_prefix="fairpool",
        timeout_ms=1000,
        client=client,
    )


def elastic_service(client: Any) -> SearchRoutingService:
    """The service under test: Postgres is the real source of truth, Elastic is a mock."""
    return SearchRoutingService(
        postgres=PostgresSearchBackend(),
        elastic=backend_with(client),
        backend="elastic",
    )


def assert_no_marker(value: object, *, where: str) -> None:
    """Every marker, and the cap number itself, must be absent wherever search travels."""
    blob = value if isinstance(value, str) else json.dumps(_plain(value), default=str)
    lowered = blob.casefold()
    for name, marker in MARKERS.items():
        assert marker not in lowered, f"{name} leaked into {where}"
    assert str(CAP_MARKER) not in lowered, f"cap_cents leaked into {where}"


def _plain(value: object) -> object:
    if isinstance(value, (uuid.UUID, bytes)):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {key: _plain(item) for key, item in vars(value).items()}
    return value


# --- the projection itself ---------------------------------------------------------


async def test_a_real_private_row_cannot_reach_a_public_document(
    db_session: AsyncSession,
) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    before = {
        (kind, doc_id): await read_public_document(db_session, doc_kind=kind, doc_id=doc_id)
        for kind, doc_id in ((POOL_DOC, pool_id), (LOT_DOC, lot_id))
    }
    await seed_private_data(db_session, pool_id, lot_id)

    for (doc_kind, doc_id), previous in before.items():
        doc = await read_public_document(db_session, doc_kind=doc_kind, doc_id=doc_id)
        assert doc is not None
        assert previous is not None
        assert tuple(doc.fields()) == PUBLIC_FIELDS  # the allowlist, exactly and only
        assert_no_marker(doc.fields(), where=f"{doc_kind} document")
        # Buyer data added after indexing never enters the projection either: the same
        # row reads identically because the projection has no join path to any of it.
        assert doc.fields() == previous.fields()


async def test_the_projection_sql_touches_no_private_table() -> None:
    dialect = postgresql.dialect()
    statements = [
        str(select(Pool.id, pool_content()).compile(dialect=dialect)),
        str(select(lot_content()).compile(dialect=dialect)),
        str(public_documents_select().compile(dialect=dialect)),
    ]
    for statement in statements:
        sql = statement.casefold()
        for table in PRIVATE_TABLES:
            assert f" from {table}" not in sql, f"the projection reads {table}"
            assert f" join {table}" not in sql, f"the projection joins {table}"
        assert "pools" in sql


def test_the_search_port_takes_no_buyer_or_merchant_arguments() -> None:
    """No caller can pass a cap, a user, a request or a token through this port."""
    allowed = {"session", "q", "kinds", "status", "limit", "lot_id", "text", "doc_kind", "doc_id"}
    for port in (SearchService, SearchIndexer):
        for name, function in inspect.getmembers(port, inspect.isfunction):
            if name.startswith("_"):
                continue
            parameters = set(inspect.signature(function).parameters) - {"self"}
            assert parameters <= allowed, f"{port.__name__}.{name} takes {parameters}"
    # And the shape that comes back is the public one, with no private field to fill.
    assert tuple(field.name for field in fields(SearchHit)) == (
        "doc_id",
        "doc_kind",
        "pool_id",
        "lot_id",
        "product_key",
        "title",
        "score",
    )


def test_the_index_mapping_and_the_query_body_name_only_public_fields() -> None:
    properties = set(index_mappings(INFERENCE_ID)["properties"])
    assert properties - set(PUBLIC_FIELDS) == {EMBEDDING_FIELD}  # the text's own vector field
    body = semantic_request("zephyr", kinds=[LOT_DOC], status=["BIDDING"], limit=5)
    assert set(body["_source"]) <= set(PUBLIC_FIELDS)
    assert_no_marker(body, where="the recorded S8 request body")


# --- the backends, the index write and the job payload -----------------------------


async def test_backend_hits_and_the_index_write_carry_no_private_value(
    db_session: AsyncSession,
) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    await seed_private_data(db_session, pool_id, lot_id)

    hits = await PostgresSearchBackend().search(
        db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
    )
    assert hits
    for hit in hits:
        assert_no_marker(vars(hit), where="a Postgres hit")

    client = RecordingClient()
    indexer = SearchDocumentIndexer(elastic=backend_with(client))
    await indexer.upsert(db_session, doc_kind=LOT_DOC, doc_id=lot_id)
    writes = [kwargs for name, kwargs in client.calls if name == "index"]
    assert len(writes) == 1
    assert set(writes[0]["document"]) == set(PUBLIC_FIELDS)
    assert_no_marker(writes[0], where="the Elastic index write")


async def test_private_values_are_not_in_the_text_any_backend_can_match(
    db_session: AsyncSession,
) -> None:
    """What is indexed is the public text only, so a private value cannot be retrieved.

    A trigram query built from private text can still answer with public documents -
    trigrams are fuzzy and that is retrieval noise, not a leak. The privacy claim that
    matters is the one asserted here: the private value is absent from the indexed text
    and absent from every hit, while a public needle does find the document.
    """
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    await seed_private_data(db_session, pool_id, lot_id)
    documents = [
        await read_public_document(db_session, doc_kind=POOL_DOC, doc_id=pool_id),
        await read_public_document(db_session, doc_kind=LOT_DOC, doc_id=lot_id),
    ]
    assert all(doc is not None for doc in documents)
    for needle in (
        MARKERS["quote_text"],
        MARKERS["notes"],
        MARKERS["user_email"],
        MARKERS["account_key"],
        MARKERS["vault_token_label"],
        MARKERS["request_hash"],
        MARKERS["receipt_signature"],
        str(CAP_MARKER),
    ):
        for doc in documents:
            assert doc is not None
            assert needle not in doc.content, needle  # never indexed, so never matched
            assert needle not in doc.title and needle not in doc.product_key

        hits = await PostgresSearchBackend().search(
            db_session, q=needle, kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
        )
        for hit in hits:
            assert_no_marker(vars(hit), where=f"a hit for {needle!r}")

    # The public side does work, so the assertions above are not passing by accident.
    found = await PostgresSearchBackend().search(
        db_session, q="quixote 9k", kinds=[POOL_DOC, LOT_DOC], status=None, limit=10
    )
    assert {str(pool_id), str(lot_id)} <= {hit.doc_id for hit in found}


# --- hydration against current Postgres visibility ---------------------------------


async def test_a_hit_whose_row_turned_private_is_dropped(db_session: AsyncSession) -> None:
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    await seed_private_data(db_session, pool_id, lot_id)
    client = RecordingClient(
        response=response_of(
            document(pool_id=pool_id, doc_kind=POOL_DOC, lot_id=None),
            document(pool_id=pool_id, lot_id=lot_id, doc_kind=LOT_DOC, status="BIDDING"),
        )
    )
    svc = elastic_service(client)
    both = await svc.search(
        db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=None, limit=5
    )
    assert {hit.doc_id for hit in both} == {str(pool_id), str(lot_id)}

    # The pool turns private: everything it carries is dropped, not merely filtered.
    await db_session.execute(
        text("UPDATE pools SET status = :s WHERE id = :id"),
        {"s": PoolStatus.CANCELLED.value, "id": pool_id},
    )
    svc_postgres_first = SearchRoutingService(postgres=PostgresSearchBackend(), backend="postgres")
    assert (
        await svc.search(db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=None, limit=5)
        == []
    )
    # The trigram path reads the same committed rows, so it drops them too.
    assert (
        await svc_postgres_first.search(
            db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=None, limit=5
        )
        == []
    )

    # Deleting the rows outright is the same answer: nothing is served from the index.
    gone = await add_pool(db_session, title="Fictional zephyr pool deleted later")
    client.response = response_of(document(pool_id=gone, doc_kind=POOL_DOC, lot_id=None))
    assert [
        hit.doc_id
        for hit in await svc.search(db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5)
    ] == [str(gone)]
    await db_session.execute(text("DELETE FROM pools WHERE id = :id"), {"id": gone})
    assert (
        await svc.search(db_session, q="quixote", kinds=[POOL_DOC, LOT_DOC], status=None, limit=5)
        == []
    )


async def test_a_stale_hit_is_dropped_when_its_status_moved_past_the_filter(
    db_session: AsyncSession,
) -> None:
    """The index still says BIDDING; Postgres says AWARDED, so the hit is not shown."""
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    lot_id = await add_lot(db_session, pool_id)
    client = RecordingClient(
        response=response_of(
            document(pool_id=pool_id, lot_id=lot_id, doc_kind=LOT_DOC, status="BIDDING")
        )
    )
    svc = elastic_service(client)
    hits = await svc.search(db_session, q="quixote", kinds=[LOT_DOC], status=["BIDDING"], limit=5)
    assert len(hits) == 1

    await db_session.execute(
        text("UPDATE lots SET status = :s WHERE id = :id"),
        {"s": LotStatus.AWARDED.value, "id": lot_id},
    )
    assert (
        await svc.search(db_session, q="quixote", kinds=[LOT_DOC], status=["BIDDING"], limit=5)
        == []
    )
    # The document itself is still public; it simply no longer matches this caller.
    doc = await read_public_document(db_session, doc_kind=LOT_DOC, doc_id=lot_id)
    assert doc is not None and doc.status == LotStatus.AWARDED.value


async def test_a_hit_for_a_draft_pool_never_survives_hydration(
    db_session: AsyncSession,
) -> None:
    """A DRAFT pool is not public: an index that wrongly holds it is overridden."""
    draft = await add_pool(db_session, title="Fictional draft pool", status="DRAFT")
    client = RecordingClient(
        response=response_of(document(pool_id=draft, doc_kind=POOL_DOC, lot_id=None))
    )
    svc = elastic_service(client)
    assert await svc.search(db_session, q="quixote", kinds=[POOL_DOC], status=None, limit=5) == []


async def test_the_indexer_deletes_a_document_that_turned_private(
    db_session: AsyncSession,
) -> None:
    """Turning private is an index change too: nothing stale is left to be served."""
    pool_id = await add_pool(db_session, title="Fictional zephyr pool")
    client = RecordingClient()
    indexer = SearchDocumentIndexer(elastic=backend_with(client))
    await indexer.upsert(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    await db_session.execute(
        text("UPDATE pools SET status = :s WHERE id = :id"),
        {"s": PoolStatus.CANCELLED.value, "id": pool_id},
    )
    await indexer.upsert(db_session, doc_kind=POOL_DOC, doc_id=pool_id)
    assert [name for name, _ in client.calls] == [
        "indices.exists",
        "index",
        "indices.exists",
        "delete",
    ]
    assert_no_marker(client.calls, where="the index calls")


async def test_a_mapped_hit_cannot_carry_a_field_the_index_should_not_have() -> None:
    """Even a corrupt index entry is mapped down to the public shape (rule 23)."""
    response = {
        "hits": {
            "hits": [
                {
                    "_id": str(new_id()),
                    "_score": 1.0,
                    "_source": {
                        "doc_kind": POOL_DOC,
                        "pool_id": str(new_id()),
                        "lot_id": None,
                        "status": "OPEN",
                        "product_key": "zephyr",
                        "condition": "NEW",
                        "title": "Fictional pool",
                        "cap_cents": CAP_MARKER,
                        "quote_text": MARKERS["quote_text"],
                        "canonical_request": MARKERS["request_body"],
                    },
                }
            ]
        }
    }
    (hit,) = hits_of(response)
    assert set(vars(hit)) == {
        "doc_id",
        "doc_kind",
        "pool_id",
        "lot_id",
        "product_key",
        "title",
        "score",
    }
    assert_no_marker(vars(hit), where="a mapped Elastic hit")
