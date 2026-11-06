"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Security
from fastapi.responses import StreamingResponse
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.adapters.ai.client import PROMPT_VERSION, AIUnavailable
from fairpool.adapters.search.projection import OPEN_LOT_STATUSES, PUBLIC_POOL_STATUSES
from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant, require_session
from fairpool.api.routers.pools import _search_service
from fairpool.db.models.auction import Bid, BidFlag, BidRevision, Merchant
from fairpool.db.models.catalog import Pool
from fairpool.db.models.enums import BidStatus, PoolMode
from fairpool.db.models.pools import Lot
from fairpool.db.session import create_engine
from fairpool.domain.errors import ApplicationError
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.auction.bids import BidService
from fairpool.modules.auction.confirm import confirm_and_reconcile
from fairpool.modules.auction.handlers import merchant_reject_copy
from fairpool.modules.auction.quote import QuoteService
from fairpool.modules.auction.reconcile import OfferReconciler
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.run_log import PostgresAiRunLogger
from fairpool.modules.merchants.events import has_capacity, stream_merchant_events
from fairpool.modules.merchants.profile import MerchantProfileService
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.modules.pools.receipts import signing_seed
from fairpool.modules.search.similarity import advise_confirmed_bid
from fairpool.ports import SearchService
from fairpool.wiring import ai_client

router = APIRouter()
_MISSING = object()

#: The most lots one merchant list answers with; the frozen Agent API has no page param.
OPEN_LOT_LIMIT = 100


def _auction_ai(request: Request) -> Any | None:
    """The model behind quote parsing and reconciliation, or ``None`` for the fallback.

    ``app.state.auction_ai`` is the test seam, exactly as intake has one; otherwise
    ``wiring.ai_client`` decides from ``AI_ENABLED``. A provider that is off does not
    fail a merchant: the quote route answers ``FEATURE_DISABLED`` and a confirmed bid
    with free text waits for ops review (``ai-schemas.md`` section 4).
    """
    injected = getattr(request.app.state, "auction_ai", _MISSING)
    if injected is not _MISSING:
        return injected  # type: ignore[no-any-return]
    settings = request.app.state.settings
    try:
        return ai_client(settings)
    except AIUnavailable:
        return None


def _profile_response(merchant: Merchant) -> schemas.MerchantProfileResponse:
    return schemas.MerchantProfileResponse(
        merchant_id=merchant.id,
        display_name=merchant.display_name,
        onboarding_status=str(merchant.onboarding_status),
        attestations=merchant.attestations,
        payee_email=merchant.payee_email,
        paypal_merchant_id=merchant.paypal_merchant_id,
    )


