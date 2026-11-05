"""CR-10: the browser policy headers and the inbound request-ID sanitiser.

The middleware is registered in ``api/app.py``; these tests mount it on the same app
factory the registration uses, so what is asserted is the header set a browser sees.
``sanitize_request_id`` is separate: the request ID is echoed into a response header
and every log line, so it may not carry arbitrary caller text (I14).
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from fairpool.api.app import create_app
from fairpool.infra.security_headers import (
    HEADERS,
    HSTS_VALUE,
    SecurityHeadersMiddleware,
    sanitize_request_id,
)
from tests.unit.test_settings import make_settings

HEX_ID = re.compile(r"[0-9a-f]{32}")


def app_with_middleware():  # type: ignore[no-untyped-def]
    app = create_app(make_settings())
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def test_every_response_carries_the_browser_policy() -> None:
    with TestClient(app_with_middleware(), base_url="https://api.test") as client:
        response = client.get("/health")
    assert response.status_code == 200
    for name, value in HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["Strict-Transport-Security"] == HSTS_VALUE


def test_the_policy_is_on_error_responses_too() -> None:
    # A 404 on a deep path can still be rendered by the browser; the headers apply.
    with TestClient(app_with_middleware(), base_url="https://api.test") as client:
        response = client.get("/missing")
    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_hsts_is_only_sent_over_https() -> None:
    with TestClient(app_with_middleware(), base_url="http://api.test") as client:
        response = client.get("/health")
    assert "Strict-Transport-Security" not in response.headers
    for name, value in HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.parametrize("value", ["req-abc", "a.b_c-1", "A" * 64, "0"])
def test_a_well_formed_request_id_is_kept(value: str) -> None:
    assert sanitize_request_id(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "A" * 65,
        "abc def",
        "abc\r\nX-Injected: 1",
        "<script>alert(1)</script>",
        "caf\u00e9",
    ],
)
def test_anything_else_becomes_a_fresh_identifier(value: str | None) -> None:
    generated = sanitize_request_id(value)
    assert HEX_ID.fullmatch(generated), generated
