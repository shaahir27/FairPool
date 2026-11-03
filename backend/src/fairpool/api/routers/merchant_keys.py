"""Merchant API keys: the three session-authenticated console routes (T06A07).

Contract: ``api.md`` section 4.2. The secret exists only in the create response; the
list carries the prefix, which is public to the merchant and already what an operator
needs to recognise a key. Revocation marks the row rather than deleting it, so the audit
trail keeps the subject it names, and a key that is revoked stops resolving at once
because ``merchants/auth.py`` reads ``revoked_at`` on every request.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api import schemas
from fairpool.api.deps import database_session, require_merchant
from fairpool.db.models.auction import Merchant
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import Principal
from fairpool.modules.merchants.api_keys import MerchantApiKeys

router = APIRouter()


def _keys(request: Request) -> MerchantApiKeys:
    settings = request.app.state.settings
    return MerchantApiKeys(
        clock=DbClock(), audit=PostgresAuditLog(), hmac_key=settings.hmac_key.get_secret_value()
    )


async def _merchant(db: AsyncSession, principal: Principal) -> Merchant:
    """The merchant row ``require_merchant`` has already proved exists."""
    row = await db.scalar(select(Merchant).where(Merchant.user_id == principal.user_id))
    if row is None:
        raise HTTPException(403, "FORBIDDEN")
    return row


@router.get(
    "/api/v1/merchant/api-keys",
    response_model=schemas.ApiKeyList,
    operation_id="merchant_api_keys_list",
)
async def merchant_api_keys_list(
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.ApiKeyList:
    """Every key this merchant issued, newest last, with the hash left in the database."""
    merchant = await _merchant(db, principal)
    rows = await _keys(request).list(db, merchant_id=merchant.id)
    return schemas.ApiKeyList(
        items=[
            schemas.ApiKeyView(
                id=row.id,
                name=row.name,
                key_prefix=row.key_prefix,
                scopes=list(row.scopes),
                last_used_at=row.last_used_at,
                revoked_at=row.revoked_at,
            )
            for row in rows
        ]
    )


@router.post(
    "/api/v1/merchant/api-keys",
    response_model=schemas.ApiKeyCreated,
    operation_id="merchant_api_keys_create",
    status_code=201,
)
async def merchant_api_keys_create(
    payload: schemas.ApiKeyCreateRequest,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> schemas.ApiKeyCreated:
    """Issue a key and show its secret here and only here (I14, FR-IG-04)."""
    merchant = await _merchant(db, principal)
    row, key = await _keys(request).create(
        db, merchant=merchant, name=payload.name, scopes=payload.scopes
    )
    await db.commit()
    return schemas.ApiKeyCreated(id=row.id, name=row.name, key=key, scopes=list(row.scopes))


@router.delete(
    "/api/v1/merchant/api-keys/{key_id}",
    operation_id="merchant_api_keys_delete",
)
async def merchant_api_keys_delete(
    key_id: UUID,
    request: Request,
    principal: Annotated[Principal, Security(require_merchant)],
    db: Annotated[AsyncSession, Depends(database_session)],
) -> None:
    """Revoke a key; a row that belongs to another merchant is not there (I11)."""
    merchant = await _merchant(db, principal)
    await _keys(request).revoke(db, merchant=merchant, key_id=key_id)
    await db.commit()
