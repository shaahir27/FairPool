"""T03B02: the one allowlisted projection and the request shape recorded for spike S8.

Unit scope: no network and no database. The Elastic half is checked against the
request and mapping the spike recorded (``docs/spike-results.md`` S8, produced by
``tools/fairpool_spike_check.py``), with a clearly named recording client - it is
not evidence of live Elastic behaviour (rule 18, OD-P3-3).
"""

from __future__ import annotations

import asyncio
from dataclasses import fields
from typing import Any
from uuid import uuid4

import pytest

from fairpool.adapters.search.base import SearchBackendError
from fairpool.adapters.search.elastic import (
    EMBEDDING_FIELD,
    ElasticSearchBackend,
    hits_of,
    hybrid_request,
    index_mappings,
    index_name,
    semantic_request,
)
from fairpool.adapters.search.projection import (
    LOT_DOC,
    POOL_DOC,
    PUBLIC_FIELDS,
    PublicDocument,
)
from fairpool.ports import SearchHit

INFERENCE_ID = ".jina-embeddings-v5-text-small"


def document(doc_kind: str = POOL_DOC, **overrides: Any) -> PublicDocument:
    base: dict[str, Any] = {
        "doc_kind": doc_kind,
        "pool_id": uuid4(),
        "lot_id": None,
        "status": "OPEN",
        "product_key": "monitor-27-4k",
        "condition": "NEW",
        "title": "Fictional monitor pool",
        "content": "Fictional monitor pool monitor-27-4k black NEW monitor NY delivery 7 days",
    }
    base.update(overrides)
    return PublicDocument(**base)


