"""Pool entries: join, read, withdraw (T03B01) and the vault lifecycle (T03B04).

The join, read and withdraw routes are Member B's T03B01 lane and are unchanged
here; the three vault routes are T03B04's CR-3 fake permission lifecycle. Every
other route in this file stays a stub until its own task. Each vault route is
owner-scoped (another buyer's entry id answers ``404``, the same as an unknown id),
keeps the payment token out of every response, and lets the service do the
consent, attempt, quarantine and deletion bookkeeping.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_buyer
from fairpool.api.routers.checkout import _labels
from fairpool.config import Settings
from fairpool.db.models.auction import Award
from fairpool.db.models.catalog import Pool, PoolEntry
from fairpool.db.models.enums import BuyerOrderStatus, PoolMode
from fairpool.db.models.pools import Allocation, Lot
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.vault import FakePaymentVaultProvider
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, DecryptionError
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.infra.limits import SlidingWindowLimiter
from fairpool.modules.agentapi.views import entry_view, entry_views
from fairpool.modules.identity.service import Principal
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import receipt_for_entry, signing_seed
from fairpool.modules.pools.vault import VaultService
from fairpool.ports import PaymentVaultProvider

router = APIRouter()

logger = logging.getLogger("fairpool.entries")

#: The statuses under which a buyer order is still the entry's live offer (api.md "Entry").
ACTIVE_ORDER_STATUSES: tuple[BuyerOrderStatus, ...] = (
    BuyerOrderStatus.OFFERED,
    BuyerOrderStatus.ORDER_CREATED,
    BuyerOrderStatus.APPROVED,
    BuyerOrderStatus.AUTHORIZING,
    BuyerOrderStatus.AUTHORIZED,
    BuyerOrderStatus.CAPTURING,
    BuyerOrderStatus.CAPTURE_PENDING,
    BuyerOrderStatus.CAPTURED,
    BuyerOrderStatus.REFUNDING,
)

#: config-and-errors.md section 3: POST /api/v1/pools/{pool_id}/entries is 10/min/user.
JOIN_RATE_LIMIT = 10
JOIN_RATE_WINDOW_S = 60.0


class UserRateLimiter(SlidingWindowLimiter):
    """One sliding window per session user; ``config-and-errors.md`` section 3 limits.

    Keyed by the authenticated user rather than the client address, because two
    buyers behind one address must not share a budget. The intake route reuses this
    class with its own limit instead of carrying a second copy of the window.
    """

    def __init__(self, *, limit: int = JOIN_RATE_LIMIT, window_s: float = JOIN_RATE_WINDOW_S):
        super().__init__(limit=limit, window_s=window_s)


async def rate_limit_join(
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
) -> Principal:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        if not hasattr(request.app.state, "join_limiter"):
            request.app.state.join_limiter = UserRateLimiter()
        request.app.state.join_limiter.check(str(principal.user_id), time.monotonic())
    return principal


def _join_service(request: Request) -> JoinService:
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    cached: JoinService | None = getattr(request.app.state, "join_service", None)
    if cached is None:
        cached = JoinService(
            DbClock(),
            PostgresAuditLog(),
            PostgresIdempotencyStore(),
            signing_seed=signing_seed(settings.receipt_signing_key.get_secret_value()),
            dedupe_mode=settings.dedupe_mode,
        )
        request.app.state.join_service = cached
    return cached


# ------------------------------------------------------------------ vault wiring


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if settings is None:
        raise HTTPException(500, "INTERNAL_ERROR")
    return settings


async def _owned_entry(db: AsyncSession, *, entry_id: UUID, user_id: UUID) -> PoolEntry:
    """Owner-scoped fetch: someone else's entry id answers exactly like an unknown one."""
    entry = await db.scalar(
        select(PoolEntry).where(PoolEntry.id == entry_id, PoolEntry.user_id == user_id)
    )
    if entry is None:
        raise HTTPException(404, "NOT_FOUND")
    return entry


def _vault_cipher(request: Request) -> AesGcmCipher:
    cached: AesGcmCipher | None = getattr(request.app.state, "vault_cipher", None)
    if cached is not None:
        return cached
    settings = _settings(request)
    value = settings.vault_token_key.get_secret_value() if settings.vault_token_key else ""
    try:
        built = AesGcmCipher.from_config_value(value)
    except DecryptionError:
        # A malformed key is an operational failure; the value never reaches a log.
        raise HTTPException(500, "INTERNAL_ERROR") from None
    request.app.state.vault_cipher = built
    return built


