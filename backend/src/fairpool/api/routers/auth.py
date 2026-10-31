"""Buyer authentication; privileged accounts are operator-provisioned only."""

import time
from collections import OrderedDict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, identity_service, require_session
from fairpool.modules.identity.service import Principal

router = APIRouter()


class AuthRateLimiter:
    def __init__(self) -> None:
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, ip: str, now: float) -> None:
        # shortcut: per-process limits; require shared enforcement before multi-process deployment.
        hits = self.clients.setdefault(ip, deque())
        self.clients.move_to_end(ip)
        while hits and now - hits[0] >= 60:
            hits.popleft()
        if len(hits) >= 10:
            raise HTTPException(
                429,
                "RATE_LIMITED",
                headers={"Retry-After": str(max(1, int(60 - (now - hits[0])) + 1))},
            )
        hits.append(now)
        if len(self.clients) > 4096:
            self.clients.popitem(last=False)


def rate_limit(request: Request) -> None:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        if not hasattr(request.app.state, "auth_limiter"):
            request.app.state.auth_limiter = AuthRateLimiter()
        request.app.state.auth_limiter.check(
            request.client.host if request.client else "unknown", time.monotonic()
        )


@router.post(
    "/api/v1/auth/register",
    response_model=schemas.RegisterResponse,
    operation_id="auth_register",
    dependencies=[Depends(rate_limit)],
)
async def auth_register(
    payload: schemas.RegisterRequest, request: Request, db: AsyncSession = Depends(database_session)
):
    result = await identity_service(request).register(db, **payload.model_dump())
    return {"user_id": result["user_id"], "email": result["email"]}


@router.post(
    "/api/v1/auth/login",
    response_model=schemas.LoginResponse,
    operation_id="auth_login",
    dependencies=[Depends(rate_limit)],
)
async def auth_login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(database_session),
):
    result = await identity_service(request).login(db, **payload.model_dump())
    response.set_cookie(
        "session",
        result.cookie,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=86400,
        path="/",
    )
    return {"user_id": result.user_id, "csrf_token": result.csrf_token}


@router.post("/api/v1/auth/logout", operation_id="auth_logout")
async def auth_logout(
    response: Response,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    await identity_service(request).logout(db, principal)
    response.delete_cookie("session", path="/", httponly=True, samesite="lax")


@router.get("/api/v1/me", response_model=schemas.MeResponse, operation_id="me_get")
async def me_get(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    return await identity_service(request).me(db, principal)
