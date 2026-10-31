"""T01A01: readiness reports database and migration state without leaking errors."""

from __future__ import annotations

from typing import Any

import pytest

from fairpool.db import migrations


class _FakeConnection:
    def __init__(
        self,
        revision: str | None = "0001",
        *,
        fail_select: bool = False,
        fail_revision: bool = False,
    ) -> None:
        self.revision = revision
        self.fail_select = fail_select
        self.fail_revision = fail_revision

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: Any) -> None:
        if self.fail_select:
            raise RuntimeError("database is down")

    async def scalar(self, statement: Any) -> str | None:
        if self.fail_revision:
            raise RuntimeError("alembic_version is missing")
        return self.revision


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


def use_connection(monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection) -> None:
    monkeypatch.setattr(migrations, "get_engine", lambda: _FakeEngine(connection))


@pytest.mark.asyncio
async def test_ready_when_database_and_revision_match(monkeypatch):
    use_connection(monkeypatch, _FakeConnection(migrations.HEAD_REVISION))
    probe = migrations.make_readiness_probe()
    assert await probe() == {"database": "ok", "migrations": "ok"}


@pytest.mark.asyncio
async def test_pending_when_revision_is_different(monkeypatch):
    use_connection(monkeypatch, _FakeConnection("0000"))
    probe = migrations.make_readiness_probe()
    assert await probe() == {"database": "ok", "migrations": "pending"}


@pytest.mark.asyncio
async def test_not_migrated_when_version_table_is_missing(monkeypatch):
    use_connection(monkeypatch, _FakeConnection(fail_revision=True))
    probe = migrations.make_readiness_probe()
    assert await probe() == {"database": "ok", "migrations": "not_migrated"}


@pytest.mark.asyncio
async def test_database_error_is_reported_without_exception_text(monkeypatch):
    use_connection(monkeypatch, _FakeConnection(fail_select=True))
    probe = migrations.make_readiness_probe()
    assert await probe() == {"database": "error", "migrations": "unknown"}


def test_head_revision_is_a_string():
    assert isinstance(migrations.HEAD_REVISION, str)
    assert migrations.HEAD_REVISION
