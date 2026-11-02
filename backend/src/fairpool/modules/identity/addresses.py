"""Private address book; order shipping snapshots are never modified here (CR-7)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.identity import User, UserAddress
from fairpool.domain.errors import ApplicationError
from fairpool.ports import AuditLog


class AddressBook:
    def __init__(self, key: str, audit: AuditLog) -> None:
        self.cipher = Fernet(key.encode())
        self.audit = audit

    def seal(self, value: dict[str, Any]) -> bytes:
        return self.cipher.encrypt(json.dumps(value, separators=(",", ":")).encode())

    def open(self, value: bytes) -> dict[str, Any]:
        try:
            result = json.loads(self.cipher.decrypt(bytes(value)))
            if not isinstance(result, dict):
                raise ValueError
            return result
        except (InvalidToken, ValueError, UnicodeError):
            raise ApplicationError("INTEGRITY_ERROR") from None

    def view(self, row: UserAddress) -> dict[str, Any]:
        return {"id": row.id, "is_default": row.is_default, "address": self.open(row.address_enc)}

    async def list(self, session: AsyncSession, user_id: UUID) -> list[dict[str, Any]]:
        rows = await session.scalars(
            select(UserAddress)
            .where(UserAddress.user_id == user_id)
            .order_by(UserAddress.is_default.desc(), UserAddress.created_at, UserAddress.id)
        )
        return [self.view(row) for row in rows]

    async def save(
        self,
        session: AsyncSession,
        user_id: UUID,
        address: dict[str, Any],
        *,
        is_default: bool = False,
        address_id: UUID | None = None,
    ) -> dict[str, Any]:
        # Serialize default selection and edits across this user's sessions.
        await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
        row = (
            await session.scalar(
                select(UserAddress).where(
                    UserAddress.id == address_id, UserAddress.user_id == user_id
                )
            )
            if address_id
            else None
        )
        if address_id and row is None:
            raise ApplicationError("NOT_FOUND")
        first = (
            await session.scalar(
                select(UserAddress.id).where(UserAddress.user_id == user_id).limit(1)
            )
            is None
        )
        make_default = is_default or first or bool(row and row.is_default)
        if make_default:
            await session.execute(
                update(UserAddress).where(UserAddress.user_id == user_id).values(is_default=False)
            )
            await session.flush()
        if row is None:
            row = UserAddress(id=uuid4(), user_id=user_id)
            session.add(row)
        row.address_enc = self.seal(address)
        row.is_default = make_default
        await session.flush()
        await self.audit.append(
            session,
            actor=str(user_id),
            action="identity.address_saved",
            subject_type="user_address",
            subject_id=str(row.id),
            payload={"is_default": row.is_default},
        )
        return self.view(row)

    async def delete(self, session: AsyncSession, user_id: UUID, address_id: UUID) -> None:
        await session.scalar(select(User.id).where(User.id == user_id).with_for_update())
        row = await session.scalar(
            select(UserAddress).where(UserAddress.id == address_id, UserAddress.user_id == user_id)
        )
        if row is None:
            raise ApplicationError("NOT_FOUND")
        was_default = row.is_default
        await session.delete(row)
        await session.flush()
        if was_default:
            replacement = await session.scalar(
                select(UserAddress)
                .where(UserAddress.user_id == user_id)
                .order_by(UserAddress.created_at, UserAddress.id)
                .limit(1)
            )
            if replacement:
                replacement.is_default = True
        await self.audit.append(
            session,
            actor=str(user_id),
            action="identity.address_deleted",
            subject_type="user_address",
            subject_id=str(address_id),
            payload={},
        )
