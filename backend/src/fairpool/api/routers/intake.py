"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_session

router = APIRouter()


@router.post(
    "/api/v1/intake/messages",
    response_model=schemas.IntakeMessageResponse,
    operation_id="intake_messages",
    dependencies=[Security(require_session)],
)
async def intake_messages(payload: schemas.IntakeMessageRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/intake/confirm",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_confirm",
    dependencies=[Security(require_session)],
)
async def intake_confirm(payload: schemas.IntakeConfirmRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/intake/manual",
    response_model=schemas.IntakeConfirmResponse,
    operation_id="intake_manual",
    dependencies=[Security(require_session)],
)
async def intake_manual(payload: schemas.ManualIntakeRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")
