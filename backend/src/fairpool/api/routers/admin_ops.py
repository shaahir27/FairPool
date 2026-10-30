"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Security

from fairpool.api import schemas
from fairpool.api.deps import require_admin

router = APIRouter()


@router.get(
    "/api/v1/admin/lots/{lot_id}",
    response_model=schemas.AdminLotView,
    operation_id="admin_lot_get",
    dependencies=[Security(require_admin)],
)
async def admin_lot_get(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/lots/{lot_id}/abort",
    operation_id="admin_lot_abort",
    dependencies=[Security(require_admin)],
)
async def admin_lot_abort(lot_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/lots/{lot_id}/force-award",
    response_model=schemas.AdminForceAwardResponse,
    operation_id="admin_lot_force_award",
    dependencies=[Security(require_admin)],
)
async def admin_lot_force_award(lot_id: UUID, payload: schemas.ForceAwardRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/reconciler/run",
    operation_id="admin_reconciler_run",
    dependencies=[Security(require_admin)],
)
async def admin_reconciler_run() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/admin/webhooks/dead-letter",
    operation_id="admin_dead_letter",
    dependencies=[Security(require_admin)],
)
async def admin_dead_letter() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/webhooks/{event_id}/retry",
    operation_id="admin_webhook_retry",
    dependencies=[Security(require_admin)],
)
async def admin_webhook_retry(event_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/admin/alerts",
    operation_id="admin_alerts",
    dependencies=[Security(require_admin)],
)
async def admin_alerts() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.post(
    "/api/v1/admin/mock",
    operation_id="admin_mock",
    dependencies=[Security(require_admin)],
)
async def admin_mock(payload: schemas.MockToggleRequest) -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/admin/audit/export",
    response_model=schemas.AuditExportResponse,
    operation_id="admin_audit_export",
    dependencies=[Security(require_admin)],
)
async def admin_audit_export() -> None:
    raise NotImplementedError("route arrives in a later phase")
