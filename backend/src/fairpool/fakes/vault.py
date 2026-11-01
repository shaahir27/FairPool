"""Local, inert vault provider for tests and simulation (T03B04 CR-3, DEP-5, I12).

The whole point of this fake is that it is *not* an integration: it builds no HTTP
client, holds no credentials and calls no host, so Phase 3 and every simulation run
can reach an ``ACTIVE`` permission without PayPal being reachable at all
(``AGENTS.md`` rules 14 and 22, ``domain-ports.md`` section 4.4). Approve URLs point
at the reserved ``.invalid`` domain (RFC 2606) and token ids are plain local
strings.

Calls are recorded in order so a test can prove what happened, and ``on_call`` is
awaited at the moment the fake would be waiting on a host: the vault lifecycle test
uses it to try to lock the pool and entry rows ``FOR UPDATE NOWAIT`` from another
connection, proving no provider step runs while this transaction holds those locks.

The fake is scriptable through the three provider steps:

* ``start_outcome``: ``issued`` | ``unknown`` (outcome unknown, identity reserved)
  | ``decline``;
* ``exchange_outcome``: ``active`` | ``unknown`` | ``decline``;
* ``delete_outcome``: ``deleted`` | ``not_found`` (a provider 404, which the
  contract counts as deleted) | ``unavailable`` (a real failure).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from fairpool.modules.pools.vault import (
    VaultProviderDeclined,
    VaultProviderUnavailable,
    VaultProviderUnknown,
)
from fairpool.ports import SavedPermission, SetupRedirect

StartOutcome = Literal["issued", "unknown", "decline"]
ExchangeOutcome = Literal["active", "unknown", "decline"]
DeleteOutcome = Literal["deleted", "not_found", "unavailable"]

#: Reserved by RFC 2606, so an approve URL from this fake can never be reached.
INVALID_HOST = "https://vault-token.invalid/checkout/approve/"


@dataclass
class FakePaymentVaultProvider:
    """``PaymentVaultProvider`` with no session, no database write and no network."""

    start_outcome: StartOutcome = "issued"
    exchange_outcome: ExchangeOutcome = "active"
    delete_outcome: DeleteOutcome = "deleted"
    calls: list[str] = field(default_factory=list)
    #: Provider identifiers this fake handed out. Local strings, never credentials,
    #: and never in a response body, log record, audit payload or prompt (rule 27).
    setup_tokens: dict[str, str] = field(default_factory=dict, repr=False)
    payment_tokens: dict[str, str] = field(default_factory=dict, repr=False)
    deleted_ids: list[str] = field(default_factory=list, repr=False)
    #: The ``PayPal-Request-Id`` key text each setup/exchange step would carry, in call
    #: order. A test asserts two attempts of one entry produce two of these and a retry
    #: of an unknown attempt reuses the original (I9, vault-charge.md section 2). The
    #: identifiers below stay entry-keyed: they are local inert stand-ins, while the
    #: operation key is the value the real provider reserves per attempt. The delete
    #: step is not recorded here: ``paypal-adapter.md`` section 2 keys it ``vd:{entry_id}``.
    operation_keys: list[str] = field(default_factory=list, repr=False)
    #: Awaited at the moment the fake would be waiting on a host, so a test can look
    #: at the database while a provider step is "in flight".
    on_call: Callable[[str], Awaitable[None]] | None = field(default=None, repr=False)

    async def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.on_call is not None:
            await self.on_call(name)

    async def start_setup(self, entry_id: UUID, attempt: str) -> SetupRedirect:
        await self._step(f"start_setup:{entry_id}")
        self.operation_keys.append(f"vs:{entry_id}:{attempt}")
        if self.start_outcome == "unknown":
            raise VaultProviderUnknown
        if self.start_outcome == "decline":
            raise VaultProviderDeclined
        setup_token_id = f"fake-setup-token-{entry_id}"
        self.setup_tokens[setup_token_id] = str(entry_id)
        return SetupRedirect(
            approve_url=f"{INVALID_HOST}{setup_token_id}", setup_token_id=setup_token_id
        )

    async def exchange(self, entry_id: UUID, attempt: str, setup_token_id: str) -> SavedPermission:
        await self._step(f"exchange:{entry_id}")
        self.operation_keys.append(f"vp:{entry_id}:{attempt}")
        if self.setup_tokens.get(setup_token_id) != str(entry_id):
            # A setup token this fake never issued for this entry exchanges nothing.
            raise VaultProviderUnknown
        if self.exchange_outcome == "unknown":
            raise VaultProviderUnknown
        if self.exchange_outcome == "decline":
            raise VaultProviderDeclined
        payment_token_id = f"fake-payment-token-{entry_id}"
        self.payment_tokens[payment_token_id] = str(entry_id)
        return SavedPermission(
            payment_token_id=payment_token_id,
            label=payment_token_id[-4:],
        )

    async def delete(self, payment_token_id: str, attempt: str) -> None:
        await self._step(f"delete:{payment_token_id}")
        if self.delete_outcome == "unavailable":
            raise VaultProviderUnavailable
        # ``not_found`` models PayPal's 404, which vault-charge.md §2 counts as
        # deleted, so both paths simply record and return.
        self.deleted_ids.append(payment_token_id)
