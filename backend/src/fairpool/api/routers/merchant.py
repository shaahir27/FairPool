"""Generated route stubs (T01B01); each path is fixed by api.md section 2."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.adapters.ai.client import PROMPT_VERSION, AIUnavailable
from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant, require_session
from fairpool.db.models.auction import BidRevision, Merchant
from fairpool.db.models.catalog import Pool
from fairpool.db.models.pools import Lot
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.auction.bids import BidService
from fairpool.modules.auction.quote import QuoteService
from fairpool.modules.auction.reconcile import OfferReconciler
from fairpool.modules.identity.service import Principal
from fairpool.modules.intake.run_log import PostgresAiRunLogger
from fairpool.modules.merchants.profile import MerchantProfileService
from fairpool.modules.notify.service import PostgresNotifier
from fairpool.modules.pools.receipts import signing_seed
from fairpool.wiring import ai_client

router = APIRouter()
_MISSING = object()


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
    )
    await db.commit()
    return schemas.MerchantProfileResponse(
        merchant_id=merchant.id,
        display_name=merchant.display_name,
        onboarding_status=str(merchant.onboarding_status),
        attestations=merchant.attestations,
    )


@router.get(
    "/api/v1/merchant/lots",
    response_model=list[schemas.MerchantLotSummary],
    operation_id="merchant_lots",
    dependencies=[Security(require_merchant)],
)
async def merchant_lots(q: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")


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
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.BidConfirmResponse:
    """Confirm the current revision, then reconcile it in the same transaction.

    The confirm is BS-02/03/05 and the reconciliation is BS-04: both are written before
    the commit, so a merchant never sees a CONFIRMED bid that the flags already overturn.
    """
    service = _bid_service(request)
    merchant_id = await _merchant_id(db, principal)
    bid = await service.confirm(
        db, merchant_id=merchant_id, bid_id=bid_id, revision=payload.revision
    )
    lot = await db.get(Lot, bid.lot_id)
    if lot is not None:
        pool = await db.get(Pool, lot.pool_id)
        revision = await db.scalar(
            select(BidRevision).where(
                BidRevision.bid_id == bid.id,
                BidRevision.revision == int(bid.current_revision),
            )
        )
        if pool is not None and revision is not None:
            await _offer_reconciler(request).reconcile(
                db,
                bid=bid,
                revision=revision,
                lot=lot,
                pool=pool,
                merchant_user_id=principal.user_id,
            )
    await db.commit()
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
    return schemas.BidView(
        bid_id=bid.id,
        lot_id=bid.lot_id,
        status=str(bid.status),
        current_revision=int(bid.current_revision),
        structured=revision.structured,
        reject_reason=bid.reject_reason,
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


@router.get(
    "/api/v1/merchant/events",
    operation_id="merchant_events",
    dependencies=[Security(require_merchant)],
)
async def merchant_events() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/merchant/bids",
    response_model=schemas.MerchantBidList,
    operation_id="merchant_bids",
    dependencies=[Security(require_merchant)],
)
async def merchant_bids(status: str | None = Query(None)) -> None:
    raise NotImplementedError("route arrives in a later phase")
