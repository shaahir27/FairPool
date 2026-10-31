"""Measure the S8 PostgreSQL baseline using real pg_trgm and fictional public documents."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from fairpool.db.safety import require_test_database
from fairpool.db.session import normalize_database_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = [
    "27 inch 4K monitor desk screen",
    "24 inch HD monitor compact screen",
    "32 inch curved gaming monitor screen",
    "wireless keyboard quiet typing",
    "mechanical keyboard backlit typing",
    "wireless mouse ergonomic office",
    "vertical mouse wrist support",
    "USB microphone podcast audio",
    "condenser microphone studio recording",
    "webcam HD video calls",
    "webcam 4K streaming camera",
    "USB docking station laptop ports",
    "portable solid state drive storage",
    "external hard drive backup storage",
    "noise cancelling headphones over ear",
    "wireless earbuds in ear audio",
    "adjustable desk lamp warm light",
    "standing desk height adjustable",
    "ergonomic office chair lumbar support",
    "laptop stand adjustable aluminium",
]
QUERIES = [
    ("big 4k screen for my desk", 0),
    ("quiet wireless keyboard", 3),
    ("mouse wrist support vertical", 6),
    ("podcast usb microphone", 7),
    ("4k camera for streaming", 10),
    ("laptop docking ports usb", 11),
    ("portable solid state storage", 12),
    ("headphones noise cancelling", 14),
    ("warm adjustable lamp", 16),
    ("office chair lumbar", 18),
]
SQL = (
    "SELECT id, similarity(search_text, :q) AS score FROM s8_public "
    "WHERE status='OPEN' ORDER BY score DESC,id LIMIT 5"
)


async def main() -> None:
    raw = os.environ.get("DATABASE_URL", "")
    require_test_database(raw)
    url, args = normalize_database_url(raw)
    engine = create_async_engine(url, connect_args=args)
    results = []
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TEMP TABLE s8_public(id int, status text, search_text text) "
                    "ON COMMIT DROP"
                )
            )
            started = time.perf_counter()
            await connection.execute(
                text("INSERT INTO s8_public VALUES(:id,'OPEN',:content)"),
                [
                    {"id": i, "content": item + " NEW US-EAST delivered shipping tax included"}
                    for i, item in enumerate(PRODUCTS)
                ],
            )
            ingest_ms = (time.perf_counter() - started) * 1000
            for query, expected in QUERIES:
                started = time.perf_counter()
                rows = (await connection.execute(text(SQL), {"q": query})).all()
                results.append(
                    dict(
                        query=query,
                        expected_id=expected,
                        top_five=[r.id for r in rows],
                        hit=expected in [r.id for r in rows],
                        latency_ms=(time.perf_counter() - started) * 1000,
                    )
                )
    finally:
        await engine.dispose()
    report = dict(
        status="pending",
        selected_backend="postgres",
        measured_at=datetime.now(UTC).isoformat(),
        dataset={"documents": PRODUCTS, "queries": QUERIES},
        postgres=dict(
            request_shape=SQL,
            ingest_ms=ingest_ms,
            recall_at_5=sum(r["hit"] for r in results) / len(results),
            results=results,
        ),
        elastic=dict(
            status="pending",
            reason="No exported Elastic endpoint/API key; comparison not run",
            documentation="https://www.elastic.co/docs/solutions/search/hybrid-semantic-text",
            trial_start=None,
            trial_end=None,
        ),
        acceptance=(
            "Keep PostgreSQL until live Elastic query success and recall >= baseline are recorded"
        ),
    )
    path = ROOT / "docs/evidence/phase2/s8.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PostgreSQL pg_trgm recall@5: {report['postgres']['recall_at_5']:.0%}; "
        "Elastic comparison pending"
    )


if __name__ == "__main__":
    asyncio.run(main())
