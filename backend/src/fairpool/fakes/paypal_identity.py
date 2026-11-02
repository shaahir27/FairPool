"""Deterministic in-memory ``PayPalIdentity`` for tests and simulation (T03B03).

This fake is the whole Phase 3 identity path: it builds no HTTP client, holds no
credentials, calls no host and issues no real token, so the link flow can be proven
end to end without PayPal being reachable (``AGENTS.md`` rules 14 and 22,
``paypal-adapter.md`` section 7a). The real ``POST /v1/oauth/token`` and
``GET /v1/identity/openidconnect/userinfo`` client belongs in ``adapters/paypal/``
and is a Phase 4 edit; S1 proved those two calls by hand in the Sandbox.

Codes, tokens and identifiers here are local fixture strings. ``calls`` records
step names only, never an argument, so a test log can never carry a code or a
bearer token; the token map is ``repr=False`` for the same reason.

Scriptable through ``failure``:

* ``none``: every issued code exchanges and profiles;
* ``declined``: the provider refuses (an unknown or refused grant) - nothing links;
* ``unavailable``: the provider call fails after retries - nothing links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from fairpool.modules.identity.paypal_login import (
    PayPalIdentityDeclined,
    PayPalIdentityUnavailable,
)
from fairpool.ports import ProviderProfile, ProviderTokens

#: Local fixture identifiers. S1 recorded that userinfo carries ``sub`` and
#: ``user_id`` and that the raw ``user_id`` is not the checkout ``payer_id``; the
#: port exposes exactly one identifier, so a test names the account it stands for.
FAKE_ALICE = "FAKE-LOGIN-ACCOUNT-ALICE"
FAKE_BOB = "FAKE-LOGIN-ACCOUNT-BOB"

#: ``carol`` shares Alice's provider account: the pair proves the one-account-one-
#: user rule (FR-ID-03) without any network.
DEFAULT_ACCOUNTS: Final[dict[str, str]] = {
    "fake-code-alice": FAKE_ALICE,
    "fake-code-bob": FAKE_BOB,
    "fake-code-carol": FAKE_ALICE,
}

Failure = Literal["none", "declined", "unavailable"]


@dataclass
class FakePayPalIdentity:
    """``PayPalIdentity`` with no session, no database write and no network."""

    accounts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ACCOUNTS))
    failure: Failure = "none"
    #: Step names in call order, with no argument values (rule 2).
    calls: list[str] = field(default_factory=list)
    _tokens: dict[str, str] = field(default_factory=dict, repr=False)

    async def exchange_code(self, code: str) -> ProviderTokens:
        self.calls.append("exchange_code")
        if self.failure == "unavailable":
            raise PayPalIdentityUnavailable
        account_id = self.accounts.get(code)
        if self.failure == "declined" or account_id is None:
            # A code this fake never issued profiles nothing, exactly as the
            # real exchange rejects an unknown or spent grant.
            raise PayPalIdentityDeclined
        access_token = f"fake-access-token-{len(self._tokens) + 1}"
        self._tokens[access_token] = account_id
        return ProviderTokens(access_token=access_token, expires_in=3600)

    async def userinfo(self, access_token: str, id_token: str | None = None) -> ProviderProfile:
        del id_token  # the fake has no ID token; the port allows one (CR-6).
        self.calls.append("userinfo")
        if self.failure == "unavailable":
            raise PayPalIdentityUnavailable
        account_id = self._tokens.get(access_token)
        if self.failure == "declined" or account_id is None:
            raise PayPalIdentityDeclined
        return ProviderProfile(account_id=account_id)
