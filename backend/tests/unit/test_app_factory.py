"""T00A03: app factory, health/ready probes and the error envelope."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fairpool.api.app import create_app


@contextmanager
def client_for(app: Any, *, raise_server_exceptions: bool = True) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=raise_server_exceptions) as client:
        yield client


def error_of(response: Any) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    return error


def test_health_is_public_and_exact() -> None:
    with client_for(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_create_app_does_not_load_settings() -> None:
    app = create_app()
    assert app.state.settings is None


def test_ready_without_a_probe_is_not_ready() -> None:
    with client_for(create_app()) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "not_configured", "migrations": "not_configured"},
    }


def test_ready_with_passing_boolean_probe() -> None:
    with client_for(create_app(readiness_probe=lambda: True)) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok"},
    }


def test_ready_with_failing_boolean_probe() -> None:
    with client_for(create_app(readiness_probe=lambda: False)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_ready_with_checks_mapping() -> None:
    good = {"database": "ok", "migrations": "ok"}
    bad = {"database": "ok", "migrations": "pending"}
    with client_for(create_app(readiness_probe=lambda: good)) as client:
        assert client.get("/ready").status_code == 200
    with client_for(create_app(readiness_probe=lambda: bad)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == bad


def test_ready_with_async_probe() -> None:
    async def probe() -> dict[str, str]:
        return {"database": "ok", "migrations": "ok"}

    with client_for(create_app(readiness_probe=probe)) as client:
        response = client.get("/ready")
    assert response.status_code == 200


def test_ready_probe_failure_does_not_leak_the_exception() -> None:
    def probe() -> bool:
        raise RuntimeError("database password dummy-secret")

    with client_for(create_app(readiness_probe=probe)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert "dummy-secret" not in response.text
    assert response.json()["checks"] == {"database": "error", "migrations": "unknown"}


def test_unknown_route_uses_the_not_found_envelope() -> None:
    with client_for(create_app()) as client:
        response = client.get("/missing")
    assert response.status_code == 404
    error = error_of(response)
    assert error["code"] == "NOT_FOUND"
    assert error["details"] == {}
    assert error["request_id"]
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_validation_error_uses_the_envelope_without_echoing_input() -> None:
    app = create_app()

    async def validate(q: int) -> dict[str, int]:
        return {"q": q}

    app.add_api_route("/_test/validate", validate, methods=["GET"])
    with client_for(app) as client:
        response = client.get("/_test/validate?q=raw-secret-input")
    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["fields"]
    assert "raw-secret-input" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    ("status_code", "code"),
    [(401, "UNAUTHENTICATED"), (403, "FORBIDDEN")],
)
def test_auth_errors_use_the_envelope(status_code: int, code: str) -> None:
    app = create_app()

    async def deny() -> None:
        raise HTTPException(status_code=status_code, detail="raw-detail-token")

    app.add_api_route(f"/_test/deny{status_code}", deny, methods=["GET"])
    with client_for(app) as client:
        response = client.get(f"/_test/deny{status_code}")
    assert response.status_code == status_code
    error = error_of(response)
    assert error["code"] == code
    assert "raw-detail-token" not in response.text


def test_internal_error_hides_exception_text() -> None:
    app = create_app()

    async def explode() -> None:
        raise RuntimeError("super-secret-exception-text")

    app.add_api_route("/_test/explode", explode, methods=["GET"])
    with client_for(app, raise_server_exceptions=False) as client:
        response = client.get("/_test/explode")
    assert response.status_code == 500
    error = error_of(response)
    assert error["code"] == "INTERNAL_ERROR"
    assert "super-secret-exception-text" not in response.text
    assert error["request_id"]
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_request_id_is_propagated_to_success_and_error_responses() -> None:
    with client_for(create_app()) as client:
        healthy = client.get("/health", headers={"X-Request-ID": "req-abc"})
        missing = client.get("/missing", headers={"X-Request-ID": "req-def"})
    assert healthy.headers["X-Request-ID"] == "req-abc"
    assert missing.headers["X-Request-ID"] == "req-def"
    assert error_of(missing)["request_id"] == "req-def"


@pytest.mark.parametrize(
    ("status", "detail", "expected"),
    [
        (409, "POOL_CLOSED", "POOL_CLOSED"),
        (429, "RATE_LIMITED", "RATE_LIMITED"),
        (409, "private secret", "VALIDATION_ERROR"),
    ],
)
def test_application_error_code_and_retry_after(status, detail, expected):
    app = create_app()

    async def deny():
        raise HTTPException(status_code=status, detail=detail, headers={"Retry-After": "30"})

    app.add_api_route("/_test/application-error", deny)
    with client_for(app) as client:
        response = client.get("/_test/application-error")
    assert error_of(response)["code"] == expected
    assert response.headers["Retry-After"] == "30"
    assert "private secret" not in response.text
