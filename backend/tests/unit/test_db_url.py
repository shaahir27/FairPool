"""T01A01: database URL normalisation for local and Render connections."""

from __future__ import annotations

import ssl

from fairpool.db.session import normalize_database_url


def test_plain_postgresql_scheme_becomes_asyncpg():
    url, connect_args = normalize_database_url("postgresql://user:secret@db.example:5432/fairpool")
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "db.example"
    assert url.password == "secret"
    assert connect_args == {}


def test_postgres_alias_is_accepted():
    url, _ = normalize_database_url("postgres://user:secret@localhost/fairpool")
    assert url.drivername == "postgresql+asyncpg"


def test_sslmode_require_becomes_an_ssl_context():
    url, connect_args = normalize_database_url(
        "postgresql://user:secret@render.example/fairpool?sslmode=require"
    )
    assert "sslmode" not in url.query
    context = connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_sslmode_verify_full_keeps_certificate_checking():
    _, connect_args = normalize_database_url(
        "postgresql://user:secret@render.example/fairpool?sslmode=verify-full"
    )
    context = connect_args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_asyncpg_url_is_left_alone():
    url, connect_args = normalize_database_url(
        "postgresql+asyncpg://user:secret@127.0.0.1:5432/fairpool"
    )
    assert url.drivername == "postgresql+asyncpg"
    assert connect_args == {}
