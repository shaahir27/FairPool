"""Shared test configuration: explicit environment and isolated Postgres fixtures (T01A01)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from fairpool.db.session import normalize_database_url

ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for the Postgres test suite")
    from fairpool.db.safety import require_test_database

    require_test_database(url)
    return url


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Apply migrations once; the tests themselves roll back."""
    database_url()  # Refuse ordinary or hosted databases before invoking Alembic.
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
    )


@pytest.fixture
async def db_engine(migrated_db: None) -> AsyncIterator[AsyncEngine]:
    url, connect_args = normalize_database_url(database_url())
    engine = create_async_engine(url, connect_args=connect_args, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
