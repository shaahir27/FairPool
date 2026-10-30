"""Liveness and readiness endpoints (T00A03, api.md /health and /ready)."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

ReadinessOutcome = bool | Mapping[str, str] | Awaitable[bool | Mapping[str, str]]
ReadinessProbe = Callable[[], ReadinessOutcome]

NOT_CONFIGURED_CHECKS: Final[dict[str, str]] = {
    "database": "not_configured",
    "migrations": "not_configured",
}
FAILED_CHECKS: Final[dict[str, str]] = {
    "database": "error",
    "migrations": "unknown",
}

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is serving requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: database and migrations, supplied by the composition root."""
    probe: ReadinessProbe | None = getattr(request.app.state, "readiness_probe", None)
    if probe is None:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": dict(NOT_CONFIGURED_CHECKS)},
        )
    try:
        outcome = probe()
        if inspect.isawaitable(outcome):
            outcome = await outcome
    except Exception:
        # Never leak a driver exception: readiness is a boolean health signal.
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": dict(FAILED_CHECKS)},
        )

    if isinstance(outcome, bool):
        state = "ok" if outcome else "not_ready"
        checks = {"database": state, "migrations": state}
        is_ready = outcome
    elif isinstance(outcome, Mapping):
        checks = {str(name): str(state) for name, state in outcome.items()}
        is_ready = bool(checks) and all(state == "ok" for state in checks.values())
    else:
        checks = dict(FAILED_CHECKS)
        is_ready = False

    if is_ready:
        return JSONResponse(status_code=200, content={"status": "ready", "checks": checks})
    return JSONResponse(status_code=503, content={"status": "not_ready", "checks": checks})
