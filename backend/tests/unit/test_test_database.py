import pytest

from fairpool.db.safety import require_test_database


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost/fairpool",
        "postgresql://u:p@host.example/fairpool_test",
        "sqlite:///test",
        "postgresql://u:p@127.0.0.1/fairpool",
    ],
)
def test_rejects_non_disposable_database(url):
    with pytest.raises(ValueError, match="disposable"):
        require_test_database(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_accepts_explicit_local_test_database(host):
    host = f"[{host}]" if ":" in host else host
    require_test_database(f"postgresql+asyncpg://u:p@{host}:55432/fairpool_test")