class RecordingClient:
    """Named mock: records the calls the backend makes; proves nothing about Elastic."""

    def __init__(self, *, response: Any | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.response = {
            "hits": {
                "hits": [
                    {
                        "_id": str(uuid4()),
                        "_score": 0.8,
                        "_source": {
                            "doc_kind": "pool",
                            "pool_id": str(uuid4()),
                            "lot_id": None,
                            "status": "OPEN",
                            "product_key": "monitor-27-4k",
                            "condition": "NEW",
                            "title": "Fictional monitor pool",
                        },
                    }
                ]
            }
        }
        if response is not None:
            self.response = response
        self.error = error
        self.indices = _Indices(self)

    async def search(self, **kwargs: Any) -> Any:
        self.calls.append(("search", kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    async def index(self, **kwargs: Any) -> Any:
        self.calls.append(("index", kwargs))
        return {"result": "created"}

    async def delete(self, **kwargs: Any) -> Any:
        self.calls.append(("delete", kwargs))
        return {"result": "deleted"}

    async def close(self) -> None:
        self.calls.append(("close", {}))


class _Indices:
    def __init__(self, owner: RecordingClient) -> None:
        self._owner = owner
        self.index_exists = True

    async def exists(self, **kwargs: Any) -> bool:
        self._owner.calls.append(("indices.exists", kwargs))
        return self.index_exists

    async def create(self, **kwargs: Any) -> Any:
        self._owner.calls.append(("indices.create", kwargs))
        return {"acknowledged": True}


class StatusError(Exception):
    """Shaped like the client's ApiError: the backend reads the status, never the text."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("provider text that must never leak")


# --- the projection (acceptance: only public documents are indexed) ----------------


def test_projection_fields_are_exactly_the_allowlist() -> None:
    assert tuple(f.name for f in fields(PublicDocument)) == PUBLIC_FIELDS
    assert PUBLIC_FIELDS == (
        "doc_kind",
        "pool_id",
        "lot_id",
        "status",
        "product_key",
        "condition",
        "title",
        "content",
    )
    assert tuple(document().fields()) == PUBLIC_FIELDS


def test_no_private_field_can_be_produced_by_the_projection() -> None:
    forbidden = {
        "cap_cents",
        "max_total_cents",
        "user_id",
        "entry_id",
        "canonical_request",
        "request_hash",
        "paypal_account_key",
        "paypal_link",
        "token",
        "payment_token_id",
        "quote_text",
        "notes",
        "email",
        "address",
    }
    assert forbidden.isdisjoint(PUBLIC_FIELDS)
    assert forbidden.isdisjoint(set(document().fields()))
    assert forbidden.isdisjoint(set(index_mappings(INFERENCE_ID)["properties"]))
    assert forbidden.isdisjoint(hybrid_request("q", kinds=["pool"], status=None, limit=5))


def test_document_is_keyed_by_the_row_id_it_describes() -> None:
    pool = document()
    assert pool.doc_id == pool.pool_id
    lot = document(LOT_DOC, lot_id=uuid4(), status="BIDDING")
    assert lot.doc_id == lot.lot_id
    assert lot.pool_id != lot.doc_id


def test_index_name_comes_from_the_configured_prefix() -> None:
    assert index_name("fairpool") == "fairpool-search-v1"
    assert index_name("other") == "other-search-v1"


def test_mapping_copies_content_into_a_semantic_text_field_naming_the_endpoint() -> None:
    properties = index_mappings(INFERENCE_ID)["properties"]
    assert properties["content"] == {"type": "text", "copy_to": EMBEDDING_FIELD}
    assert properties[EMBEDDING_FIELD] == {
        "type": "semantic_text",
        "inference_id": INFERENCE_ID,
    }
    assert properties["status"] == {"type": "keyword"}
    assert properties["title"] == {"type": "text"}


# --- the recorded S8 request shape -------------------------------------------------


def test_hybrid_request_is_the_recorded_s8_rrf_shape() -> None:
    body = hybrid_request("big 4k screen", kinds=["lot", "pool"], status=["OPEN"], limit=5)
    assert body == {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "must": [{"match": {"content": "big 4k screen"}}],
                                    "filter": [
                                        {"terms": {"doc_kind": ["lot", "pool"]}},
                                        {"terms": {"status": ["OPEN"]}},
                                    ],
                                }
                            }
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "must": [
                                        {
                                            "semantic": {
                                                "field": "content_embedding",
                                                "query": "big 4k screen",
                                            }
                                        }
                                    ],
                                    "filter": [
                                        {"terms": {"doc_kind": ["lot", "pool"]}},
                                        {"terms": {"status": ["OPEN"]}},
                                    ],
                                }
                            }
                        }
                    },
                ],
                "rank_window_size": 20,
                "rank_constant": 60,
            }
        },
        "size": 5,
        "_source": [
            "doc_kind",
            "pool_id",
            "lot_id",
            "status",
            "product_key",
            "condition",
            "title",
        ],
    }


def test_semantic_only_request_is_the_recorded_s8_advisory_leg() -> None:
    body = semantic_request("wireless mouse", kinds=["lot"], status=["BIDDING"], limit=5)
    assert body == {
        "query": {
            "bool": {
                "must": [{"semantic": {"field": EMBEDDING_FIELD, "query": "wireless mouse"}}],
                "filter": [
                    {"terms": {"doc_kind": ["lot"]}},
                    {"terms": {"status": ["BIDDING"]}},
                ],
            }
        },
        "size": 5,
        "_source": [
            "doc_kind",
            "pool_id",
            "lot_id",
            "status",
            "product_key",
            "condition",
            "title",
        ],
    }


def test_status_filter_is_absent_when_the_caller_does_not_filter() -> None:
    body = hybrid_request("q", kinds=["pool"], status=None, limit=3)
    leg = body["retriever"]["rrf"]["retrievers"][0]["standard"]["query"]["bool"]["filter"]
    assert leg == [{"terms": {"doc_kind": ["pool"]}}]
    assert body["size"] == 3


def test_hits_are_mapped_to_the_shared_search_hit_shape() -> None:
    (hit,) = hits_of(RecordingClient().response)
    assert isinstance(hit, SearchHit)
    assert tuple(vars(hit)) == tuple(f.name for f in fields(SearchHit))
    assert hit.doc_kind == "pool"
    assert hit.lot_id is None
    assert hit.score == pytest.approx(0.8)


def test_an_empty_or_partially_populated_index_is_a_backend_error() -> None:
    with pytest.raises(SearchBackendError, match="partially populated index"):
        hits_of({"hits": {"hits": [{"_id": "a", "_score": 1.0, "_source": {"doc_kind": "pool"}}]}})
    with pytest.raises(SearchBackendError, match="malformed response"):
        hits_of({"hits": {}})


# --- the client contract: bounded, and it writes only the projection ---------------


def _backend(client: Any, **overrides: Any) -> ElasticSearchBackend:
    kwargs: dict[str, Any] = {
        "url": "https://elastic.example.test",
        "api_key": "dummy-key-never-logged",
        "inference_id": INFERENCE_ID,
        "index_prefix": "fairpool",
        "timeout_ms": 100,
        "client": client,
    }
    kwargs.update(overrides)
    return ElasticSearchBackend(**kwargs)


async def test_elastic_search_sends_the_recorded_body_and_index_name() -> None:
    client = RecordingClient()
    hits = await _backend(client).search(
        None, q="big 4k screen", kinds=["pool"], status=["OPEN"], limit=5
    )
    assert [name for name, _ in client.calls] == ["search"]
    op, kwargs = client.calls[0]
    assert op == "search"
    assert kwargs["index"] == "fairpool-search-v1"
    assert kwargs["body"] == hybrid_request(
        "big 4k screen", kinds=["pool"], status=["OPEN"], limit=5
    )
    assert len(hits) == 1


async def test_elastic_upsert_writes_the_allowlisted_document_by_row_id() -> None:
    client = RecordingClient()
    doc = document()
    await _backend(client).upsert(doc)
    ops = [name for name, _ in client.calls]
    assert ops == ["indices.exists", "index"]
    write = client.calls[1][1]
    assert write["id"] == str(doc.doc_id)
    assert set(write["document"]) == set(PUBLIC_FIELDS)
    assert "cap_cents" not in write["document"]


async def test_elastic_creates_the_index_from_the_recorded_mapping_once() -> None:
    client = RecordingClient()
    client.indices.index_exists = False
    backend = _backend(client)
    await backend.upsert(document())
    await backend.upsert(document())
    assert [name for name, _ in client.calls] == [
        "indices.exists",
        "indices.create",
        "index",
        "index",
    ]
    create = next(kwargs for name, kwargs in client.calls if name == "indices.create")
    assert create["index"] == "fairpool-search-v1"
    assert create["mappings"] == index_mappings(INFERENCE_ID)


async def test_every_call_is_bounded_by_the_search_timeout() -> None:
    class SlowClient:
        async def search(self, **kwargs: Any) -> Any:
            await asyncio.sleep(5)
            raise AssertionError("unreachable")

    with pytest.raises(SearchBackendError, match="timed out"):
        await _backend(SlowClient(), timeout_ms=100).search(
            None, q="monitor", kinds=["pool"], status=None, limit=5
        )


async def test_a_429_inference_failure_is_reported_without_leaving_the_reason() -> None:
    client = RecordingClient(error=StatusError(429))
    with pytest.raises(SearchBackendError) as excinfo:
        await _backend(client).search(None, q="monitor", kinds=["pool"], status=None, limit=5)
    assert excinfo.value.reason == "inference capacity (429)"
    assert excinfo.value.status == 429
    assert "example.test" not in str(excinfo.value)
    assert "dummy-key" not in str(excinfo.value)
    assert "provider text" not in str(excinfo.value)


async def test_an_unconfigured_backend_is_a_fallback_not_a_crash() -> None:
    backend = ElasticSearchBackend(url="", api_key="", inference_id=INFERENCE_ID)
    with pytest.raises(SearchBackendError, match="not configured"):
        await backend.search(None, q="monitor", kinds=["pool"], status=None, limit=5)


async def test_a_missing_index_is_a_fallback_and_a_delete_repeats_safely() -> None:
    client = RecordingClient()
    client.indices.index_exists = False
    backend = _backend(client)
    await backend.delete(doc_kind=POOL_DOC, doc_id=uuid4())
    assert [name for name, _ in client.calls] == ["indices.exists"]


async def test_delete_of_an_existing_index_is_keyed_by_the_row_id() -> None:
    client = RecordingClient()
    lot_id = uuid4()
    await _backend(client).delete(doc_kind=LOT_DOC, doc_id=lot_id)
    assert [name for name, _ in client.calls] == ["indices.exists", "delete"]
    assert client.calls[1][1] == {"index": "fairpool-search-v1", "id": str(lot_id)}
