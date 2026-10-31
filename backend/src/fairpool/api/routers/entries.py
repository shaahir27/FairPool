"""Pool entries: join, read, withdraw (T03B01) and the vault lifecycle (T03B04).

The join, read and withdraw routes are Member B's T03B01 lane and are unchanged
here; the three vault routes are T03B04's CR-3 fake permission lifecycle. Every
other route in this file stays a stub until its own task. Each vault route is
owner-scoped (another buyer's entry id answers ``404``, the same as an unknown id),
keeps the payment token out of every response, and lets the service do the
consent, attempt, quarantine and deletion bookkeeping.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Security
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_session
from fairpool.api.errors import error_response
from fairpool.config import Settings
from fairpool.db.models.catalog import PoolEntry
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.vault import FakePaymentVaultProvider
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, DecryptionError
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.modules.identity.service import Principal
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import signing_seed
from fairpool.modules.pools.vault import VaultService
from fairpool.ports import PaymentVaultProvider

router = APIRouter()

#: config-and-errors.md section 3: POST /api/v1/pools/{pool_id}/entries is 10/min/user.
JOIN_RATE_LIMIT = 10
JOIN_RATE_WINDOW_S = 60.0

# These two planned codes are not yet in the shared map in api/errors.py (a
# Member A file); the envelope is rendered directly here so the statuses leave
# this route exactly as config-and-errors.md section 4 fixes them.
_DIRECT_ERROR_STATUS = {"RULES_MISMATCH": 409, "INTEGRITY_ERROR": 500}


class JoinRateLimiter:
    """Same shape as ``AuthRateLimiter``, keyed by session user (CR-3)."""

    def __init__(self) -> None:
        self.clients: OrderedDict[str, deque[float]] = OrderedDict()

    def check(self, user_id: str, now: float) -> None:
        # shortcut: per-process limits; require shared enforcement before multi-process deployment.
        hits = self.clients.setdefault(user_id, deque())
        self.clients.move_to_end(user_id)
        while hits and now - hits[0] >= JOIN_RATE_WINDOW_S:
            hits.popleft()
        if len(hits) >= JOIN_RATE_LIMIT:
            raise HTTPException(
                429,
                "RATE_LIMITED",
                headers={"Retry-After": str(max(1, int(JOIN_RATE_WINDOW_S - (now - hits[0])) + 1))},
            )
        hits.append(now)
        if len(self.clients) > 4096:
            self.clients.popitem(last=False)


async def rate_limit_join(
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
) -> Principal:
    settings = request.app.state.settings
    if settings is not None and settings.rate_limit_enabled:
        if not hasattr(request.app.state, "join_limiter"):
            request.app.state.join_limiter = JoinRateLimiter()
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


def _planned_error(exc: ApplicationError) -> JSONResponse | None:
    """Render the codes the shared exception handler does not know yet."""
    status = _DIRECT_ERROR_STATUS.get(exc.code)
    if status is None:
        return None
    return error_response(status_code=status, code=exc.code, message="The entry request failed.")


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
    try:
        outcome = await _join_service(request).join(
            db,
            pool_id=pool_id,
            user_id=principal.user_id,
            confirmed_request_id=payload.confirmed_request_id,
            idempotency_key=idempotency_key,
        )
    except ApplicationError as exc:
        response = _planned_error(exc)
        if response is not None:
            return response
        raise
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
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    entry = await db.scalar(
        select(PoolEntry).where(
            PoolEntry.pool_id == pool_id, PoolEntry.user_id == principal.user_id
        )
    )
    if entry is None:
        raise HTTPException(404, "NOT_FOUND")
    # Allocation and offer views arrive with Phase 4 (T04A05). The vault fields come
    # from the vault service itself: a status and a four-character label, never a
    # token, and never a value invented here (vault-charge.md section 5). With no
    # VAULT_TOKEN_KEY configured no permission can exist at all, so the read reports
    # that instead of failing: a buyer's own entry page must not break over an
    # operator setting.
    vault_status: str | None = None
    vault_label: str | None = None
    if _settings(request).vault_token_key is not None:
        permission = await _vault_service(request).status(db, entry_id=entry.id)
        vault_status, vault_label = permission.status, permission.label
    return {
        "entry_id": entry.id,
        "entry_status": str(entry.status),
        "allocation": None,
        "offer": None,
        "vault_status": vault_status,
        "vault_label": vault_label,
    }


@router.delete(
    "/api/v1/pools/{pool_id}/entries/me",
    response_model=schemas.EntryWithdrawResponse,
    operation_id="entries_me_delete",
)
async def entries_me_delete(
    pool_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    try:
        outcome = await _join_service(request).withdraw(
            db, pool_id=pool_id, user_id=principal.user_id
        )
    except ApplicationError as exc:
        response = _planned_error(exc)
        if response is not None:
            return response
        raise
    # api.md: withdrawal "also deletes the saved PayPal permission in vault mode".
    # It runs after the entry is WITHDRAWN and inside the same request transaction,
    # so a permission that still arrives is quarantined rather than activated, and a
    # buyer who never saved anything gets the documented no-op back (idempotent).
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
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    settings = _settings(request)
    if payload.cap_cents != entry.cap_cents or payload.consent_version != (
        settings.vault_consent_version
    ):
        raise HTTPException(422, "VALIDATION_ERROR")
    try:
        redirect = await _vault_service(request).start(db, entry_id=entry.id)
    except ApplicationError as exc:
        response = _planned_error(exc)
        if response is not None:
            return response
        raise
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
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
    token: str | None = Query(None),
    payer_id: str | None = Query(None, alias="PayerID"),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    try:
        await _vault_service(request).complete(db, entry_id=entry.id, setup_token_id=token or "")
    except ApplicationError as exc:
        response = _planned_error(exc)
        if response is not None:
            return response
        raise
    # No status, no label and no identifier in the redirect target (rule 27).
    base = _settings(request).frontend_base_url.rstrip("/")
    return RedirectResponse(url=f"{base}/entries/{entry.id}", status_code=302)


# Delete the saved permission: the provider resource goes first, then the encrypted
# columns (vault-charge.md §5); a provider 404 counts as deleted.
@router.delete("/api/v1/entries/{entry_id}/vault", operation_id="vault_delete")
async def vault_delete(
    entry_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_session)],
    db: AsyncSession = Depends(database_session),
):
    entry = await _owned_entry(db, entry_id=entry_id, user_id=principal.user_id)
    try:
        permission = await _vault_service(request).withdraw(db, entry_id=entry.id)
    except ApplicationError as exc:
        response = _planned_error(exc)
        if response is not None:
            return response
        raise
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
    dependencies=[Security(require_session)],
)
async def me_entries() -> None:
    raise NotImplementedError("route arrives in a later phase")


@router.get(
    "/api/v1/entries/{entry_id}/status",
    response_model=schemas.EntryStatusResponse,
    operation_id="entry_status",
    dependencies=[Security(require_session)],
)
async def entry_status(entry_id: UUID) -> None:
    raise NotImplementedError("route arrives in a later phase")
