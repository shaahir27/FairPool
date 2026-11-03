"""Provision the disposable loopback test database that ``make test`` needs.

``db/safety.py`` refuses anything but a loopback database whose name ends in
``_test``, so a clean clone cannot run the suite until one exists (D-P3-05). This
creates it when it is missing and applies no migrations; ``make test`` does that.

A missing or unreachable server is a note, not a failure: ``make setup`` bootstraps
a machine, and Postgres may legitimately start after it.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from fairpool.db.safety import require_test_database
from fairpool.db.session import normalize_database_url
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]


def target_url() -> str:
    """The loopback ``*_test`` URL the suite will use, resolved the conftest way."""
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        values = dotenv_values(ROOT / ".env")
        url = values.get("TEST_DATABASE_URL") or values.get("DATABASE_URL") or ""
    return url


async def ensure(url: str) -> str:
    """Create the database if absent; return the outcome for the caller to print."""
    target = make_url(url)
    name = str(target.database)
    # Connect to the maintenance database on the same cluster: CREATE DATABASE
    # cannot run inside a transaction, so the connection is opened in AUTOCOMMIT.
    admin_url = target.set(database="postgres").render_as_string(False)
    admin, connect_args = normalize_database_url(admin_url)
    engine = create_async_engine(admin, connect_args=connect_args, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            existing = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            )
            if existing is not None:
                return f"{name}: already exists"
            # The name is this repository's own constant, not user input; quoted anyway.
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
            return f"{name}: created"
    finally:
        await engine.dispose()


def main() -> int:
    url = target_url()
    if not url:
        print("test db: SKIP - no DATABASE_URL or TEST_DATABASE_URL (set one in .env)")
        return 0
    try:
        require_test_database(url)
    except ValueError as error:
        print(f"test db: SKIP - {error}")
        return 0
    try:
        print(f"test db: {asyncio.run(ensure(url))}")
    except Exception as error:  # noqa: BLE001 - a bootstrap step must not fail the install
        print(f"test db: SKIP - cannot reach the server ({type(error).__name__}); start Postgres")
    return 0


if __name__ == "__main__":
    sys.exit(main())
