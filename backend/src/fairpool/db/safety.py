"""Refuse automated destructive tests against ordinary or hosted databases."""

from sqlalchemy.engine import make_url


def require_test_database(value: str) -> None:
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not url.database.endswith("_test")
    ):
        raise ValueError("A disposable loopback PostgreSQL database ending in _test is required")