@router.get(
    "/api/v1/merchant/profile",
    response_model=schemas.MerchantProfileResponse,
    operation_id="merchant_profile_get",
)
async def merchant_profile_get(
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MerchantProfileResponse:
    if principal.role != "merchant":
        raise HTTPException(403, "FORBIDDEN")
    merchant = await db.scalar(select(Merchant).where(Merchant.user_id == principal.user_id))
    if merchant is None:
        raise ApplicationError("NOT_FOUND")
    return _profile_response(merchant)


@router.post(
    "/api/v1/merchant/profile",
    response_model=schemas.MerchantProfileResponse,
    operation_id="merchant_profile",
)
async def merchant_profile(
    payload: schemas.MerchantProfileRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MerchantProfileResponse:
    """Create or update the merchant row and stamp the three attestations.

    This is the one merchant route that cannot require the row: it creates it.
    The role check stays, so a buyer still cannot call it.
    """
    if principal.role != "merchant":
        raise HTTPException(403, "FORBIDDEN")
    service = MerchantProfileService(
        clock=DbClock(),
        demo=request.app.state.settings.payment_router == "single_seller",
    )
    merchant = await service.upsert(
        db,
        user_id=principal.user_id,
        display_name=payload.display_name,
        payee_email=payload.payee_email,
        paypal_merchant_id=payload.paypal_merchant_id,
        attestations=payload.attestations,
        present=payload.model_fields_set,
    )
    await db.commit()
    return _profile_response(merchant)


@router.get(
    "/api/v1/merchant/lots",
    response_model=list[schemas.MerchantLotSummary],
    operation_id="merchant_lots",
    dependencies=[Security(require_merchant)],
)
async def merchant_lots(
    request: Request,
    db: Annotated[AsyncSession, Depends(database_session)],
    q: str | None = Query(None),
) -> list[schemas.MerchantLotSummary]:
    search = _search_service(request) if q else None
    return await list_open_lots(db, search=search, q=q)


def _lot_summary(lot: Lot, pool: Pool) -> schemas.MerchantLotSummary:
    template = pool.template or {}
    return schemas.MerchantLotSummary(
        lot_id=lot.id,
        pool_id=lot.pool_id,
        zone_id=lot.zone_id,
        seats=lot.seats,
        min_seats=lot.min_seats,
        status=str(lot.status),
        bid_close_at=lot.bid_close_at,
        product_key=str(template.get("product_key") or ""),
        variant=str(template["variant"]) if template.get("variant") else None,
        condition=str(template.get("condition") or ""),
        delivery_sla_days=int(template.get("delivery_sla_days") or 0),
        min_return_days=int(template.get("min_return_days") or 0),
    )


async def list_open_lots(
    db: AsyncSession,
    *,
    search: SearchService | None,
    q: str | None,
    status: str | None = None,
) -> list[schemas.MerchantLotSummary]:
    """Lots in an open status; a ``q`` search ranks them, an empty one lists them (INT-1)."""
    statuses = list(OPEN_LOT_STATUSES)
    if status is not None:
        if status not in statuses:
            raise HTTPException(422, "VALIDATION_ERROR")
        statuses = [status]
    query = (
        select(Lot, Pool)
        .join(Pool, Pool.id == Lot.pool_id)
        .where(
            Lot.status.in_(statuses),
            Pool.status.in_(sorted(PUBLIC_POOL_STATUSES)),
            Pool.mode == PoolMode.LIVE_SANDBOX,
        )
    )
    hits = None
    if q:
        if search is None:
            raise HTTPException(500, "INTERNAL_ERROR")
        hits = await search.search(db, q=q, kinds=["lot"], status=statuses, limit=OPEN_LOT_LIMIT)
        ids = [hit.lot_id for hit in hits if hit.lot_id is not None]
        if not ids:
            return []
        query = query.where(Lot.id.in_(ids))
    found = (await db.execute(query.order_by(Lot.bid_close_at, Lot.id).limit(OPEN_LOT_LIMIT))).all()
    if hits is not None:
        # Keep the retrieval ranking; the SQL order above only makes the unranked path stable.
        by_id = {lot.id: (lot, pool) for lot, pool in found}
        found = [by_id[hit.lot_id] for hit in hits if hit.lot_id in by_id]
    return [_lot_summary(lot, pool) for lot, pool in found]


async def lot_summary_for(db: AsyncSession, lot_id: UUID) -> schemas.MerchantLotSummary:
    """One lot's requirement detail; an unknown id is the same ``404`` as a foreign bid.

    The pool filter is ``list_lots``'s: a DRAFT or cancelled pool's lots are not a
    merchant's to read, and the id alone must not open one.
    """
    row = (
        await db.execute(
            select(Lot, Pool)
            .join(Pool, Pool.id == Lot.pool_id)
            .where(
                Lot.id == lot_id,
                Pool.status.in_(sorted(PUBLIC_POOL_STATUSES)),
                Pool.mode == PoolMode.LIVE_SANDBOX,
            )
        )
    ).first()
    if row is None:
        raise ApplicationError("NOT_FOUND")
    return _lot_summary(row[0], row[1])


def bid_view(bid: Bid, revision: BidRevision, flags: list[BidFlag]) -> schemas.BidView:
    """The console and the Agent API return one bid shape; only the door differs."""
    return schemas.BidView(
        bid_id=bid.id,
        lot_id=bid.lot_id,
        status=str(bid.status),
        current_revision=int(bid.current_revision),
        structured=revision.structured,
        # CR-11: the stored code stays exact; the copy a merchant reads is coarsened
        # when it would describe the seated buyers' caps rather than their own bid.
        reject_reason=merchant_reject_copy(str(bid.reject_reason or "")) or None,
        flags=[
            schemas.BidFlagView(
                code=flag.code,
                severity=str(flag.severity),
                field=flag.field,
                evidence=flag.evidence,
            )
            for flag in flags
        ],
    )


def _app_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """The app's session factory, created lazily exactly as ``api/deps.py`` does.

    A background task outlives the request's session, so it opens its own unit of
    work here; the engine belongs to the app and is never disposed by this helper.
    """
    state = request.app.state
    if not hasattr(state, "session_factory"):
        state.engine = create_engine(state.settings)
        state.session_factory = async_sessionmaker(state.engine, expire_on_commit=False)
    factory: async_sessionmaker[AsyncSession] = state.session_factory
    return factory


async def advise_similarity(request: Request, bid_id: UUID) -> None:
    """Advisory only, after the response: it never fails or delays the confirm (INT-1)."""
    settings = request.app.state.settings
    if settings is None or not settings.similarity_check_enabled:
        return
    async with _app_session_factory(request)() as session:
        await advise_confirmed_bid(
            session, settings=settings, search=_search_service(request), bid_id=bid_id
        )


@router.post(
    "/api/v1/merchant/lots/{lot_id}/quote",
    response_model=schemas.QuoteResponse,
    operation_id="merchant_quote",
)
async def merchant_quote(
    lot_id: UUID,
    payload: schemas.QuoteRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.QuoteResponse:
    """Parse a pasted quote into a PROPOSED revision the merchant must confirm.

    Nothing stored here can enter the auction: an unconfirmed revision is rejected at
    award (R1, BS-11), and the fields the quote did not state stay empty to be filled
    (``ai-schemas.md`` section 3).
    """
    service = _quote_service(request)
    result = await service.propose(
        db,
        merchant_id=await _merchant_id(db, principal),
        lot_id=lot_id,
        quote_text=payload.quote_text,
    )
    await db.commit()
    return schemas.QuoteResponse(**result)


async def _merchant_id(db: AsyncSession, principal: Principal) -> UUID:
    value = await db.scalar(select(Merchant.id).where(Merchant.user_id == principal.user_id))
    if value is None:  # require_merchant already guarantees the row; belt and braces
        raise HTTPException(403, "FORBIDDEN")
    return value


def _bid_service(request: Request) -> BidService:
    settings = request.app.state.settings
    return BidService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        seed=signing_seed(settings.receipt_signing_key.get_secret_value()),
        flat_delivered=settings.bid_pricing_mode == "flat_delivered",
    )


def _quote_service(request: Request) -> QuoteService:
    """The paste-a-quote helper: it proposes, the merchant confirms (DEP-2)."""
    settings = request.app.state.settings
    return QuoteService(
        clock=DbClock(),
        audit=PostgresAuditLog(),
        run_logger=PostgresAiRunLogger(),
        ai=_auction_ai(request),
        model=settings.ai_model_parse,
        prompt_version=PROMPT_VERSION,
        signing_seed=signing_seed(settings.receipt_signing_key.get_secret_value()),
        flat_delivered=settings.bid_pricing_mode == "flat_delivered",
    )


def _offer_reconciler(request: Request) -> OfferReconciler:
    """The RECONCILE task behind a confirm: flags can withhold a bid, never qualify one."""
    settings = request.app.state.settings
    return OfferReconciler(
        audit=PostgresAuditLog(),
        run_logger=PostgresAiRunLogger(),
        notifier=PostgresNotifier(),
        ai=_auction_ai(request),
        model=settings.ai_model_parse,
        prompt_version=PROMPT_VERSION,
    )


@router.put(
    "/api/v1/merchant/lots/{lot_id}/bid",
    response_model=schemas.BidResponse,
    operation_id="merchant_bid_put",
)
async def merchant_bid_put(
    lot_id: UUID,
    payload: schemas.BidRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidResponse:
    """Save a new sealed revision and return its signed receipt (FR-AU-02)."""
    service = _bid_service(request)
    bid, revision = await service.save(
        db,
        merchant_id=await _merchant_id(db, principal),
        lot_id=lot_id,
        structured=payload.structured,
        quote_text=payload.quote_text,
        notes=payload.notes,
    )
    await db.commit()
    return schemas.BidResponse(
        bid_id=bid.id,
        revision=revision.revision,
        status=str(bid.status),
        receipt=schemas.BidReceipt(
            hash=revision.receipt_hash, signature=revision.receipt_signature
        ),
    )


@router.post(
    "/api/v1/merchant/bids/{bid_id}/confirm",
    response_model=schemas.BidConfirmResponse,
    operation_id="merchant_bid_confirm",
)
async def merchant_bid_confirm(
    bid_id: UUID,
    payload: schemas.BidConfirmRequest,
    request: Request,
    background: BackgroundTasks,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidConfirmResponse:
    """Confirm the current revision, then reconcile it in the same transaction.

    The confirm is BS-02/03/05 and the reconciliation is BS-04: both are written before
    the commit, so a merchant never sees a CONFIRMED bid that the flags already overturn.
    """
    service = _bid_service(request)
    bid = await confirm_and_reconcile(
        db,
        bid_service=service,
        reconciler=_offer_reconciler(request),
        merchant_id=await _merchant_id(db, principal),
        bid_id=bid_id,
        revision=payload.revision,
        merchant_user_id=principal.user_id,
    )
    await db.commit()
    # Advisory only, after the response: it never fails or delays the confirm (INT-1).
    background.add_task(advise_similarity, request, bid.id)
    return schemas.BidConfirmResponse(
        bid_id=bid.id, revision=int(bid.current_revision), status=str(bid.status)
    )


@router.get(
    "/api/v1/merchant/bids/{bid_id}",
    response_model=schemas.BidView,
    operation_id="merchant_bid_get",
)
async def merchant_bid_get(
    bid_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidView:
    """A merchant reads only its own bid; another merchant's id is NOT_FOUND (I11)."""
    service = _bid_service(request)
    bid, revision, flags = await service.get(
        db, merchant_id=await _merchant_id(db, principal), bid_id=bid_id
    )
    return bid_view(bid, revision, flags)


@router.get(
    "/api/v1/merchant/events",
    operation_id="merchant_events",
)
async def merchant_events(
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> StreamingResponse:
    # SSE: tick, lot_open, bid_status and checkout_progress. The auth read commits
    # before streaming, so no transaction or lock is held for the life of the
    # response; the generator then opens its own short read sessions.
    merchant_id = await _merchant_id(db, principal)
    await db.commit()
    if not has_capacity():
        raise HTTPException(429, "RATE_LIMITED", headers={"Retry-After": "60"})
    if not hasattr(request.app.state, "session_factory"):
        settings = request.app.state.settings
        if settings is None:
            raise HTTPException(500, "INTERNAL_ERROR")
        request.app.state.engine = create_engine(settings)
        request.app.state.session_factory = async_sessionmaker(
            request.app.state.engine, expire_on_commit=False
        )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return StreamingResponse(
        stream_merchant_events(factory, merchant_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


#: The newest bids one console list answers with; the contract has no page parameter.
BID_LIST_LIMIT = 100


@router.get(
    "/api/v1/merchant/bids",
    response_model=schemas.MerchantBidList,
    operation_id="merchant_bids",
)
async def merchant_bids(
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
    status: str | None = Query(None),
) -> schemas.MerchantBidList:
    # The merchant's own bids, newest first in SQL and oldest first in the body.
    # Three queries total (bids, current revisions, their flags): the per-bid loop
    # made the list cost grow with the history.
    merchant_id = await _merchant_id(db, principal)
    query = select(Bid).where(Bid.merchant_id == merchant_id)
    if status is not None:
        try:
            wanted = BidStatus(status)
        except ValueError:
            raise ApplicationError("VALIDATION_ERROR") from None
        query = query.where(Bid.status == wanted)
    bids = list(
        await db.scalars(query.order_by(Bid.created_at.desc(), Bid.id.desc()).limit(BID_LIST_LIMIT))
    )
    if not bids:
        return schemas.MerchantBidList(items=[])
    current = tuple_(BidRevision.bid_id, BidRevision.revision).in_(
        [(bid.id, int(bid.current_revision)) for bid in bids]
    )
    revisions = {
        revision.bid_id: revision
        for revision in await db.scalars(select(BidRevision).where(current))
    }
    flags: dict[UUID, list[BidFlag]] = {}
    revision_ids = [revision.id for revision in revisions.values()]
    if revision_ids:
        for flag in await db.scalars(
            select(BidFlag).where(BidFlag.bid_revision_id.in_(revision_ids))
        ):
            flags.setdefault(flag.bid_revision_id, []).append(flag)
    items = [
        bid_view(bid, revisions[bid.id], flags.get(revisions[bid.id].id, []))
        for bid in reversed(bids)
        if bid.id in revisions
    ]
    return schemas.MerchantBidList(items=items)
