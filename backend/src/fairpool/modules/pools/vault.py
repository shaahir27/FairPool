"""The vault permission lifecycle: consent, save, ACTIVE, quarantine, delete.

Contract: ``vault-charge.md`` sections 2, 4 and 5, ``domain-ports.md`` section 4.4,
CR-3 note 3, ``DEP-5``. CR-3 fixes the order in time and nothing here may collapse
it: ``manual confirmation -> SUBMITTED entry and receipt -> explicit consent and
save -> ACTIVE permission -> close-time eligibility``.

Rules this module implements:

* one ``vault_setup_attempts`` row owns the operation identity (the setup key
  ``vs:{entry_id}:{attempt}`` and the exchange key of the same attempt); reopening
  an attempt whose outcome is unknown reuses **that row and that identity**, and a
  genuinely new attempt is a new row with the previous one ``FAILED``, never
  silently replaced;
* the browser callback carries a token id and is never authority for anything
  else: the server matches its own live, unexpired, unconsumed attempt for the
  caller's own entry, fences it once with a conditional ``UPDATE`` so two callbacks
  cannot both exchange, and exchanges the setup identifier it stored itself;
* a token that arrives after the entry withdrew or after the pool closed is
  ``QUARANTINED`` and deleted at the provider: it is never copied into
  ``vault_tokens`` and never activated;
* the payment token id is a credential (rule 27): stored only encrypted with
  ``VAULT_TOKEN_KEY`` and a per-row nonce, and never written to a response body, a
  log record, an audit payload, a notification or a search document. Buyers see
  ``token_label``, the last four characters;
* deleting a permission deletes the provider resource first and only then clears
  the ciphertext columns, and a provider 404 counts as deleted;
* no provider call runs while a pool or entry lock is held: the vault paths read
  ``pools`` and ``pool_entries`` with no ``FOR UPDATE`` and fence only their own
  attempt row, so ``pool.close`` never waits behind a provider round trip;
* with ``VAULT_REAL_SAVE_ENABLED=false`` (the Phase 3 default) ``start`` refuses
  with ``FEATURE_DISABLED`` and writes nothing, so a consented-but-unsaved
  permission cannot exist; ``ACTIVE`` is reachable only through the injected
  ``FakePaymentVaultProvider`` that tests and simulation use (DEP-5).

This module imports nothing from ``fairpool.adapters.paypal`` and no HTTP client:
the provider arrives as ``PaymentVaultProvider`` (I2, I12). The cipher is injected
for the same reason Member B must not import ``fairpool.infra`` (scaffold section 5
rule 5): the composition root supplies ``fairpool.infra.crypto.AesGcmCipher``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.catalog import PoolEntry
from fairpool.db.models.enums import EntryStatus, PoolStatus, VaultSetupStatus, VaultStatus
from fairpool.db.models.identity import VaultSetupAttempt, VaultToken
from fairpool.domain.errors import ApplicationError
from fairpool.domain.hashing import sha256_hex
from fairpool.domain.money import to_paypal_string
from fairpool.ports import AuditLog, Clock, PaymentVaultProvider, SetupRedirect, VaultPermission

#: ``VAULT_CONSENT_VERSION`` values this build can render and hash
#: (vault-charge.md §6). Changing a wording needs a new version, never an edit.
CONSENT_TEXTS: Final[dict[str, str]] = {
    "v1": (
        "FairPool will charge this PayPal account once for this pool, for the final "
        "delivered price of the winning offer, only if it is at or below your maximum "
        "of ${cap}. PayPal's approval screen will not show the amount. FairPool, not "
        "PayPal, enforces your maximum. You can withdraw before the pool closes. "
        "Nothing is charged if you are not selected. Refunds follow the pool rules."
    ),
}

#: Buyers see only the last four characters of a token (vault-charge.md §5).
LABEL_LENGTH: Final[int] = 4


class TokenCipher(Protocol):
    """The at-rest cipher handed to the vault service (``infra.crypto.AesGcmCipher``).

    ``seal`` returns ``(nonce, ciphertext)`` with a fresh nonce per row; ``open``
    reverses it. Neither may log the plaintext (I14).
    """

    def seal(self, plaintext: str) -> tuple[bytes, bytes]: ...

    def open(self, nonce: bytes, ciphertext: bytes) -> str: ...


class VaultProviderError(Exception):
    """A provider step failed. Carries a code only: never a payload, never a token."""

    code: str = "UNKNOWN"


class VaultProviderDeclined(VaultProviderError):
    """Definitive refusal: the permission will not exist (vault-charge.md §7)."""

    code: str = "INSTRUMENT_DECLINED"


class VaultProviderUnknown(VaultProviderError):
    """Outcome unknown: the identity stays reserved and is replayed, not replaced."""

    code: str = "UNKNOWN"


class VaultProviderUnavailable(VaultProviderError):
    """Unreachable provider: no local state may claim the step happened."""

    code: str = "PAYPAL_UNAVAILABLE"


def render_consent_text(version: str, cap_cents: int) -> str:
    """The exact text a buyer accepted, with their own cap stated (FR-IN-05)."""
    template = CONSENT_TEXTS.get(version)
    if template is None:
        # A version this build does not know is not the wording the buyer saw.
        raise ApplicationError("VALIDATION_ERROR")
    return template.format(cap=to_paypal_string(cap_cents))


def consent_text_sha256(version: str, cap_cents: int) -> str:
    """SHA-256 of the exact rendered consent text (``consent_text_sha256``)."""
    return sha256_hex(render_consent_text(version, cap_cents).encode("utf-8"))


def label_of(payment_token_id: str) -> str:
    """The only form a token id may leave this module: its last four characters."""
    return payment_token_id[-LABEL_LENGTH:]


async def has_active_permission(session: AsyncSession, *, entry_id: UUID, cap_cents: int) -> bool:
    """Close-time eligibility test (CR-3 note 3): recorded consent and ACTIVE.

    Mirrors the charge precheck (BO-27) so a buyer is never told they are eligible
    for something that could not be charged. A permission whose stored cap is not
    the entry's cap is not the permission this buyer consented to, so it fails
    closed.
    """
    row = (
        await session.execute(
            select(
                VaultToken.status,
                VaultToken.consent_version,
                VaultToken.consent_text_sha256,
                VaultToken.cap_cents,
            )
            .where(VaultToken.entry_id == entry_id, VaultToken.deleted_at.is_(None))
            .order_by(VaultToken.created_at.desc(), VaultToken.id)
            .limit(1)
        )
    ).first()
    if row is None:
        return False
    status, consent_version, consent_hash, token_cap = row
    if str(status) != str(VaultStatus.ACTIVE):
        return False
    if not consent_version or not consent_hash:
        return False
    return bool(token_cap == cap_cents)


class VaultService:
    """``PaymentVault``: owns the ``vault_setup_attempts`` and ``vault_tokens`` rows."""

    def __init__(
        self,
        clock: Clock,
        audit: AuditLog,
        cipher: TokenCipher,
        provider: PaymentVaultProvider,
        *,
        consent_version: str,
        setup_ttl_s: int,
        real_save_enabled: bool,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.cipher = cipher
        self.provider = provider
        self.consent_version = consent_version
        self.setup_ttl_s = setup_ttl_s
        self.real_save_enabled = real_save_enabled

    # -------------------------------------------------------------- reads

    async def _entry(self, session: AsyncSession, entry_id: UUID) -> PoolEntry:
        # Owner scoping is the router's job (it fetches by id AND user_id, so
        # another buyer's entry answers 404). Read with no lock: provider I/O must
        # never sit behind an entry lock, and no vault step changes an entry row.
        entry = await session.scalar(select(PoolEntry).where(PoolEntry.id == entry_id))
        if entry is None:
            raise ApplicationError("NOT_FOUND")
        return entry

    async def _live_attempt(
        self, session: AsyncSession, entry_id: UUID, wall_now: datetime
    ) -> VaultSetupAttempt | None:
        return await session.scalar(
            select(VaultSetupAttempt)
            .where(
                VaultSetupAttempt.entry_id == entry_id,
                VaultSetupAttempt.status == VaultSetupStatus.PENDING,
                VaultSetupAttempt.consumed_at.is_(None),
                VaultSetupAttempt.expires_at > wall_now,
            )
            .order_by(VaultSetupAttempt.created_at.desc(), VaultSetupAttempt.id)
            .limit(1)
        )

    async def _latest_attempt(
        self, session: AsyncSession, entry_id: UUID
    ) -> VaultSetupAttempt | None:
        return await session.scalar(
            select(VaultSetupAttempt)
            .where(VaultSetupAttempt.entry_id == entry_id)
            .order_by(VaultSetupAttempt.created_at.desc(), VaultSetupAttempt.id)
            .limit(1)
        )

    async def _token(self, session: AsyncSession, entry_id: UUID) -> VaultToken | None:
        """The entry's live permission row, if one has been recorded (one per entry)."""
        return await session.scalar(
            select(VaultToken)
            .where(VaultToken.entry_id == entry_id, VaultToken.deleted_at.is_(None))
            .order_by(VaultToken.created_at.desc(), VaultToken.id)
            .limit(1)
        )

    async def _latest_token(self, session: AsyncSession, entry_id: UUID) -> VaultToken | None:
        return await session.scalar(
            select(VaultToken)
            .where(VaultToken.entry_id == entry_id)
            .order_by(VaultToken.created_at.desc(), VaultToken.id)
            .limit(1)
        )

    async def _pool_state(self, session: AsyncSession, pool_id: UUID) -> tuple[str, str | None]:
        row = (
            await session.execute(
                text("SELECT status, timeline->>'close_at' FROM pools WHERE id = :id"),
                {"id": pool_id},
            )
        ).first()
        if row is None:
            raise ApplicationError("INTEGRITY_ERROR")
        return str(row[0]), row[1]

    async def _closed(self, session: AsyncSession, pool_id: UUID, wall_now: datetime) -> bool:
        """True once the pool left OPEN or passed ``close_at`` (both quarantine a save)."""
        status, close_at = await self._pool_state(session, pool_id)
        if status != str(PoolStatus.OPEN) or close_at is None:
            return True
        return wall_now >= datetime.fromisoformat(str(close_at).replace("Z", "+00:00"))

    # ------------------------------------------------------------------ start

    async def start(self, session: AsyncSession, *, entry_id: UUID) -> SetupRedirect:
        """Record the consent and the attempt row, then ask the provider for approval."""
        if not self.real_save_enabled:
            # DEP-5: a consented-but-unsaved permission must not be able to exist,
            # so this refuses before it writes anything (no half-state).
            raise ApplicationError("FEATURE_DISABLED")
        entry = await self._entry(session, entry_id)
        if str(entry.status) != str(EntryStatus.SUBMITTED):
            # A withdrawn, eligible or rejected entry cannot start a save.
            raise ApplicationError("ORDER_STATE_INVALID")

        now = await self.clock.db_now(session)
        wall_now = await self.clock.db_wall_now(session)

        # CR-3: an expired, unconsumed attempt becomes FAILED and is reported as
        # VAULT_SETUP_EXPIRED, so the next start creates a new row and a new
        # identity rather than reusing a dead one.
        expired = await session.scalar(
            text(
                "UPDATE vault_setup_attempts SET status = 'FAILED'::vault_setup_status, "
                "last_error = 'VAULT_SETUP_EXPIRED' WHERE entry_id = :entry "
                "AND status = 'PENDING'::vault_setup_status AND consumed_at IS NULL "
                "AND expires_at <= :wall RETURNING id"
            ),
            {"entry": entry_id, "wall": wall_now},
        )
        if expired is not None:
            raise ApplicationError("VAULT_SETUP_EXPIRED")

        pending_consumed = await session.scalar(
            select(VaultSetupAttempt)
            .where(
                VaultSetupAttempt.entry_id == entry_id,
                VaultSetupAttempt.status == VaultSetupStatus.PENDING,
                VaultSetupAttempt.consumed_at.is_not(None),
            )
            .order_by(VaultSetupAttempt.created_at.desc(), VaultSetupAttempt.id)
            .limit(1)
        )
        if pending_consumed is not None:
            # The exchange outcome is unknown: that identity stays reserved and no
            # second provider operation is invented while it is unresolved.
            raise ApplicationError("PAYPAL_UNAVAILABLE")

        attempt = await self._live_attempt(session, entry_id, wall_now)
        if attempt is None:
            previous = await session.scalar(
                select(func.count())
                .select_from(VaultSetupAttempt)
                .where(VaultSetupAttempt.entry_id == entry_id)
            )
            attempt = VaultSetupAttempt(
                id=uuid4(),
                entry_id=entry_id,
                # This row owns the identity of both provider steps for the attempt.
                operation_key=f"vs:{entry_id}:{int(previous or 0) + 1}",
                status=VaultSetupStatus.PENDING,
                expires_at=now + timedelta(seconds=self.setup_ttl_s),
            )
            session.add(attempt)
            await session.flush()

        await self._record_consent(session, entry=entry, now=now)

        try:
            redirect = await self.provider.start_setup(entry_id)
        except VaultProviderDeclined:
            attempt.status = VaultSetupStatus.FAILED
            attempt.last_error = VaultProviderDeclined.code
            await session.flush()
            await self._audit(session, entry=entry, action="vault.setup_declined")
            raise ApplicationError("VAULT_REQUIRED") from None
        except VaultProviderError as exc:
            # Stay PENDING with the same identity: a reopen reuses this row (CR-3).
            attempt.last_error = exc.code or VaultProviderUnknown.code
            await session.flush()
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None

        # The provider setup identifier is a credential too: encrypted at rest,
        # never returned to a client (the response carries the approve URL only).
        nonce, ciphertext = self.cipher.seal(redirect.setup_token_id)
        attempt.provider_setup_nonce = nonce
        attempt.provider_setup_ciphertext = ciphertext
        await session.flush()
        await self._audit(session, entry=entry, action="vault.setup_started")
        return redirect

    async def _record_consent(
        self, session: AsyncSession, *, entry: PoolEntry, now: datetime
    ) -> None:
        """Store the consent the buyer gave: version, text hash, cap, time (pool via entry).

        The cap is the entry's own frozen cap, never a client value: the confirmed
        request and the receipt may not move after the fact (CR-3).
        """
        existing = await self._token(session, entry.id)
        if existing is not None:
            if str(existing.status) == str(VaultStatus.ACTIVE):
                # A permission that already exists is not saved twice.
                raise ApplicationError("ORDER_STATE_INVALID")
            return
        session.add(
            VaultToken(
                id=uuid4(),
                entry_id=entry.id,
                user_id=entry.user_id,
                status=VaultStatus.SETUP_PENDING,
                cap_cents=entry.cap_cents,
                consent_version=self.consent_version,
                consent_text_sha256=consent_text_sha256(self.consent_version, entry.cap_cents),
                consented_at=now,
            )
        )
        await session.flush()

    # ------------------------------------------------------ return and exchange

    async def complete(
        self, session: AsyncSession, *, entry_id: UUID, setup_token_id: str
    ) -> VaultPermission:
        """Fence the caller's own attempt once, then exchange it for a permission.

        ``setup_token_id`` comes from an untrusted redirect and is only ever
        *compared* with the value this server stored: the exchange uses the stored
        one, so a query string is never authority for anything (api.md "Entry").
        """
        entry = await self._entry(session, entry_id)
        now = await self.clock.db_now(session)
        wall_now = await self.clock.db_wall_now(session)

        attempt = await self._latest_attempt(session, entry_id)
        if attempt is None:
            # Nothing of ours is waiting: the redirect authorises no exchange.
            raise ApplicationError("NOT_FOUND")
        if attempt.status == VaultSetupStatus.EXCHANGED:
            return await self.status(session, entry_id=entry_id)
        if attempt.consumed_at is not None:
            # Consumed once already: a replay of the callback, never a second
            # exchange, whether it ended EXCHANGED, QUARANTINED or unknown.
            return await self.status(session, entry_id=entry_id)
        if attempt.status != VaultSetupStatus.PENDING:
            raise ApplicationError("VAULT_SETUP_EXPIRED")
        if attempt.expires_at <= wall_now:
            # A dead attempt is refused before any of its credentials are read:
            # it never exchanges, and it is kept as FAILED rather than replaced.
            attempt.status = VaultSetupStatus.FAILED
            attempt.last_error = "VAULT_SETUP_EXPIRED"
            await session.flush()
            raise ApplicationError("VAULT_SETUP_EXPIRED")
        if attempt.provider_setup_ciphertext is None or attempt.provider_setup_nonce is None:
            raise ApplicationError("INTEGRITY_ERROR")
        if await self._closed(session, entry.pool_id, wall_now) or str(entry.status) != str(
            EntryStatus.SUBMITTED
        ):
            # QUARANTINED: written as quarantined, deleted at the provider, and
            # never copied into vault_tokens nor activated (CR-3).
            attempt.status = VaultSetupStatus.QUARANTINED
            attempt.consumed_at = now
            await self._clear_permission(session, entry=entry, now=now)
            await session.flush()
            await self._audit(session, entry=entry, action="vault.quarantined")
            stored_setup = self.cipher.open(
                attempt.provider_setup_nonce, attempt.provider_setup_ciphertext
            )
            await self._provider_delete(stored_setup)
            return VaultPermission(entry_id, str(VaultStatus.DELETED), None)

        stored = self.cipher.open(attempt.provider_setup_nonce, attempt.provider_setup_ciphertext)
        if setup_token_id and setup_token_id != stored:
            raise ApplicationError("VALIDATION_ERROR")

        # The fence: a conditional single-row update. Only this attempt row is
        # locked, and a second callback's statement matches no row, so exactly one
        # exchange runs. No pool or entry lock exists at this point.
        fenced = await session.scalar(
            text(
                "UPDATE vault_setup_attempts SET consumed_at = :at WHERE id = :id "
                "AND consumed_at IS NULL RETURNING id"
            ),
            {"at": now, "id": attempt.id},
        )
        if fenced is None:
            return await self.status(session, entry_id=entry_id)

        try:
            permission = await self.provider.exchange(entry_id, stored)
        except VaultProviderDeclined:
            attempt.status = VaultSetupStatus.FAILED
            attempt.last_error = VaultProviderDeclined.code
            await self._fail_permission(session, entry_id=entry_id, now=now)
            await session.flush()
            await self._audit(session, entry=entry, action="vault.save_declined")
            raise ApplicationError("VAULT_REQUIRED") from None
        except VaultProviderError as exc:
            # Unknown outcome: the row stays consumed and PENDING so the identity
            # is never replaced, and no permission is claimed locally (I9).
            attempt.last_error = exc.code or VaultProviderUnknown.code
            await session.flush()
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None

        token = await self._token(session, entry_id)
        if token is None:
            raise ApplicationError("INTEGRITY_ERROR")
        nonce, ciphertext = self.cipher.seal(permission.payment_token_id)
        token.status = VaultStatus.ACTIVE
        token.token_nonce = nonce
        token.token_ciphertext = ciphertext
        token.token_label = label_of(permission.payment_token_id)
        attempt.status = VaultSetupStatus.EXCHANGED
        await session.flush()
        # Only the four-character label travels in the audit payload (rule 27).
        await self._audit(
            session,
            entry=entry,
            action="vault.saved",
            extra={"status": str(VaultStatus.ACTIVE), "label": token.token_label},
        )
        return VaultPermission(entry_id, str(token.status), token.token_label)

    # ---------------------------------------------------------------- delete

    async def withdraw(self, session: AsyncSession, *, entry_id: UUID) -> VaultPermission:
        """Delete the saved permission: provider first, columns after; idempotent."""
        entry = await self._entry(session, entry_id)
        now = await self.clock.db_now(session)
        token = await self._token(session, entry_id)
        if token is None:
            # Nothing live to delete. A repeat call answers the same way, and a
            # late approval still lands in the quarantine path above.
            latest = await self._latest_token(session, entry_id)
            if latest is None:
                return VaultPermission(entry_id, str(VaultStatus.SETUP_PENDING), None)
            return VaultPermission(entry_id, str(latest.status), latest.token_label)

        if token.token_ciphertext is not None and token.token_nonce is not None:
            stored = self.cipher.open(token.token_nonce, token.token_ciphertext)
            # A provider 404 counts as deleted, so an already-gone resource returns
            # normally; only a real failure keeps the ciphertext and stops here.
            await self._provider_delete(stored)

        token.token_ciphertext = None
        token.token_nonce = None
        token.status = VaultStatus.DELETED
        token.deleted_at = now
        await session.flush()
        await self._audit(
            session,
            entry=entry,
            action="vault.deleted",
            extra={"status": str(VaultStatus.DELETED), "label": token.token_label},
        )
        return VaultPermission(entry_id, str(token.status), token.token_label)

    async def _provider_delete(self, token_id: str) -> None:
        try:
            await self.provider.delete(token_id)
        except VaultProviderDeclined:
            # The contracted 404-as-deleted outcome (domain-ports.md §4.4).
            return
        except VaultProviderError:
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None

    async def _clear_permission(
        self, session: AsyncSession, *, entry: PoolEntry, now: datetime
    ) -> None:
        """Quarantine leaves no live permission row and never a ciphertext (rule 27)."""
        token = await self._token(session, entry.id)
        if token is None:
            return
        token.status = VaultStatus.DELETED
        token.deleted_at = now
        token.token_ciphertext = None
        token.token_nonce = None

    async def _fail_permission(
        self, session: AsyncSession, *, entry_id: UUID, now: datetime
    ) -> None:
        token = await self._token(session, entry_id)
        if token is None:
            return
        token.status = VaultStatus.FAILED
        token.deleted_at = now

    # ---------------------------------------------------------------- status

    async def status(self, session: AsyncSession, *, entry_id: UUID) -> VaultPermission:
        """The permission as the product may see it: a status and a four-char label."""
        await self._entry(session, entry_id)
        token = await self._token(session, entry_id)
        if token is not None:
            return VaultPermission(entry_id, str(token.status), token.token_label)
        latest = await self._latest_token(session, entry_id)
        if latest is not None:
            return VaultPermission(entry_id, str(latest.status), latest.token_label)
        # No permission row means the saving step never completed: the documented
        # default status, never a claim of ACTIVE.
        return VaultPermission(entry_id, str(VaultStatus.SETUP_PENDING), None)

    # ----------------------------------------------------------------- audit

    async def _audit(
        self,
        session: AsyncSession,
        *,
        entry: PoolEntry,
        action: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {"pool_id": str(entry.pool_id), "entry_id": str(entry.id)}
        payload.update(extra or {})
        await self.audit.append(
            session,
            actor=str(entry.user_id),
            action=action,
            subject_type="pool_entry",
            subject_id=str(entry.id),
            payload=payload,
        )
