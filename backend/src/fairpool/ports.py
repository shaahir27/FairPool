"""Ports shared by both workstreams (contract: ``docs/contracts/domain-ports.md``).

Every database-facing method takes an ``AsyncSession`` and never commits; the
caller owns the transaction (I10). The dataclasses below are the frozen wire
shapes exchanged across port boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "AIClient",
    "AiRunLogger",
    "AllocationReadService",
    "AsyncSession",
    "AuditLog",
    "AwardView",
    "BeaconClient",
    "Clock",
    "IdemConflict",
    "IdemNew",
    "IdemReplay",
    "IdemResult",
    "IdempotencyStore",
    "IntakeProposal",
    "JobQueue",
    "Ledger",
    "LotView",
    "MerchantAuth",
    "MerchantDirectory",
    "MerchantPrincipal",
    "Notifier",
    "PayeeRef",
    "PayPalIdentity",
    "PaymentVault",
    "PaymentVaultProvider",
    "ProviderProfile",
    "ProviderTokens",
    "QuoteProposal",
    "ReconcileResult",
    "SavedPermission",
    "SearchHit",
    "SearchIndexer",
    "SearchService",
    "SeatView",
    "SetupRedirect",
    "SimilarityResult",
    "Totals",
    "VaultPermission",
]


@dataclass(frozen=True)
class IdemNew:
    """No stored response exists for this idempotency key."""


@dataclass(frozen=True)
class IdemReplay:
    """A completed response exists for this idempotency key."""

    response: dict[str, Any]


@dataclass(frozen=True)
class IdemConflict:
    """The same key was used with a different request hash."""


type IdemResult = IdemNew | IdemReplay | IdemConflict


@dataclass(frozen=True)
class SearchHit:
    doc_id: str
    doc_kind: str
    pool_id: UUID
    lot_id: UUID | None
    product_key: str
    title: str
    score: float


@dataclass(frozen=True)
class SimilarityResult:
    own_rank: int | None
    top_lot_id: UUID | None
    top_product_key: str | None


@dataclass(frozen=True)
class MerchantPrincipal:
    merchant_id: UUID
    scopes: frozenset[str]
    via: str


@dataclass(frozen=True)
class LotView:
    id: UUID
    pool_id: UUID
    zone_id: str
    lot_order: int
    seats: int
    status: str
    payment_router: str | None
    payment_mode: str | None
    fund_deadline_at: datetime | None
    refill_cutoff_at: datetime | None
    offer_window_s: int
    fund_deadline_s: int
    max_refill_waves: int
    pool_mode: str
    # CR-4: the values the checkout handlers need; defaults keep older fakes valid.
    pending_wait_s: int = 0
    capture_grace_s: int = 0
    refill_waves: int = 0


@dataclass(frozen=True)
class SeatView:
    entry_id: UUID
    user_id: UUID
    cap_cents: int
    zone_id: str
    region: str
    rank: int
    paypal_account_key: str | None


@dataclass(frozen=True)
class Totals:
    item_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int


@dataclass(frozen=True)
class AwardView:
    lot_id: UUID
    merchant_id: UUID
    item_cents: int
    moq: int
    tier_index: int
    totals: dict[UUID, Totals]
    valid_until: datetime
    award_hash: str


@dataclass(frozen=True)
class PayeeRef:
    merchant_id: UUID
    display_name: str
    payee_email: str | None
    paypal_merchant_id: str | None
    onboarding_status: str


# The AI contract defines these result shapes in ``ai-schemas.md`` but does not
# name Python fields; proposals stay as validated JSON objects until a later task
# owns their typed schema.
type IntakeProposal = dict[str, Any]
type QuoteProposal = dict[str, Any]
type ReconcileResult = dict[str, Any]


@runtime_checkable
class Clock(Protocol):
    async def db_now(self, session: AsyncSession) -> datetime: ...

    async def db_wall_now(self, session: AsyncSession) -> datetime:
        ...
        # clock_timestamp(): read AFTER a lock is held before comparing to a deadline (CR-3).


@runtime_checkable
class JobQueue(Protocol):
    async def enqueue(
        self,
        session: AsyncSession,
        kind: str,
        payload: dict[str, Any],
        *,
        run_at: datetime | None = None,
        concurrency_key: str | None = None,
        dedupe_key: str | None = None,
    ) -> UUID | None: ...


@runtime_checkable
class AuditLog(Protocol):
    async def append(
        self,
        session: AsyncSession,
        *,
        actor: str,
        action: str,
        subject_type: str,
        subject_id: str | None,
        payload: dict[str, Any],
    ) -> int: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    async def begin(
        self,
        session: AsyncSession,
        *,
        key: str,
        scope: str,
        request_hash: str,
    ) -> IdemResult: ...

    async def complete(
        self,
        session: AsyncSession,
        *,
        key: str,
        response: dict[str, Any],
    ) -> None: ...


@runtime_checkable
class Ledger(Protocol):
    async def record(
        self,
        session: AsyncSession,
        *,
        lot_id: UUID,
        buyer_order_id: UUID,
        kind: str,
        amount_cents: int,
        paypal_ref: str,
        idempotency_key: str,
        source: str,
    ) -> bool: ...

    async def net_paid_cents(self, session: AsyncSession, lot_id: UUID) -> int: ...

    async def completed_capture_count(self, session: AsyncSession, lot_id: UUID) -> int: ...


@runtime_checkable
class Notifier(Protocol):
    async def notify(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        kind: str,
        payload: dict[str, Any],
    ) -> None: ...


@runtime_checkable
class BeaconClient(Protocol):
    async def announce(self, *, close_at: datetime, delay_s: int) -> dict[str, Any]: ...

    async def fetch(self, announced: dict[str, Any]) -> dict[str, Any] | None: ...


@runtime_checkable
class AiRunLogger(Protocol):
    async def log(
        self,
        session: AsyncSession,
        *,
        task: str,
        model: str,
        prompt_version: str,
        input_hash: str,
        output: dict[str, Any] | None,
        ok: bool,
        error: str | None,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
    ) -> UUID: ...


@runtime_checkable
class AIClient(Protocol):
    async def parse_intake(
        self,
        session: AsyncSession,
        *,
        message: str,
        candidates: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> IntakeProposal: ...

    async def parse_quote(
        self,
        session: AsyncSession,
        *,
        quote_text: str,
        lot_requirement: dict[str, Any],
    ) -> QuoteProposal: ...

    async def parse_mandate(
        self,
        session: AsyncSession,
        *,
        message: str,
        proposal: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Propose a delegation mandate; the buyer ratifies it (CR-14, FR-AI-06)."""
        ...

    async def reconcile_offer(
        self,
        session: AsyncSession,
        *,
        lot_requirement: dict[str, Any],
        bid_structured: dict[str, Any],
        text: str,
    ) -> ReconcileResult: ...

    async def sim_text(
        self,
        session: AsyncSession,
        *,
        kind: str,
        facts: dict[str, Any],
    ) -> str: ...


