"""Verify upgrade-from-0001, fresh head and drift in a newly created disposable DB."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fairpool.db.safety import require_test_database
from fairpool.db.session import normalize_database_url
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]


async def main() -> None:
    raw = os.environ.get("DATABASE_URL", "")
    require_test_database(raw)
    if os.environ.get("APP_ENV") != "test":
        raise ValueError("Migration verification requires APP_ENV=test")
    url, args = normalize_database_url(raw)
    name = f"fairpool_migration_{uuid4().hex}_test"
    engine = create_async_engine(url, connect_args=args, isolation_level="AUTOCOMMIT")
    created = False
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        child_url = url.set(database=name).render_as_string(hide_password=False)
        require_test_database(child_url)
        env = {**os.environ, "DATABASE_URL": child_url}
        for operation in (
            ("upgrade", "0001"),
            ("upgrade", "head"),
            ("check",),
            ("downgrade", "base"),
            ("upgrade", "head"),
            ("check",),
        ):
            subprocess.run(
                [sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", *operation],
                cwd=ROOT,
                env=env,
                check=True,
            )
        print("Upgrade from 0001, fresh head and both Alembic drift checks passed")
    finally:
        if created:
            async with engine.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}"'))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
