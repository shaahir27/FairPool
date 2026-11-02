"""PayPal proof precedes buyer registration; no payment permission is requested."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any, Final
from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.config import SANDBOX_CHECKOUT_HOST, Settings, assert_sandbox_host
from fairpool.db.models.identity import PayPalLink, PayPalSignup
from fairpool.domain.errors import ApplicationError
from fairpool.modules.identity.addresses import AddressBook
from fairpool.modules.identity.paypal_login import LOGIN_AUTHORIZE_PATH, account_key
from fairpool.modules.identity.service import IdentityService, Login
from fairpool.ports import AuditLog, Clock, PayPalIdentity

#: Bounded account setup window on the DB clock after successful OAuth exchange (I15).
SIGNUP_SETUP_TTL_S: Final[int] = 1800

#: The scope string PayPal documents for Login with PayPal when the app's attributes
#: are enabled (developer.paypal.com/log-in/build-button and the Scope attributes
#: table): ``profile`` for the name, ``email``, ``address``, and the URI-form scope for
#: the account information row (verification status and payer ID). Without the URI
#: scope the grant carries no attributes, which is why userinfo returned identifiers
#: only and the signup form never prefilled. No payment or vault scope is asked for
#: (``vault-charge.md``: consent is a separate, later step).
SIGNUP_SCOPE: Final[str] = (
    "openid profile email address https://uri.paypal.com/services/paypalattributes"
)


class PayPalSignupService:
    def __init__(
        self,
        settings: Settings,
        identity: PayPalIdentity,
        clock: Clock,
        audit: AuditLog,
        accounts: IdentityService,
    ) -> None:
        self.settings = settings
        self.identity = identity
        self.clock = clock
        self.audit = audit
        self.accounts = accounts
        self.key = settings.hmac_key.get_secret_value()
        self.addresses = AddressBook(settings.address_encryption_key.get_secret_value(), audit)

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self.key.encode(), f"{purpose}:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def _available(self) -> None:
        if not self.settings.paypal_login_enabled or self.settings.dedupe_mode != "two_keys":
            raise ApplicationError("FEATURE_DISABLED")

    async def start(self, session: AsyncSession, prior: str | None = None) -> tuple[str, str]:
        self._available()
        assert_sandbox_host(self.settings.paypal_checkout_base, SANDBOX_CHECKOUT_HOST)
        state = secrets.token_urlsafe(32)
        now = await self.clock.db_wall_now(session)
        live = await self._attempt(session, prior)
        if (
            live is not None
            and live.consumed_at is None
            and live.completed_at is None
            and live.expires_at > now
        ):
            # One browser, one pending attempt: reloading or revisiting the page
            # re-points that row instead of adding another to the shared database.
            row = live
            browser = str(prior)
        else:
            if prior:
                await session.execute(
                    text(
                        "DELETE FROM paypal_signups "
                        "WHERE browser_hash = :hash AND completed_at IS NULL"
                    ),
                    {"hash": self._digest("signup-browser", prior)},
                )
            browser = secrets.token_urlsafe(32)
            row = PayPalSignup(
                id=uuid4(),
                browser_hash=self._digest("signup-browser", browser),
                expires_at=now + timedelta(seconds=self.settings.oauth_state_ttl_s),
            )
            session.add(row)
        row.state_hash = self._digest("signup-state", state)
        row.expires_at = now + timedelta(seconds=self.settings.oauth_state_ttl_s)
        await session.flush()
        query = urlencode(
            {
                "flowEntry": "static",
                "response_type": "code",
                "client_id": self.settings.paypal_client_id,
                "scope": SIGNUP_SCOPE,
                "state": state,
                "redirect_uri": self.settings.public_base_url.rstrip("/")
                + "/api/v1/auth/paypal/callback",
            }
        )
        return self.settings.paypal_checkout_base + LOGIN_AUTHORIZE_PATH + "?" + query, browser

    async def _attempt(
        self,
        session: AsyncSession,
        browser: str | None,
        *,
        lock: bool = False,
    ) -> PayPalSignup | None:
        if not browser or len(browser) > 128:
            return None
        query = select(PayPalSignup).where(
            PayPalSignup.browser_hash == self._digest("signup-browser", browser)
        )
        if lock:
            query = query.with_for_update()
        return await session.scalar(query)

    async def status(self, session: AsyncSession, browser: str | None) -> dict[str, Any]:
        enabled = self.settings.paypal_login_enabled and self.settings.dedupe_mode == "two_keys"
        row = await self._attempt(session, browser)
        status = "not_started"
        if row is not None:
            if row.completed_at is not None:
                # The account exists; this is not a form that needs finishing again.
                status = "registered"
            elif row.expires_at <= await self.clock.db_wall_now(session):
                status = "expired"
            elif row.authenticated_at is not None:
                status = "ready"
            else:
                status = "pending"
        prefill = (
            self.addresses.open(row.profile_enc)
            if enabled and status == "ready" and row is not None and row.profile_enc
            else None
        )
        return {"enabled": enabled, "status": status, "prefill": prefill}

    async def _already_registered(self, session: AsyncSession, key: str) -> bool:
        # A revoked link does not let its owner enroll a second buyer (I6, CR-6).
        linked = await session.scalar(
            select(PayPalLink.id).where(PayPalLink.paypal_account_key == key).limit(1)
        )
        completed = await session.scalar(
            select(PayPalSignup.id)
            .where(PayPalSignup.account_key == key, PayPalSignup.completed_at.is_not(None))
            .limit(1)
        )
        return linked is not None or completed is not None

    async def complete(
        self,
        session: AsyncSession,
        *,
        browser: str | None,
        state: str | None,
        code: str | None,
    ) -> None:
        self._available()
        row = await self._attempt(session, browser, lock=True)
        now = await self.clock.db_wall_now(session)
        if (
            row is None
            or not state
            or not code
            or len(state) > 128
            or len(code) > 4096
            or row.expires_at <= now
            or row.consumed_at is not None
            or not hmac.compare_digest(row.state_hash, self._digest("signup-state", state))
        ):
            raise ApplicationError("FORBIDDEN")
        # Single-use grants are never retried after an unknown exchange outcome.
        row.consumed_at = now
        await session.flush()
        tokens = await self.identity.exchange_code(code)
        profile = await self.identity.userinfo(tokens.access_token, tokens.id_token)
        key = account_key(self.key, profile.account_id)
        if await self._already_registered(session, key):
            raise ApplicationError("PAYPAL_LINK_CONFLICT")
        now = await self.clock.db_wall_now(session)
        if row.expires_at <= now:
            raise ApplicationError("FORBIDDEN")
        row.account_key = key
        row.profile_enc = self.addresses.seal(profile.details) if profile.details else None
        row.authenticated_at = now
        # Separate the short OAuth-state window from a bounded setup window on the DB clock (I15).
        row.expires_at = now + timedelta(seconds=SIGNUP_SETUP_TTL_S)
        await session.flush()

    async def register(
        self,
        session: AsyncSession,
        *,
        browser: str | None,
        email: str,
        password: str,
        password_confirm: str,
        display_name: str,
        delivery_address: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], Login]:
        self._available()
        if password != password_confirm:
            raise ApplicationError("VALIDATION_ERROR")
        row = await self._attempt(session, browser, lock=True)
        now = await self.clock.db_wall_now(session)
        if (
            row is None
            or row.authenticated_at is None
            or row.account_key is None
            or row.completed_at is not None
            or row.expires_at <= now
        ):
            raise ApplicationError("FORBIDDEN")
        # Different browsers can authenticate the same PayPal account concurrently.
        lock_key = int.from_bytes(bytes.fromhex(row.account_key)[:8], "big", signed=True)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        if await self._already_registered(session, row.account_key):
            raise ApplicationError("PAYPAL_LINK_CONFLICT")
        try:
            async with session.begin_nested():
                user = await self.accounts.register(
                    session,
                    email=email,
                    password=password,
                    display_name=display_name,
                )
                now = await self.clock.db_wall_now(session)
                if row.expires_at <= now:
                    raise ApplicationError("FORBIDDEN")
                session.add(
                    PayPalLink(
                        id=uuid4(),
                        user_id=user["user_id"],
                        paypal_account_key=row.account_key,
                        linked_at=now,
                    )
                )
                row.completed_at = now
                row.profile_enc = None
                await session.flush()
                if delivery_address is not None:
                    await self.addresses.save(
                        session, user["user_id"], delivery_address, is_default=True
                    )
                login = await self.accounts.login(session, email=email, password=password)
                await self.audit.append(
                    session,
                    actor=str(user["user_id"]),
                    action="identity.paypal_signup",
                    subject_type="user",
                    subject_id=str(user["user_id"]),
                    payload={"paypal_linked": True},
                )
        except IntegrityError:
            raise ApplicationError("PAYPAL_LINK_CONFLICT") from None
        return user, login
