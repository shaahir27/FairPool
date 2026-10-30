"""Alembic environment (T01A01): async engine, all models, strict comparison."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from fairpool.config import get_settings
from fairpool.db import models  # noqa: F401  (registers every table)
from fairpool.db.base import Base
from fairpool.db.session import normalize_database_url

config = context.config
target_metadata = Base.metadata

_COMPARE = {
    "compare_type": True,
    "compare_server_default": True,
}


def run_migrations_offline() -> None:
    url, _ = normalize_database_url(get_settings().database_url.get_secret_value())
    context.configure(
        url=url.render_as_string(hide_password=True),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_COMPARE,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, **_COMPARE)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url, connect_args = normalize_database_url(get_settings().database_url.get_secret_value())
    engine = create_async_engine(url, connect_args=connect_args, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
