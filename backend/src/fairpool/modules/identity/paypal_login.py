"""Log-in-with-PayPal account linking (T03B03, CR-3).

Contracts this file implements: ``api.md`` "Account link", ``db-schema.md``
(``oauth_states``, ``paypal_links``, ``pool_entries.paypal_account_key``),
``paypal-adapter.md`` section 7a, ``config-and-errors.md``
(``PAYPAL_LOGIN_ENABLED``, ``OAUTH_STATE_TTL_S``, ``DEDUPE_MODE``,
``REQUIRE_PAYPAL_LINK``, ``PAYPAL_LINK_CONFLICT``), ``state-machines.md`` (entry
machine) and spike S1 as recorded in ``spike-results.md``.

**What is fake and what is real, stated plainly.** The two Login identity calls
(``exchange_code``, ``userinfo``) reach PayPal only through the ``PayPalIdentity``
port, and in this build the only implementation of that port is
``fakes.paypal_identity.FakePayPalIdentity``. There is no HTTP client for
``POST /v1/oauth/token`` or ``GET /v1/identity/openidconnect/userinfo`` here, so
every test and CI run proves the port contract, the state ladder and the storage
rules -- **never a live provider round trip**. S1 recorded those two calls by hand
against the Sandbox. The real client belongs in ``adapters/paypal/`` (``AGENTS.md``
rule 3); ``modules.identity`` importing it would be an ``tools/check_imports.py``
rule 3 violation, which is exactly why the port exists and the whitelist stays as
it is (section 7a). Wiring the real client is a Phase 4 edit.

Rules, in order:

* ``PAYPAL_LOGIN_ENABLED=false`` refuses every route here with ``403
  FEATURE_DISABLED`` before a row exists (rule 19).
* ``start`` writes exactly one single-use ``oauth_states`` row bound to the
  **initiating session id**, expiring ``OAUTH_STATE_TTL_S`` on the database
  clock (I15), and returns only the authorize URL, which carries the ``state``.
* ``callback`` rejects a missing ``state``, an unknown, expired or already
  consumed row, and a row bound to another session -- in that order, with no
  provider call -- and a provider ``error`` writes nothing at all.
* The state row is consumed once, **before** the code is exchanged, so a replayed
  callback can neither re-link nor make a second provider call (I9). Every refusal
  runs inside one savepoint, so a rejected callback writes nothing at all.
* Only ``HMAC(HMAC_KEY, identifier)`` is stored (BD-12, I14). The code, both
  tokens and the raw ``sub``/``user_id`` are never persisted, logged, returned
  or audited, and the authorize URL never reaches a log line.
* ``DEDUPE_MODE=two_keys`` (the recorded S1 outcome) keeps the login key and the
  checkout ``payer_id`` key as two identifiers deduplicated separately, with no
  equality requirement and no prefix stripping. ``checkout_only`` stores no login
  key at all. ``full`` would additionally require them to be equal; equivalence
  was never proved, so the mode is refused rather than silently downgraded
  (OD-P3-4).
* Link, unlink and join serialise on the same ``users`` row lock that
  ``modules/pools/join.py`` takes first (user-then-pool, api.md "Account link"),
  and ``unlink`` is refused while the buyer still holds an entry, so relinking
  cannot evade the ``(pool_id, paypal_account_key)`` rule (F16, I6).
* Login identity and vault permissions are separate resources: this file writes
  no ``vault_tokens`` or ``vault_setup_attempts`` column and takes no provider
  step there (vault-charge.md section 5).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from urllib.parse import urlencode
from uuid import UUID, uuid4

from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.config import SANDBOX_CHECKOUT_HOST, assert_sandbox_host
from fairpool.db.models.identity import OAuthState, PayPalLink
from fairpool.domain.errors import ApplicationError
from fairpool.domain.paypal_identity import PayPalIdentityDeclined, PayPalIdentityUnavailable
from fairpool.modules.identity.service import Principal
from fairpool.ports import AuditLog, Clock, PayPalIdentity

logger = logging.getLogger("fairpool.identity.paypal_login")

#: S1: scope ``openid`` only. The account-attributes scope returned
#: ``invalid_scope`` for this app, so nothing here asks for it.
LOGIN_SCOPE: Final[str] = "openid"
#: PayPal's Login authorization endpoint, on the Sandbox checkout host only
#: (FR-PP-06). Phase 3 never fetches this URL; the Phase 4 client re-reads
#: PayPal's Login documentation before it does.
LOGIN_AUTHORIZE_PATH: Final[str] = "/connect"

#: An entry that still occupies the buyer's place (state-machines.md: WITHDRAWN
#: and REJECTED are terminal for the buyer, everything else is participation).
_PARTICIPATING_ENTRY_STATUSES: Final[tuple[str, ...]] = ("SUBMITTED", "ELIGIBLE")

#: The only two constraint names a link insert may swallow (db-schema.md).
_LINK_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {"uq_paypal_links_user_active", "uq_paypal_links_account_active"}
)


class ProviderDeclined(Exception):
    """A decline the buyer must see as a ``400``: no row is written (api.md)."""


def account_key(hmac_key: str, identifier: str) -> str:
    """BD-12: the stored shape of a PayPal account identifier, never the identifier.

    The checkout lane derives the payer-key half of ``two_keys`` the same way from
    an approved order's ``payer_id``; no prefix is ever stripped from either side.
    """
    return hmac.new(hmac_key.encode(), identifier.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class LinkDisclosure:
    """What a ``DEDUPE_MODE`` proves and what it does not (FR-ID-02, I13)."""

    mode: str
    summary: str
    proves: str
    does_not_prove: str


_DISCLOSURES: Final[dict[str, LinkDisclosure]] = {
    "two_keys": LinkDisclosure(
        mode="two_keys",
        summary=(
            "Logging in with PayPal stores one keyed reference to that PayPal "
            "account. The PayPal account you pay with at checkout is kept as a "
            "separate reference."
        ),
        proves="One entry per linked PayPal account per pool, checked on its own.",
        does_not_prove=(
            "It does not prove one human per account, it does not show that the "
            "login account and the checkout payer account are the same person or "
            "different people, and it is not complete anti-scalper protection."
        ),
    ),
    "checkout_only": LinkDisclosure(
        mode="checkout_only",
        summary=(
            "FairPool stores no PayPal Login account for you. Duplicate control "
            "uses only the payer account on an approved PayPal order."
        ),
        proves="One entry per checkout payer account per pool.",
        does_not_prove=(
            "It proves nothing about login accounts, does not prove one human per "
            "account, and is the weakest of the three duplicate-control settings."
        ),
    ),
    "full": LinkDisclosure(
        mode="full",
        summary=(
            "Would require the PayPal Login account and the checkout payer account "
            "to be the same identifier before a second entry is refused."
        ),
        proves=(
            "Nothing in this build: S1 did not prove the two identifiers are "
            "comparable, so the mode is unavailable (OD-P3-4)."
        ),
        does_not_prove=("Even with equal identifiers it would not prove one human per account."),
    ),
}


def disclosure(mode: str) -> LinkDisclosure:
    """The disclosure text for one ``DEDUPE_MODE`` value."""
    found = _DISCLOSURES.get(mode)
    if found is None:  # pragma: no cover - Settings admits only the three values
        raise ApplicationError("INTERNAL_ERROR")
    return found


@dataclass(frozen=True)
class LoginStart:
    """The only thing ``start`` returns: the authorize URL, which carries the state."""

    authorize_url: str


@dataclass(frozen=True)
class LinkResult:
    """The callback's outcome: whether a login key now exists, and under which mode."""

    linked: bool
    mode: str
    disclosure: LinkDisclosure