@runtime_checkable
class SearchService(Protocol):
    async def search(
        self,
        session: AsyncSession,
        *,
        q: str,
        kinds: list[str],
        status: list[str] | None,
        limit: int,
    ) -> list[SearchHit]: ...

    async def similarity_check(
        self,
        session: AsyncSession,
        *,
        lot_id: UUID,
        text: str,
    ) -> SimilarityResult: ...


@runtime_checkable
class SearchIndexer(Protocol):
    async def upsert(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None: ...

    async def delete(self, session: AsyncSession, *, doc_kind: str, doc_id: UUID) -> None: ...


@runtime_checkable
class MerchantAuth(Protocol):
    async def from_session(self, session: AsyncSession, user_id: UUID) -> MerchantPrincipal: ...

    async def from_api_key(self, session: AsyncSession, bearer: str) -> MerchantPrincipal: ...


@runtime_checkable
class AllocationReadService(Protocol):
    async def get_lot(self, session: AsyncSession, lot_id: UUID) -> LotView: ...

    async def get_award(self, session: AsyncSession, lot_id: UUID) -> AwardView: ...

    async def list_seated(self, session: AsyncSession, lot_id: UUID) -> list[SeatView]: ...

    async def next_candidates(
        self,
        session: AsyncSession,
        lot_id: UUID,
        count: int,
    ) -> list[SeatView]: ...


@runtime_checkable
class MerchantDirectory(Protocol):
    async def get_payee(self, session: AsyncSession, merchant_id: UUID) -> PayeeRef: ...


@dataclass(frozen=True)
class SetupRedirect:
    """What a save-PayPal attempt hands the browser. The URL is never logged or audited."""

    approve_url: str
    setup_token_id: str


@dataclass(frozen=True)
class SavedPermission:
    """A provider credential. Encrypt on arrival; never log, return, audit or prompt it."""

    payment_token_id: str
    label: str


@dataclass(frozen=True)
class VaultPermission:
    """A saved permission as the rest of the product may see it: never the token."""

    entry_id: UUID
    status: str
    label: str | None


@dataclass(frozen=True)
class ProviderTokens:
    access_token: str
    expires_in: int
    #: PayPal's documented place for the profile claims of a Login grant; userinfo
    #: stays the only source of the identifier (CR-6).
    id_token: str | None = None
    #: The scope names the provider granted, never a token or grant value (CR-6).
    #: Whether ``profile email address`` came back is the difference between a parse
    #: gap and an attribute set the Sandbox app never approved.
    granted_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderProfile:
    """One identifier from the userinfo response; the raw value never reaches storage."""

    account_id: str = field(repr=False)
    details: dict[str, Any] = field(default_factory=dict, repr=False)


@runtime_checkable
class PaymentVaultProvider(Protocol):
    """The three provider steps only: takes no session, writes no row (CR-3).

    ``attempt`` is the attempt identity the vault service stores inside
    ``vault_setup_attempts.operation_key`` (the suffix of ``vs:{entry_id}:{attempt}``),
    so the key of every step of one attempt is that row's key and two attempts of one
    entry never share one (I9, ``vault-charge.md`` section 2).
    """

    async def start_setup(self, entry_id: UUID, attempt: str) -> SetupRedirect: ...

    async def exchange(
        self, entry_id: UUID, attempt: str, setup_token_id: str
    ) -> SavedPermission: ...

    async def delete(self, payment_token_id: str, attempt: str) -> None: ...


@runtime_checkable
class PaymentVault(Protocol):
    """The vault service both lanes call; it owns the attempt and token rows (CR-3).

    Provider I/O happens outside any transaction holding a pool, lot or entry
    lock. Phase 3 and simulation use the fake provider only; the real one arrives
    with T05A01 and stays refused by ``VAULT_REAL_SAVE_ENABLED`` until then.
    """

    async def start(self, session: AsyncSession, *, entry_id: UUID) -> SetupRedirect: ...

    async def complete(
        self, session: AsyncSession, *, entry_id: UUID, setup_token_id: str
    ) -> VaultPermission: ...

    async def withdraw(self, session: AsyncSession, *, entry_id: UUID) -> VaultPermission: ...

    async def status(self, session: AsyncSession, *, entry_id: UUID) -> VaultPermission: ...


@runtime_checkable
class PayPalIdentity(Protocol):
    """The two Log-in-with-PayPal reads, kept behind the adapter (CR-3, I1, I2).

    ``modules.identity`` imports this port and no HTTP client, so the import
    whitelist never has to widen for login.
    """

    async def exchange_code(self, code: str) -> ProviderTokens: ...

    async def userinfo(self, access_token: str, id_token: str | None = None) -> ProviderProfile: ...
