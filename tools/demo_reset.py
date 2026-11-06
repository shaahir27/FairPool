"""T09A03: reset the demo database, guarded.

``make db-reset`` runs alembic straight against whatever ``DATABASE_URL`` says, and
this repository's ``.env`` points at the hosted Supabase demo database. So today a
convenient local command silently drops the schema the judges are looking at. This
tool owns the decision instead: it resolves its target with the same rules
``demo_seed.py`` uses, prints what it is about to destroy, and refuses to run without
an explicit confirmation.

    python tools/demo_reset.py            # refuses: needs --yes
    python tools/demo_reset.py --yes      # resets the loopback demo database
    DEMO_SEED_HOSTED=1 python tools/demo_reset.py --yes   # resets the hosted demo database
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT / "backend" / "src", ROOT / "tools"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from demo_seed import load_env, loopback_database_url  # noqa: E402  (same target rules)

#: The tables a rehearsal cares about. Row counts are printed before and after so the
#: operator sees the destruction is real and the reset left nothing behind.
COUNTED_TABLES: tuple[str, ...] = (
    "pools",
    "pool_entries",
    "lots",
    "bids",
    "bid_revisions",
    "awards",
    "buyer_orders",
    "ledger_entries",
    "audit_log",
    "users",
)


def resolve_target() -> str:
    """The database to reset: hosted only on the explicit opt-in, else loopback."""
    load_env()
    if os.environ.get("DEMO_SEED_HOSTED") == "1":
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise SystemExit("DEMO_SEED_HOSTED=1 but DATABASE_URL is not configured")
        print("target: HOSTED demo database (DEMO_SEED_HOSTED=1)")
        return url
    print("target: loopback demo database (set DEMO_SEED_HOSTED=1 to name the hosted one)")
    return loopback_database_url()


async def counts(url: str) -> dict[str, int]:
    from fairpool.db.session import normalize_database_url
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async_url, connect_args = normalize_database_url(url)
    engine = create_async_engine(async_url, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            rows: dict[str, int] = {}
            for table in COUNTED_TABLES:
                value: Any = await connection.scalar(text(f"SELECT count(*) FROM {table}"))  # noqa: S608
                rows[table] = int(value or 0)
            return rows
    finally:
        await engine.dispose()


def reset_schema(url: str) -> None:
    """Drop the public schema and rebuild it from the migrations.

    ``alembic downgrade base`` is the obvious tool and it cannot be used here:
    reversing the migration that made ``awards.bid_revision_id`` nullable has to put
    the NOT NULL back, and a force-awarded row is null *by design*, so the downgrade
    aborts partway through the reversal. Verified: on a database holding demo awards it
    raises IntegrityError and rolls back, leaving nothing reset. A demo reset must not
    depend on the data it is clearing, so this drops the schema outright. Migration
    0001 recreates ``citext`` and ``pg_trgm`` itself, so the rebuild is complete.
    """
    asyncio.run(_drop_public_schema(url))

    from alembic import command
    from alembic.config import Config

    os.environ["DATABASE_URL"] = url
    command.upgrade(Config(str(ROOT / "backend" / "alembic.ini")), "head")


async def _drop_public_schema(url: str) -> None:
    from fairpool.db.session import normalize_database_url
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async_url, connect_args = normalize_database_url(url)
    engine = create_async_engine(async_url, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            for statement in (
                "DROP SCHEMA public CASCADE",
                "CREATE SCHEMA public",
                "GRANT ALL ON SCHEMA public TO CURRENT_USER",
                "GRANT ALL ON SCHEMA public TO public",
            ):
                await connection.execute(text(statement))
            await connection.commit()
    finally:
        await engine.dispose()


def report(label: str, table: dict[str, int]) -> None:
    total = sum(table.values())
    shown = ", ".join(f"{name}={count}" for name, count in table.items())
    print(f"{label}: {total} rows across counted tables ({shown})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset the demo database.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm the reset; without it nothing is touched",
    )
    args = parser.parse_args(argv)

    url = resolve_target()
    before = asyncio.run(counts(url))
    report("before", before)
    if not args.yes:
        print("refusing: re-run with --yes. No data was changed.")
        return 2
    if sum(before.values()) == 0:
        print("already empty: nothing to reset.")
        return 0

    reset_schema(url)

    after = asyncio.run(counts(url))
    report("after", after)
    if sum(after.values()) != 0:
        print("FAILED: rows survived the reset; investigate before re-seeding.")
        return 1
    print("state cleared: run `make demo-seed` to rebuild the demo fixtures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
