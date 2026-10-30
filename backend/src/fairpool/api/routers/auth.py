"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_session

router = APIRouter()


@router.post(
    "/api/v1/auth/register",
    response_model=schemas.RegisterResponse,
    operation_id="auth_register",
)
async def auth_register(payload: schemas.RegisterRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/auth/login",
    response_model=schemas.LoginResponse,
    operation_id="auth_login",
)
async def auth_login(payload: schemas.LoginRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/auth/logout",
    operation_id="auth_logout",
    dependencies=[Security(require_session)],
)
async def auth_logout() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/me",
    response_model=schemas.MeResponse,
    operation_id="me_get",
    dependencies=[Security(require_session)],
)
async def me_get() -> None:
    raise NotImplementedError("route arrives in a later phase")
