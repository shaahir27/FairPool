"""Intake routes: the conversation turn and the confirmation (T04B01, api.md "Intake").

Both routes are session-scoped (so CSRF is enforced by ``require_session`` on every
POST), owner-scoped through the authenticated principal, and strict about what they
return: a status, at most one question and the server-built card. Raw model output
never leaves :mod:`fairpool.modules.intake.pipeline`.

``body``/``logic`` split: the route validates the contracted request shape, the
service owns retrieval, the model call, the deterministic checks and the write. The
manual form's route is unchanged and shares the same confirmation service.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.ai.client import AIUnavailable
from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.api.routers.entries import UserRateLimiter
from fairpool.api.routers.pools import _search_service
from fairpool.config import Settings
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.manual import ManualIntakeService
from fairpool.modules.intake.pipeline import IntakeService
from fairpool.modules.intake.run_log import PostgresAiRunLogger
from fairpool.ports import AIClient
from fairpool.wiring import ai_client

router = APIRouter()

#: config-and-errors.md section 3: POST /api/v1/intake/messages is 20/min/user.
INTAKE_RATE_LIMIT = 20
INTAKE_RATE_WINDOW_S = 60.0

_MISSING = object()


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    return settings


def _ai(request: Request, settings: Settings) -> AIClient | None:
    """The configured model, or ``None`` so every turn answers with the manual form.

    ``app.state.intake_ai`` is the test seam (it replaces the provider call with a
    scripted fake); otherwise ``wiring.ai_client`` decides from ``AI_ENABLED``.
    """
    injected = getattr(request.app.state, "intake_ai", _MISSING)
    if injected is not _MISSING:
        return injected  # type: ignore[no-any-return]
    try:
        return ai_client(settings)
    except AIUnavailable:
        return None


def intake_service(request: Request) -> IntakeService:
    """One service per app: retrieval, the AI client and the turn history live with it."""
    cached: IntakeService | None = getattr(request.app.state, "intake_service", None)
    if cached is not None:
        return cached
    settings = _settings(request)
    built = IntakeService(
        search=_search_service(request),
        ai=_ai(request, settings),
        audit=PostgresAuditLog(),
        clock=DbClock(),
        run_logger=PostgresAiRunLogger(),
        model=settings.ai_model_parse,
    )
    request.app.state.intake_service = built
    return built


async def rate_limit_intake(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
) -> Principal:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        limiter: UserRateLimiter | None = getattr(request.app.state, "intake_limiter", None)
        if limiter is None:
            limiter = UserRateLimiter(limit=INTAKE_RATE_LIMIT, window_s=INTAKE_RATE_WINDOW_S)
            request.app.state.intake_limiter = limiter
        limiter.check(str(principal.user_id), time.monotonic())
    return principal


@router.post(
    "/api/v1/intake/messages",
    response_model=schemas.IntakeMessageResponse,
    operation_id="intake_messages",
)
async def intake_messages(
    payload: schemas.IntakeMessageRequest,
    request: Request,
    principal: Annotated[Principal, Security(rate_limit_intake)],
    db: AsyncSession = Depends(database_session),
):
    """One turn: a confirmation card, one clarifying question, or the manual form."""
    return await intake_service(request).propose(
        db,
        user_id=principal.user_id,
        message=payload.message,
        pool_id_override=payload.pool_id,
        session_id=payload.session_id,
    )


@router.post(
    "/api/v1/intake/confirm",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_confirm",
)
async def intake_confirm(
    payload: schemas.IntakeConfirmRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """Confirm a proposal into the canonical request the join endpoint consumes."""
    record = await intake_service(request).confirm(
        db, user_id=principal.user_id, proposal_id=payload.proposal_id
    )
    return JSONResponse(
        status_code=201,
        content={
            "confirmed_request_id": str(record.id),
            "canonical_request": record.canonical_request,
        },
    )


# The manual form is the deterministic half of intake (CR-3); it keeps its own
# handler and shares ``ManualIntakeService`` with the confirm route above.
@router.post(
    "/api/v1/intake/manual",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_manual",
)
async def intake_manual(
    payload: schemas.ManualIntakeRequest,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    """The deterministic half of intake (CR-3 pull-forward from T04B01).

    No AI is involved and nothing here depends on T02B03: the buyer's own form is
    validated against the pool's frozen template and stored as the immutable
    confirmed request the join endpoint consumes.
    """
    service = ManualIntakeService(PostgresAuditLog())
    record = await service.confirm(
        db,
        user_id=principal.user_id,
        pool_id=payload.pool_id,
        # The frozen validator accepts buyer-chosen fields only; ``pool_id`` selects
        # the pool and is not part of the request it validates.
        payload=payload.model_dump(mode="json", exclude={"pool_id"}),
    )
    # A raw Response skips FastAPI's jsonable_encoder, so every value must already
    # be JSON-native: ids are text here exactly as the join lane writes them.
    return JSONResponse(
        status_code=201,
        content={
            "confirmed_request_id": str(record.id),
            "canonical_request": record.canonical_request,
        },
    )
