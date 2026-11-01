"""Admin operations: force-award and the reconciler run (T04X01, T04A03).

``api.md`` section 3 fixes both bodies. The force-award helper is a demo and test
tool: it writes the immutable award a real ``lot.award`` would write and then
applies LS-14 through the whitelist, so it can never leave a lot in a state the
state machine does not name (CR-4). It refuses with ``FEATURE_DISABLED`` unless
``APP_ENV`` is ``local``/``test`` or ``MOCK_TOGGLES_ENABLED`` is set.

Everything else in this module stays the generated Phase 1 stub; the fixed route
table in ``api.md`` is the contract and those routes arrive with their own tasks.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Security
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_admin
from fairpool.db.models.auction import Award, Merchant
from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.enums import AllocationStatus, PaymentMode, PaymentRouter
from fairpool.db.models.pools import Allocation
from fairpool.domain import hashing
from fairpool.domain.errors import ApplicationError
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.jobs import PostgresJobQueue
from fairpool.modules.checkout.funding import apply_lot_transition, lock_lot
from fairpool.modules.identity.service import Principal
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.modules.reconciler.resolve import Reconciler

router = APIRouter()

#: LS-14 applies from these states (state-machines.md).
FORCE_AWARD_FROM: frozenset[str] = frozenset({"PLANNED", "BIDDING", "BID_CLOSED"})

#: ``APP_ENV`` values the helper is allowed in (api.md section 3).
FORCE_AWARD_ENVS: frozenset[str] = frozenset({"local", "test"})


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
    status_code=201,
    dependencies=[Security(require_admin)],
)
async def admin_lot_force_award(
    lot_id: UUID,
    payload: schemas.ForceAwardRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_admin)],
    db: AsyncSession = Depends(database_session),
):
    settings = request.app.state.settings
    enabled = settings.app_env in FORCE_AWARD_ENVS or settings.mock_toggles_enabled
    if not enabled:
        # api.md section 3: the helper is local/test/demo only.
        raise ApplicationError("FEATURE_DISABLED")

    lot = await lock_lot(db, lot_id)
    if str(lot.status) not in FORCE_AWARD_FROM:
        raise ApplicationError("ORDER_STATE_INVALID")
    merchant = await db.scalar(select(Merchant).where(Merchant.id == payload.merchant_id))
    if merchant is None:
        raise ApplicationError("NOT_FOUND")
    pool = await db.scalar(select(Pool).where(Pool.id == lot.pool_id))
    if pool is None:
        raise ApplicationError("INTEGRITY_ERROR")

    clock = DbClock()
    now = await clock.db_now(db)
    valid_until = now + timedelta(minutes=int(payload.valid_minutes))

    # flat_delivered: one delivered price per seat, so the total is item_cents and
    # the body carries no breakdown (flat-delivered-bids.md).
    item_cents = int(payload.item_cents)
    seated = (
        await db.execute(
            select(Allocation.entry_id, PoolEntry.cap_cents)
            .join(PoolEntry, PoolEntry.id == Allocation.entry_id)
            .where(
                Allocation.lot_id == lot.id,
                Allocation.status == AllocationStatus.SEATED,
            )
        )
    ).all()
    # A seat refilled from the waitlist is priced from the award it joins, so a flat
    # award prices every candidate of the lot's zone, not only today's seated rows:
    # ``open_checkout.create_offer`` reads a total for the seat it is about to offer
    # and cannot offer a seat the award does not price. Waitlisted rows keep their
    # lot_id NULL, so this read is scoped by zone rather than by the lot column.
    candidates = (
        await db.execute(
            select(Allocation.entry_id)
            .join(PoolEntry, PoolEntry.id == Allocation.entry_id)
            .where(
                Allocation.pool_id == lot.pool_id,
                Allocation.zone_id == lot.zone_id,
                Allocation.status.in_([AllocationStatus.SEATED, AllocationStatus.WAITLISTED]),
            )
        )
    ).all()
    totals = {
        str(entry_id): {
            "item_cents": item_cents,
            "shipping_cents": 0,
            "tax_cents": 0,
            "total_cents": item_cents,
        }
        for (entry_id,) in candidates
    }
    document = {
        "v": 1,
        "lot_id": str(lot.id),
        # CR-4: a forced award has no bid behind it; the key is hashed as null.
        "bid_revision_id": None,
        "merchant_id": str(merchant.id),
        "tier_index": int(payload.tier_index),
        "item_cents": item_cents,
        "moq": int(payload.moq),
        "totals": totals,
        "valid_until": valid_until.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "rule_version": "ranking_v1",
    }
    award = Award(
        id=uuid4(),
        lot_id=lot.id,
        bid_revision_id=None,
        merchant_id=merchant.id,
        tier_index=int(payload.tier_index),
        item_cents=item_cents,
        moq=int(payload.moq),
        totals=totals,
        valid_until=valid_until,
        rule_version="ranking_v1",
        award_hash=hashing.award_hash(document),
    )
    db.add(award)
    await db.flush()

    # N8: the router and mode are stamped at award time. A SIMULATION pool always
    # uses the fake router, whatever the deployment is configured with (I12).
    router_name = "fake" if str(pool.mode) == "SIMULATION" else settings.payment_router
    lot.payment_router = PaymentRouter(router_name)
    lot.payment_mode = PaymentMode(settings.payment_mode)
    lot.award_id = award.id

    # SEATED entries whose cap cannot cover the awarded total are PRICED_OUT at
    # award time; the same release rule then fills their seats (CR-4, N12).
    priced_out = 0
    for entry_id, cap_cents in seated:
        if int(cap_cents) < item_cents:
            await db.execute(
                text(
                    "UPDATE allocations SET status = 'PRICED_OUT'::allocation_status, "
                    "lot_id = NULL WHERE lot_id = :lot AND entry_id = :entry"
                ),
                {"lot": lot.id, "entry": entry_id},
            )
            priced_out += 1

    audit = PostgresAuditLog()
    await apply_lot_transition(
        db,
        lot=lot,
        to_status="AWARDED",
        trigger="admin.force_award",
        audit=audit,
        actor=str(principal.user_id),
        payload={
            "transition_id": "LS-14",
            "forced": True,
            "award_hash": award.award_hash,
            "item_cents": item_cents,
            "moq": int(payload.moq),
            "priced_out": priced_out,
            "payment_router": router_name,
            "payment_mode": settings.payment_mode,
        },
    )
    jobs = PostgresJobQueue()
    await jobs.enqueue(
        db,
        "lot.open_checkout",
        {"lot_id": str(lot.id)},
        run_at=now,
        concurrency_key=f"lot:{lot.id}",
    )
    notifier = PostgresNotifier()
    await notifier.notify(
        db,
        user_id=merchant.user_id,
        kind="lot.awarded",
        payload={
            "pool_id": str(pool.id),
            "lot_id": str(lot.id),
            "award_hash": award.award_hash,
            "item_cents": item_cents,
        },
    )

    # CR-4 aligned the response model with this body, so the route returns it directly and
    # the OpenAPI surface and the payload cannot drift apart.
    return {
        "lot_id": lot.id,
        "award": {
            "award_hash": award.award_hash,
            "item_cents": item_cents,
            "moq": int(payload.moq),
            "tier_index": int(payload.tier_index),
            "valid_until": valid_until,
        },
        "lot_status": "AWARDED",
    }


@router.post(
    "/api/v1/admin/reconciler/run",
    operation_id="admin_reconciler_run",
    dependencies=[Security(require_admin)],
)
async def admin_reconciler_run(
    db: AsyncSession = Depends(database_session),
):
    reconciler = Reconciler(clock=DbClock(), jobs=PostgresJobQueue())
    enqueued = await reconciler.sweep(db, {})
    return JSONResponse(status_code=202, content={"enqueued": enqueued})


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
