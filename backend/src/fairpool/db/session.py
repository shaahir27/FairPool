"""Async engine, session factory and database URL handling (T01A01)."""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fairpool.config import Settings, get_settings


def normalize_database_url(raw: str) -> tuple[URL, dict[str, object]]:
    """Return an asyncpg URL and the SSL connect args.

    Render's external URL uses ``postgresql://`` and may carry
    ``?sslmode=require``; asyncpg rejects that query parameter, so it is
    converted to an SSLContext.
    """
    url = make_url(raw)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    url = url.set(query=query)
    connect_args: dict[str, object] = {}
    if sslmode in {"require", "verify-ca", "verify-full"}:
        context = ssl.create_default_context()
        if sslmode == "require":
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = context
    return url, connect_args


def create_engine(settings: Settings) -> AsyncEngine:
    url, connect_args = normalize_database_url(settings.database_url.get_secret_value())
    return create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """The process-wide engine; import time never reads settings."""
    return create_engine(get_settings())


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """One transaction per request; the handler owns the work inside it."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