def _vault_provider(request: Request) -> PaymentVaultProvider:
    """Phase 3 has one provider implementation: the inert local fake (DEP-5).

    ``T05A01`` wires the real ``POST /v3/vault/setup-tokens`` adapter here; a test
    or a simulation run scripts its own fake through ``app.state.vault_provider``.
    """
    injected = getattr(request.app.state, "vault_provider", None)
    if injected is not None:
        return injected  # type: ignore[no-any-return]
    created = FakePaymentVaultProvider()
    request.app.state.vault_provider = created
    return created


def _vault_service(request: Request) -> VaultService:
    settings = _settings(request)
    return VaultService(
        DbClock(),
        PostgresAuditLog(),
        _vault_cipher(request),
        _vault_provider(request),
        consent_version=settings.vault_consent_version,
        setup_ttl_s=settings.vault_setup_ttl_s,
        real_save_enabled=settings.vault_real_save_enabled,
    )


@router.post(
    "/api/v1/pools/{pool_id}/entries",
    response_model=schemas.EntryCreateResponse,
    operation_id="entries_join",
)
async def entries_join(
    pool_id: UUID,
    payload: schemas.EntryCreateRequest,
    request: Request,
    principal: Annotated[Principal, Security(rate_limit_join)],
    db: AsyncSession = Depends(database_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    # api.md section 1: required, any string up to 128 characters.
    if idempotency_key is None or not idempotency_key:
        raise HTTPException(400, "IDEMPOTENCY_KEY_REQUIRED")
    if len(idempotency_key) > 128:
        raise HTTPException(422, "VALIDATION_ERROR")
    outcome = await _join_service(request).join(
        db,
        pool_id=pool_id,
        user_id=principal.user_id,
        confirmed_request_id=payload.confirmed_request_id,
        idempotency_key=idempotency_key,
    )
    # The receipt payload is returned as the exact JSON bytes that were
    # signed; FastAPI must not re-serialise the timestamp (fairness §1).
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


@router.get(
    "/api/v1/pools/{pool_id}/entries/me",
    response_model=schemas.EntryStatusResponse,
    operation_id="entries_me_get",
)
async def entries_me_get(
    pool_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: AsyncSession = Depends(database_session),
):
    entry = await db.scalar(
        select(PoolEntry).where(
            PoolEntry.pool_id == pool_id, PoolEntry.user_id == principal.user_id
        )
    )
    if entry is None:
        raise HTTPException(404, "NOT_FOUND")
    # The allocation and the live offer come from the one view helper the agent lane
    # and ``entry_status`` already share, so this read cannot drift from them. The
    # vault fields come from the vault service itself: a status and a four-character
    # label, never a token, and never a value invented here (vault-charge.md
    # section 5). With no VAULT_TOKEN_KEY configured no permission can exist at all,
    # so the read reports that instead of failing: a buyer's own entry page must not
    # break over an operator setting.
    vault_status: str | None = None
    vault_label: str | None = None
    if _settings(request).vault_token_key is not None:
        permission = await _vault_service(request).status(db, entry_id=entry.id)
        vault_status, vault_label = permission.status, permission.label
    view = await _entry_view(db, entry, frontend_base_url=_settings(request).frontend_base_url)
    body = view.model_dump(mode="json")
    body["vault_status"] = vault_status
    body["vault_label"] = vault_label
    # CR-9: the same helper the join replay uses, so the read-back is the receipt
    # the pool signed. Returned as the exact JSON bytes for the same reason the
    # join is: FastAPI must not re-serialise the timestamp (fairness §1), or the
    # payload a buyer downloads would no longer be the text the signature covers.
    body["receipt"] = await _stored_receipt(db, entry)
    return JSONResponse(status_code=200, content=body)


async def _stored_receipt(db: AsyncSession, entry: PoolEntry) -> dict[str, object] | None:
    """The buyer's own stored receipt, or None when its row is missing.

    `receipt_for_entry` treats a missing `entry_receipts` row as an integrity break, which
    is right for the join replay that wrote it moments earlier. On a read that only reports
    state the same break must not blank the buyer's whole pool screen: the receipt is
    reported as absent and the break is logged, because inventing a receipt is never
    allowed (fairness §1, CR-9).
    """
    try:
        return await receipt_for_entry(db, entry)
    except ApplicationError as exc:
        if exc.code != "INTEGRITY_ERROR":
            raise
        logger.error("entries.me.receipt_missing entry_id=%s", entry.id)
        return None


@router.delete(
    "/api/v1/pools/{pool_id}/entries/me",
    response_model=schemas.EntryWithdrawResponse,
    operation_id="entries_me_delete",
)
async def entries_me_delete(
    pool_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: AsyncSession = Depends(database_session),
):
    # Phase 1 is the entry withdrawal alone. ``join.withdraw`` takes the ``users``
    # row lock and then the pool row lock, and a savepoint release keeps both to the
    # end of the transaction, so this commit is what frees them: no provider call may
    # run while a pool lock is held (domain-ports.md 4.4, vault-charge.md 2, I9).
    outcome = await _join_service(request).withdraw(db, pool_id=pool_id, user_id=principal.user_id)
    await db.commit()
    # Phase 2 is the provider step, on a fresh short transaction with no pool, lot or
    # entry lock held: api.md says withdrawal "also deletes the saved PayPal permission
    # in vault mode". A permission that still arrives afterwards is quarantined by the
    # callback, and a buyer who never saved anything gets the documented no-op back
    # (idempotent). If the provider fails the entry stays WITHDRAWN: phase 1 is already
    # durable and an unreachable provider is retried by the delete route, not undone.
    if outcome.body.get("entry_id") and _settings(request).vault_token_key is not None:
        permission = await _vault_service(request).withdraw(
            db, entry_id=UUID(str(outcome.body["entry_id"]))
        )
        outcome.body["vault_status"] = permission.status
        if permission.label is not None:
            outcome.body["vault_label"] = permission.label
    return JSONResponse(status_code=outcome.status_code, content=outcome.body)


# Consent and start saving PayPal: the explicit second step after the join (CR-3).
# The cap and the consent version are checked against what this server already froze
# for the entry: a client cannot move a cap a receipt covers, and a version the build
# does not render is not the wording the buyer saw (vault-charge.md §6). With
# VAULT_REAL_SAVE_ENABLED=false the service answers 403 FEATURE_DISABLED before
# writing anything (DEP-5).
@router.post(
    "/api/v1/entries/{entry_id}/vault",
    response_model=schemas.VaultStartResponse,
    operation_id="vault_start",
)
async def vault_start(
    entry_id: UUID,
    payload: schemas.VaultStartRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: AsyncSession = Depends(database_session),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    settings = _settings(request)
    if payload.cap_cents != entry.cap_cents or payload.consent_version != (
        settings.vault_consent_version
    ):
        raise HTTPException(422, "VALIDATION_ERROR")
    redirect = await _vault_service(request).start(db, entry_id=entry.id)
    # The response carries the approve URL and the version only: never a setup or
    # payment token identifier, and the URL is not logged (rule 27).
    return JSONResponse(
        status_code=200,
        content={"approve_url": redirect.approve_url, "consent_version": payload.consent_version},
    )


# The untrusted redirect: exchange our own stored setup token, then 302 home.
# ``token`` is never authority for anything: the service matches the caller's own
# live, unconsumed, unexpired attempt and exchanges the identifier it stored itself;
# a value that is not that identifier proves nothing (api.md "Entry", CR-3).
# ``PayerID`` exists in the provider redirect shape only and never selects a resource.
@router.get("/api/v1/entries/{entry_id}/vault/return", operation_id="vault_return")
async def vault_return(
    entry_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: AsyncSession = Depends(database_session),
    token: str | None = Query(None),
    payer_id: str | None = Query(None, alias="PayerID"),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    await _vault_service(request).complete(db, entry_id=entry.id, setup_token_id=token or "")
    # No status, no label and no identifier in the redirect target (rule 27).
    base = _settings(request).frontend_base_url.rstrip("/")
    return RedirectResponse(url=f"{base}/entries/{entry.id}", status_code=302)


# Delete the saved permission: the provider resource goes first, then the encrypted
# columns (vault-charge.md §5); a provider 404 counts as deleted.
@router.delete("/api/v1/entries/{entry_id}/vault", operation_id="vault_delete")
async def vault_delete(
    entry_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: AsyncSession = Depends(database_session),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    permission = await _vault_service(request).withdraw(db, entry_id=entry.id)
    return JSONResponse(
        status_code=200,
        content={
            "entry_id": str(entry.id),
            "vault_status": permission.status,
            "vault_label": permission.label,
        },
    )


@router.get(
    "/api/v1/me/entries",
    response_model=schemas.MeEntryList,
    operation_id="me_entries",
    dependencies=[Security(require_buyer)],
)
async def me_entries(
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.MeEntryList:
    rows = (
        await db.execute(
            select(PoolEntry, Pool, Lot, Award)
            .join(Pool, Pool.id == PoolEntry.pool_id)
            .outerjoin(
                Allocation,
                and_(Allocation.entry_id == PoolEntry.id, Allocation.pool_id == PoolEntry.pool_id),
            )
            .outerjoin(Lot, Lot.id == Allocation.lot_id)
            .outerjoin(Award, Award.id == Lot.award_id)
            .where(PoolEntry.user_id == principal.user_id)
            .order_by(PoolEntry.created_at, PoolEntry.id)
        )
    ).all()
    entries = [entry for entry, _, _, _ in rows]
    pools = {entry.pool_id: pool for entry, pool, _, _ in rows}
    lots = {entry.id: lot for entry, _, lot, _ in rows}
    awards = {entry.id: award for entry, _, _, award in rows}
    caps = {entry.id: entry.cap_cents for entry in entries}
    views = await entry_views(
        db,
        entries,
        frontend_base_url=_settings(request).frontend_base_url,
        include_terminal_orders=True,
    )
    return schemas.MeEntryList(
        items=[
            _me_entry(
                view,
                pool=pools[UUID(view["pool_id"])],
                lot=lots[UUID(view["entry_id"])],
                award=awards[UUID(view["entry_id"])],
                cap_cents=caps[UUID(view["entry_id"])],
            )
            for view in views
        ]
    )


@router.get(
    "/api/v1/entries/{entry_id}/status",
    response_model=schemas.EntryStatusResponse,
    operation_id="entry_status",
    dependencies=[Security(require_buyer)],
)
async def entry_status(
    entry_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_buyer)],
    db: Annotated[AsyncSession, Depends(database_session)],
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    view = await _entry_view(db, entry, frontend_base_url=_settings(request).frontend_base_url)
    vault_status: str | None = None
    vault_label: str | None = None
    if _settings(request).vault_token_key is not None:
        permission = await _vault_service(request).status(db, entry_id=entry.id)
        vault_status, vault_label = permission.status, permission.label
    # The receipt is returned as the stored JSON so its timestamp is not re-serialised
    # (CR-9); every other field is the one view helper both reads share.
    body = view.model_dump(mode="json")
    body["vault_status"] = vault_status
    body["vault_label"] = vault_label
    body["receipt"] = await _stored_receipt(db, entry)
    return JSONResponse(status_code=200, content=body)


async def _entry_view(
    db: AsyncSession, entry: PoolEntry, *, frontend_base_url: str
) -> schemas.MeEntry:
    return _me_entry(await entry_view(db, entry, frontend_base_url=frontend_base_url))


def _me_entry(
    view: dict[str, Any],
    *,
    pool: Pool | None = None,
    lot: Lot | None = None,
    award: Award | None = None,
    cap_cents: int | None = None,
) -> schemas.MeEntry:
    allocation = view["allocation"]
    if allocation is not None and cap_cents is not None:
        # F6: only the PRICED_OUT sentence needs these, but they are published for any
        # allocation because the same two numbers are what a seated buyer is charged.
        allocation = {
            **allocation,
            "cap_cents": cap_cents,
            "item_cents": None if award is None else int(award.item_cents),
        }
    offer = view["offer"]
    return schemas.MeEntry(
        entry_id=view["entry_id"],
        pool_id=view["pool_id"],
        entry_status=view["entry_status"],
        allocation=None if allocation is None else schemas.AllocationView(**allocation),
        offer=None if offer is None else schemas.OfferRef(**offer),
        pool_title=pool.title if pool is not None else None,
        pool_status=str(pool.status) if pool is not None else None,
        labels=_labels(lot)
        if lot is not None
        else (
            ["SANDBOX", "SIMULATED"]
            if pool is not None and pool.mode == PoolMode.SIMULATION
            else ["SANDBOX"]
        ),
        product=(
            schemas.ProductDisplay(
                title=str(pool.template.get("title", pool.title)),
                variant=pool.template.get("variant"),
                condition=str(pool.template.get("condition", "")),
                bundle_contents=[str(item) for item in pool.template.get("bundle_contents", [])],
            )
            if pool is not None
            else None
        ),
    )