@dataclass(frozen=True)
class UnlinkResult:
    """Whether an active link was revoked. Never a vault statement (rule 27)."""

    revoked: bool


def _is_link_constraint(exc: IntegrityError) -> bool:
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) != "23505":
        return False
    name = getattr(orig, "constraint_name", None)
    if name is None:
        # asyncpg on this platform exposes only the message text (as in join.py).
        match = re.search(r'unique constraint "([^"]+)"', str(orig))
        name = match.group(1) if match else ""
    return str(name) in _LINK_CONSTRAINTS


class PayPalLoginService:
    """State, exchange, keyed link and revocation for Log in with PayPal."""

    def __init__(
        self,
        identity: PayPalIdentity,
        clock: Clock,
        audit: AuditLog,
        *,
        hmac_key: str,
        dedupe_mode: str,
        enabled: bool,
        client_id: str,
        redirect_uri: str,
        checkout_base: str,
        state_ttl_s: int,
    ) -> None:
        self.identity = identity
        self.clock = clock
        self.audit = audit
        self.hmac_key = hmac_key
        self.dedupe_mode = dedupe_mode
        self.enabled = enabled
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.checkout_base = checkout_base
        self.state_ttl_s = state_ttl_s

    # ------------------------------------------------------------------ gates

    def _require_available(self) -> None:
        if not self.enabled:
            # rule 19: the feature is off, so no row and no URL exist to be told about.
            raise ApplicationError("FEATURE_DISABLED")
        if self.dedupe_mode == "full":
            # OD-P3-4: `full` is the equality requirement on top of `two_keys`, and
            # equivalence was never proved (S1). Refused here rather than quietly
            # behaving like `two_keys`; the mode stays unreachable until a checkout
            # payer identifier exists at link time to compare against.
            raise ApplicationError("FEATURE_DISABLED")

    # ------------------------------------------------------------------ start

    async def start(self, session: AsyncSession, principal: Principal) -> LoginStart:
        """Write one single-use ``oauth_states`` row and return the authorize URL."""
        self._require_available()
        # FR-PP-06: the URL may point at nothing but the Sandbox checkout host.
        assert_sandbox_host(self.checkout_base, SANDBOX_CHECKOUT_HOST)

        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        # I15: the lifetime is the database clock's, not this process's.
        expires_at = await self.clock.db_now(session) + timedelta(seconds=self.state_ttl_s)
        session.add(
            OAuthState(
                state=state,
                # 7a: the nonce binds this row to this callback. It is not presented
                # as ID-token freshness proof, because S1 verified userinfo only.
                nonce=nonce,
                user_id=principal.user_id,
                # CR-3: the initiating session, so a callback cannot land in another one.
                session_id=principal.session_id,
                expires_at=expires_at,
            )
        )
        await session.flush()
        # The URL carries the state and the client id: it is never a log line (rule 2).
        logger.info("paypal login started")
        return LoginStart(authorize_url=self._authorize_url(state, nonce))

    def _authorize_url(self, state: str, nonce: str) -> str:
        query = urlencode(
            {
                "flowEntry": "static",
                "response_type": "code",
                "client_id": self.client_id,
                "scope": LOGIN_SCOPE,
                "redirect_uri": self.redirect_uri,
                "state": state,
                # spikes.md S1 step 2 built the request with a state and a nonce; 7a
                # states what the stored nonce does and does not prove.
                "nonce": nonce,
            }
        )
        return f"{self.checkout_base}{LOGIN_AUTHORIZE_PATH}?{query}"

    # --------------------------------------------------------------- callback

    async def complete(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        code: str | None,
        state: str | None,
        provider_error: str | None,
    ) -> LinkResult:
        """Run the rejection ladder, then exchange, key and link.

        One savepoint, so a planned refusal writes nothing at all: not the
        consumed flag, not the link, not the audit row (api.md "Account link").
        """
        async with session.begin_nested():
            return await self._complete_inner(
                session,
                principal,
                code=code,
                state=state,
                provider_error=provider_error,
            )

    async def _complete_inner(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        code: str | None,
        state: str | None,
        provider_error: str | None,
    ) -> LinkResult:
        self._require_available()

        if provider_error:
            # api.md: a provider decline is a 400 and writes nothing: the state row
            # stays unconsumed so the buyer can start a fresh flow.
            raise ProviderDeclined

        if not state or not code:
            raise ApplicationError("VALIDATION_ERROR")

        now = await self.clock.db_now(session)
        row = (
            await session.execute(
                select(OAuthState).where(OAuthState.state == state).with_for_update()
            )
        ).scalar_one_or_none()
        # The ladder, in contract order. Every rung refuses before any provider call.
        if row is None or not hmac.compare_digest(row.state, state):
            raise ApplicationError("FORBIDDEN")
        if row.expires_at <= now:
            raise ApplicationError("FORBIDDEN")
        if row.consumed_at is not None:
            # A consumed row is never reused, so a replay cannot relink (CR-3).
            raise ApplicationError("FORBIDDEN")
        if row.user_id != principal.user_id or row.session_id != principal.session_id:
            # Bound to another session or another buyer: never authority here.
            raise ApplicationError("FORBIDDEN")

        consumed = await session.scalar(
            update(OAuthState)
            .where(OAuthState.state == state, OAuthState.consumed_at.is_(None))
            .values(consumed_at=now)
            .returning(OAuthState.state)
        )
        if consumed is None:
            # Lost the race for this row: exactly one callback may exchange (I9).
            raise ApplicationError("FORBIDDEN")

        try:
            tokens = await self.identity.exchange_code(code)
            profile = await self.identity.userinfo(tokens.access_token)
        except PayPalIdentityDeclined as exc:
            raise ProviderDeclined from exc
        except PayPalIdentityUnavailable as exc:
            # The transaction rolls back with the request, so the failed exchange
            # leaves the row unconsumed and the buyer can start again.
            raise ApplicationError("PAYPAL_UNAVAILABLE") from exc

        # Only the keyed digest survives this line; the raw identifier is dropped.
        key = account_key(self.hmac_key, profile.account_id)
        await self._lock_user(session, principal.user_id)

        if self.dedupe_mode == "checkout_only":
            # The weaker setting stores no login key at all (decisions.md section 4).
            await self._audit_link(
                session, principal, action="paypal.link", link_id=None, stored=False
            )
            return LinkResult(
                linked=False, mode="checkout_only", disclosure=disclosure("checkout_only")
            )

        existing = await session.scalar(
            select(PayPalLink.id).where(
                PayPalLink.user_id == principal.user_id, PayPalLink.revoked_at.is_(None)
            )
        )
        if existing is not None:
            # One active link per user: a second link attempt is a conflict, not an update.
            raise ApplicationError("PAYPAL_LINK_CONFLICT")

        link_id = uuid4()
        try:
            async with session.begin_nested():
                session.add(
                    PayPalLink(
                        id=link_id,
                        user_id=principal.user_id,
                        paypal_account_key=key,
                        linked_at=now,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            if not _is_link_constraint(exc):
                raise ApplicationError("INTERNAL_ERROR") from None
            # Either this user already linked in a racing callback, or another user
            # holds this account key: both are PAYPAL_LINK_CONFLICT (config-and-errors 4).
            raise ApplicationError("PAYPAL_LINK_CONFLICT") from None

        await self._audit_link(
            session, principal, action="paypal.link", link_id=link_id, stored=True
        )
        return LinkResult(
            linked=True, mode=self.dedupe_mode, disclosure=disclosure(self.dedupe_mode)
        )

    # ----------------------------------------------------------------- unlink

    async def unlink(self, session: AsyncSession, principal: Principal) -> UnlinkResult:
        """Revoke the active link, refused while the buyer still holds an entry."""
        async with session.begin_nested():
            return await self._unlink_inner(session, principal)

    async def _unlink_inner(self, session: AsyncSession, principal: Principal) -> UnlinkResult:
        self._require_available()
        await self._lock_user(session, principal.user_id)

        placeholders = ", ".join(f":s{i}" for i in range(len(_PARTICIPATING_ENTRY_STATUSES)))
        still_participating = await session.scalar(
            text(
                f"SELECT 1 FROM pool_entries WHERE user_id = :user "
                f"AND status::text IN ({placeholders}) LIMIT 1"
            ),
            {
                "user": principal.user_id,
                **{f"s{i}": status for i, status in enumerate(_PARTICIPATING_ENTRY_STATUSES)},
            },
        )
        if still_participating is not None:
            # F16: revoking the link while an entry stands would free the
            # (pool_id, paypal_account_key) slot that entry occupies, so relinking
            # could evade participation. The entry machine has no edge that lets a
            # revoked link keep a seat (state-machines.md ES-01/ES-02).
            raise ApplicationError("PAYPAL_LINK_CONFLICT")

        now = await self.clock.db_now(session)
        revoked = await session.scalar(
            update(PayPalLink)
            .where(PayPalLink.user_id == principal.user_id, PayPalLink.revoked_at.is_(None))
            .values(revoked_at=now)
            .returning(PayPalLink.id)
        )
        # Idempotent for the client: no active link is not an error, and nothing in
        # a saved vault permission is touched either way (rule 27).
        await self._audit_link(
            session,
            principal,
            action="paypal.unlink",
            link_id=revoked if isinstance(revoked, UUID) else None,
            stored=False,
        )
        return UnlinkResult(revoked=revoked is not None)

    # ---------------------------------------------------------------- helpers

    async def _lock_user(self, session: AsyncSession, user_id: UUID) -> None:
        # api.md "Account link": link, unlink and join take this same lock first,
        # then the pool lock (join.py), so the three serialise on the user row.
        await session.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id}
        )

    async def _audit_link(
        self,
        session: AsyncSession,
        principal: Principal,
        *,
        action: str,
        link_id: UUID | None,
        stored: bool,
    ) -> None:
        # No account key, identifier, code or token in an audit payload (7a, rule 27).
        await self.audit.append(
            session,
            actor=str(principal.user_id),
            action=action,
            subject_type="paypal_link",
            subject_id=str(link_id) if link_id is not None else None,
            payload={"dedupe_mode": self.dedupe_mode, "stored_key": stored},
        )
