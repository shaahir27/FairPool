"""Elastic hybrid search backend (T03B02, INT-1) - the request shape recorded for spike S8.

Official documentation consulted before writing this call (Nov 1, 2026):

* https://www.elastic.co/docs/reference/elasticsearch/clients/python/async -
  ``AsyncElasticsearch("<url>", api_key=..., request_timeout=<seconds>)``,
  ``await client.search(index=..., body={...})`` and ``await client.close()``;
  the async client is installed as ``pip install elasticsearch[async]`` (9.x, the
  current stable major, matching the 9.5.5 cluster S8 measured).
* https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion -
  the ``retriever.rrf.retrievers[].standard.query`` body with ``rank_window_size``
  and ``rank_constant``, confirming the shape S8 accepted.
* https://www.elastic.co/docs/solutions/search/hybrid-semantic-text and the
  semantic-text mapping reference
  (elastic.co/docs/reference/elasticsearch/mapping-reference/semantic-text-search-retrieval) -
  ``semantic_text`` retrieval. These pages now present ``match``/``knn`` as the
  current forms and the plain ``semantic`` query as legacy; S8 recorded the
  ``semantic`` leg working on the live cluster, so this module keeps the recorded
  shape rather than inventing a newer one.

Every call is bounded by ``SEARCH_TIMEOUT_MS``; timeout, a missing index, a
permission or inference failure (the recorded 429) and a malformed or empty
response all raise :class:`SearchBackendError`, which the service turns into the
Postgres fallback. No URL, key or provider message ever reaches a log.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final
from uuid import UUID

from fairpool.adapters.search.base import SearchBackendError
from fairpool.adapters.search.projection import PublicDocument
from fairpool.ports import AsyncSession, SearchHit

INDEX_SUFFIX: Final[str] = "-search-v1"
EMBEDDING_FIELD: Final[str] = "content_embedding"
# The RRF tuning S8 ran with.
RANK_WINDOW_SIZE: Final[int] = 20
RANK_CONSTANT: Final[int] = 60
# Retrieval needs no more than the allowlisted public fields.
SOURCE_FIELDS: Final[tuple[str, ...]] = (
    "doc_kind",
    "pool_id",
    "lot_id",
    "status",
    "product_key",
    "condition",
    "title",
)


# The mapping S8 created: content copies into a semantic_text field that names
# an explicit inference endpoint (ai-schemas.md section 7).
def index_mappings(inference_id: str) -> dict[str, Any]:
    return {
        "properties": {
            "doc_kind": {"type": "keyword"},
            "pool_id": {"type": "keyword"},
            "lot_id": {"type": "keyword"},
            "status": {"type": "keyword"},
            "product_key": {"type": "keyword"},
            "condition": {"type": "keyword"},
            "title": {"type": "text"},
            "content": {"type": "text", "copy_to": EMBEDDING_FIELD},
            EMBEDDING_FIELD: {"type": "semantic_text", "inference_id": inference_id},
        }
    }


def _filters(kinds: list[str], status: list[str] | None) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = [{"terms": {"doc_kind": sorted(kinds)}}]
    if status is not None:
        filters.append({"terms": {"status": sorted(status)}})
    return filters


def hybrid_request(
    q: str, *, kinds: list[str], status: list[str] | None, limit: int
) -> dict[str, Any]:
    """The recorded S8 hybrid body: RRF over a BM25 ``match`` and a ``semantic`` leg."""
    filters = _filters(kinds, status)
    return {
        "retriever": {
            "rrf": {
                "retrievers": [
                    {
                        "standard": {
                            "query": {
                                "bool": {"must": [{"match": {"content": q}}], "filter": filters}
                            }
                        }
                    },
                    {
                        "standard": {
                            "query": {
                                "bool": {
                                    "must": [
                                        {"semantic": {"field": EMBEDDING_FIELD, "query": q}},
                                    ],
                                    "filter": filters,
                                }
                            }
                        }
                    },
                ],
                "rank_window_size": RANK_WINDOW_SIZE,
                "rank_constant": RANK_CONSTANT,
            }
        },
        "size": limit,
        "_source": list(SOURCE_FIELDS),
    }


def semantic_request(
    q: str, *, kinds: list[str], status: list[str] | None, limit: int
) -> dict[str, Any]:
    """The recorded S8 semantic-only body, used by the advisory wrong-product check."""
    return {
        "query": {
            "bool": {
                "must": [{"semantic": {"field": EMBEDDING_FIELD, "query": q}}],
                "filter": _filters(kinds, status),
            }
        },
        "size": limit,
        "_source": list(SOURCE_FIELDS),
    }


def index_name(prefix: str) -> str:
    return f"{prefix}{INDEX_SUFFIX}"


def hits_of(response: Any) -> list[SearchHit]:
    """Map an Elastic response to the shared ``SearchHit`` shape; a partial hit is a fault."""
    try:
        raw = response["hits"]["hits"]
    except (TypeError, KeyError, IndexError) as exc:
        raise SearchBackendError("malformed response") from exc
    hits: list[SearchHit] = []
    for entry in raw:
        try:
            source = entry["_source"]
            hits.append(
                SearchHit(
                    doc_id=str(entry["_id"]),
                    doc_kind=str(source["doc_kind"]),
                    pool_id=UUID(str(source["pool_id"])),
                    lot_id=UUID(str(source["lot_id"])) if source.get("lot_id") else None,
                    product_key=str(source["product_key"]),
                    title=str(source["title"]),
                    score=float(entry.get("_score") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError):
            # An empty or partially populated index is a fallback, not an answer.
            raise SearchBackendError("partially populated index") from None
    return hits


class ElasticSearchBackend:
    """The Elastic half of ``SearchService`` and ``SearchIndexer`` behind one client."""

    def __init__(
        self,
        *,
        url: str = "",
        api_key: str = "",
        inference_id: str = "",
        index_prefix: str = "fairpool",
        timeout_ms: int = 1500,
        client: Any | None = None,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._inference_id = inference_id
        self._timeout_s = timeout_ms / 1000
        self.index = index_name(index_prefix)
        self._client = client
        self._index_ready = False

    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
        semantic_only: bool = False,
    ) -> list[SearchHit]:
        # The index answers over HTTP; hydration against Postgres is the service's job.
        del session
        if not q.strip() or limit <= 0:
            return []
        body = (
            semantic_request(q, kinds=kinds, status=status, limit=limit)
            if semantic_only
            else hybrid_request(q, kinds=kinds, status=status, limit=limit)
        )
        response = await self._call(
            "search", self._client_factory().search, index=self.index, body=body
        )
        return hits_of(response)

    async def upsert(self, document: PublicDocument) -> None:
        client = self._client_factory()
        await self._ensure_index(client)
        # doc_id is the row id the document describes, so the same write repeats safely.
        await self._call(
            "index",
            client.index,
            index=self.index,
            id=str(document.doc_id),
            document=document.fields(),
        )

    async def delete(self, *, doc_kind: str, doc_id: UUID) -> None:
        del doc_kind
        client = self._client_factory()
        if not await self._call("exists", self._indices_exists, client):
            return
        try:
            await self._call("delete", client.delete, index=self.index, id=str(doc_id))
        except SearchBackendError as exc:
            if exc.status == 404:
                return  # already absent: a delete repeats safely (CR-3)
            raise

    async def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
            self._client = None

    async def _indices_exists(self, client: Any) -> bool:
        return bool(await client.indices.exists(index=self.index))

    async def _create_index(self, client: Any) -> Any:
        return await client.indices.create(
            index=self.index, mappings=index_mappings(self._inference_id)
        )

    async def _ensure_index(self, client: Any) -> None:
        if self._index_ready:
            return
        if not await self._call("exists", self._indices_exists, client):
            if not self._inference_id:
                raise SearchBackendError("no inference endpoint configured")
            try:
                await self._call("create", self._create_index, client)
            except SearchBackendError as exc:
                if exc.status != 400:
                    raise
                # A racing create from another worker is the outcome we wanted.
        self._index_ready = True

    def _client_factory(self) -> Any:
        """The injected client, or the official async client built once and reused."""
        if self._client is None:
            if not self._url or not self._api_key:
                raise SearchBackendError("elastic not configured")
            try:
                from elasticsearch import AsyncElasticsearch
            except ImportError as exc:
                raise SearchBackendError("elasticsearch client not installed") from exc
            self._client = AsyncElasticsearch(
                hosts=[self._url], api_key=self._api_key, request_timeout=self._timeout_s
            )
        return self._client

    async def _call(self, op: str, function: Any, *args: Any, **kwargs: Any) -> Any:
        """One bounded client call; the official client takes these arguments by keyword."""
        try:
            return await asyncio.wait_for(function(*args, **kwargs), timeout=self._timeout_s)
        except TimeoutError as exc:
            raise SearchBackendError(f"{op} timed out") from exc
        except Exception as exc:
            raise _classify(op, exc) from exc


def _classify(op: str, exc: Exception) -> SearchBackendError:
    """Map a client failure to a fixed reason: never the provider text, URL or key."""
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        status = getattr(exc, "status", None)
    if isinstance(status, int):
        reason = {
            429: "inference capacity (429)",
            404: "index not found",
            403: "permission denied",
            401: "permission denied",
        }.get(status, f"{op} failed ({status})")
        return SearchBackendError(reason, status=status)
    return SearchBackendError(f"{op} unavailable")
