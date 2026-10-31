"""Buyer registration and database-backed signed opaque sessions."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.ports import Clock


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    role: str


@dataclass(frozen=True)
class Login:
    user_id: UUID
    cookie: str = field(repr=False)
    csrf_token: str = field(repr=False)


class IdentityService:
    def __init__(self, signing_key: str, clock: Clock) -> None:
        self.key = signing_key.encode()
        self.clock = clock
        self.hasher = PasswordHasher()  # Argon2id defaults, including random salt.
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    def _signature(self, session_id: str) -> str:
        return hmac.new(self.key, ("session:v1:" + session_id).encode(), hashlib.sha256).hexdigest()

    async def register(
        self, session: AsyncSession, *, email: str, password: str, display_name: str
    ) -> dict[str, Any]:
        email = email.strip().lower()
        if (
            not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
            or len(email) > 320
            or not 8 <= len(password) <= 200
            or not display_name.strip()
            or len(display_name) > 120
        ):
            raise ApplicationError("VALIDATION_ERROR")
        hashed = await asyncio.to_thread(self.hasher.hash, password)
        uid = uuid4()
        inserted = await session.scalar(
            text(
                "INSERT INTO users(id,email,password_hash,display_name,role) "
                "VALUES(:id,:email,:hash,:name,'buyer') ON CONFLICT(email) DO NOTHING "
                "RETURNING id"
            ),
            {"id": uid, "email": email, "hash": hashed, "name": display_name.strip()},
        )
        if inserted is None:
            raise ApplicationError("VALIDATION_ERROR")
        return {"user_id": uid, "email": email, "role": "buyer"}

    async def login(self, session: AsyncSession, *, email: str, password: str) -> Login:
        row = (
            await session.execute(
                text("SELECT id,password_hash FROM users WHERE email=:email"),
                {"email": email.strip().lower()},
            )
        ).first()
        try:
            await asyncio.to_thread(
                self.hasher.verify, row.password_hash if row else self.dummy_hash, password
            )
        except (VerificationError, InvalidHashError):
            raise ApplicationError("UNAUTHENTICATED") from None
        if row is None:
            raise ApplicationError("UNAUTHENTICATED")
        now = await self.clock.db_now(session)
        sid, csrf = uuid4(), secrets.token_urlsafe(32)
        await session.execute(
            text(
                "INSERT INTO sessions(id,user_id,csrf_token,expires_at) "
                "VALUES(:id,:user,:csrf,:expires)"
            ),
            {"id": sid, "user": row.id, "csrf": csrf, "expires": now + timedelta(hours=24)},
        )
        return Login(row.id, f"{sid}.{self._signature(str(sid))}", csrf)

    async def authenticate(
        self,
        session: AsyncSession,
        cookie: str | None,
        *,
        csrf: str | None = None,
        unsafe: bool = False,
    ) -> Principal:
        try:
            sid, signature = (cookie or "").split(".", 1)
            session_id = UUID(sid)
            if not hmac.compare_digest(signature, self._signature(sid)):
                raise ValueError()
        except (ValueError, TypeError):
            raise ApplicationError("UNAUTHENTICATED") from None
        now = await self.clock.db_now(session)
        row = (
            await session.execute(
                text(
                    "SELECT s.user_id,s.csrf_token,u.role FROM sessions s JOIN users u ON "
                    "u.id=s.user_id WHERE s.id=:id AND s.revoked_at IS NULL AND "
                    "s.expires_at>:now"
                ),
                {"id": session_id, "now": now},
            )
        ).first()
        if row is None:
            raise ApplicationError("UNAUTHENTICATED")
        if unsafe and (not csrf or not hmac.compare_digest(csrf, row.csrf_token)):
            raise ApplicationError("FORBIDDEN")
        return Principal(row.user_id, session_id, row.role)

    async def logout(self, session: AsyncSession, principal: Principal) -> None:
        await session.execute(
            text("UPDATE sessions SET revoked_at=:now WHERE id=:id"),
            {"now": await self.clock.db_now(session), "id": principal.session_id},
        )

    async def me(self, session: AsyncSession, principal: Principal) -> dict[str, Any]:
        row = (
            (
                await session.execute(
                    text(
                        (
                            "SELECT id AS user_id,email,display_name,role, EXISTS(SELECT 1 FROM "
                            "paypal_links p WHERE p.user_id=u.id AND p.revoked_at IS NULL) AS "
                            "paypal_linked, (SELECT count(*) FROM notifications n WHERE "
                            "n.user_id=u.id AND read_at IS NULL) "
                            "AS unread_notifications FROM users u"
                            " WHERE id=:id"
                        )
                    ),
                    {"id": principal.user_id},
                )
            )
            .mappings()
            .one()
        )
        return dict(row)
