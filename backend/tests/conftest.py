"""Shared test configuration: local env and Postgres fixtures (T01A01)."""

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


def _load_env_file() -> None:
    """Make host-side tests use the same local settings as the app.

    Values already present in the environment win (CI exports its own). The
    file is never printed and is git-ignored.
    """
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required for the Postgres test suite")
    return url


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Apply migration 0001 once; the tests themselves roll back."""
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
