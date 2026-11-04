"""JavaScript SDK v6 configuration and the browser-safe client token (T07A01; INT-7).

``api.md`` section 4.1 fixes both shapes. The token is obtained by the adapter
(``POST /v1/oauth2/token`` with ``response_type=client_token`` and the site's
domain) and cached here until one minute before its expiry; only the token and a
remaining-seconds value leave this module, and neither is ever logged (I14).

The client-token path exists only on a public domain (S13: ``localhost`` answered
401 ``invalid_domain``), so the domain is derived from ``FRONTEND_BASE_URL`` -- the
page that loads the SDK -- and a deployment on localhost is expected to keep
``PAYPAL_SDK_AUTH=client_id``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from fairpool.adapters.paypal.routers import checkout_labels
from fairpool.config import Settings
from fairpool.domain.errors import ApplicationError
from fairpool.modules.checkout import mock_gateway

#: The SDK v6 core script on the Sandbox checkout host (INT-7).
SDK_URL: Final[str] = "https://www.sandbox.paypal.com/web-sdk/v6/core"
SDK_COMPONENTS: Final[tuple[str, ...]] = ("paypal-payments",)
#: The short label of DEP-4, shown wherever the stand-in routing applies.
FALLBACK_LABEL: Final[str] = "FALLBACK: single stand-in seller"
#: The contract caches a client token until one minute before expiry.
TOKEN_SAFETY_MARGIN_S: Final[int] = 60
#: A token fetch is one bounded call: a stuck PayPal call must not stall every buyer.
CLIENT_TOKEN_TIMEOUT_S: Final[float] = 5.0


class ClientTokenGateway(Protocol):
    """The one adapter call this module uses (``paypal-adapter.md`` section 12)."""

    async def client_token(self, domain: str) -> tuple[str, int]: ...


class SdkService:
    """``GET /checkout/config`` and ``GET /checkout/client-token`` behind one cache."""

    def __init__(
        self,
        *,
        gateway: ClientTokenGateway | None,
        client_id: str,
        sdk_auth: str,
        approval_ui: str,
        fallback: bool,
        domain: str | None,
        router: str = "",
    ) -> None:
        self.gateway = gateway
        self.client_id = client_id
        self.sdk_auth = sdk_auth
        self.approval_ui = approval_ui
        self.fallback = fallback
        self.domain = domain
        self.router = router
        self._lock = asyncio.Lock()
        self._pending: asyncio.Task[tuple[str, float]] | None = None
        self._token: str | None = None
        self._until = 0.0

    @classmethod
    def from_settings(cls, settings: Settings, gateway: ClientTokenGateway | None) -> SdkService:
        """Build from the environment; the fallback label follows DEP-4's two switches."""
        return cls(
            gateway=gateway,
            client_id=settings.paypal_client_id,
            sdk_auth=settings.paypal_sdk_auth,
            approval_ui=settings.paypal_approval_ui,
            fallback=(
                settings.payment_router == "single_seller"
                or settings.payment_mode == "capture_only"
            ),
            domain=urlsplit(settings.frontend_base_url).hostname,
            router=settings.payment_router,
        )

    def config(self) -> dict[str, Any]:
        """The exact public object of ``api.md`` section 4.1; no secret, no amount."""
        labels = checkout_labels(self.router)
        if self.fallback:
            labels.append(FALLBACK_LABEL)
        mock = mock_gateway.label()
        if mock is not None:
            labels.append(mock)
        return {
            "approval_ui": self.approval_ui,
            "sdk_auth": self.sdk_auth,
            "client_id": self.client_id,
            "sdk_url": SDK_URL,
            "components": list(SDK_COMPONENTS),
            "page_type": "checkout",
            "currency": "USD",
            "labels": labels,
        }

    async def client_token(self) -> dict[str, Any]:
        """The browser-safe SDK token, cached until a minute before it expires."""
        if self.approval_ui == "redirect":
            # The redirect flow never initialises the SDK, so there is no token to hand out.
            raise ApplicationError("FEATURE_DISABLED")
        if self.sdk_auth != "client_token":
            # api.md section 3: the route exists only when S13 selected client_token.
            raise ApplicationError("FEATURE_DISABLED")
        if self.gateway is None or not self.domain:
            raise ApplicationError("FEATURE_DISABLED")
        cached = self._cached()
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._cached()
            if cached is not None:
                return cached
            # One shared fetch: concurrent buyers wait on that task, not on the lock
            # while PayPal is slow (T07A01).
            task = self._pending
            if task is None:
                task = asyncio.ensure_future(self._fetch())
                self._pending = task
        try:
            token, until = await task
        except TimeoutError:
            raise ApplicationError("PAYPAL_UNAVAILABLE") from None
        return {"client_token": token, "expires_in": max(1, int(until - time.monotonic()))}

    def _cached(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if self._token is not None and now < self._until:
            return {"client_token": self._token, "expires_in": max(1, int(self._until - now))}
        return None

    async def _fetch(self) -> tuple[str, float]:
        """One short attempt: a stuck PayPal call does not hold up every buyer."""
        gateway, domain = self.gateway, self.domain
        assert gateway is not None and domain is not None
        try:
            token, expires_in = await asyncio.wait_for(
                gateway.client_token(domain), CLIENT_TOKEN_TIMEOUT_S
            )
        finally:
            self._pending = None
        ttl = max(1, int(expires_in) - TOKEN_SAFETY_MARGIN_S)
        until = time.monotonic() + ttl
        self._token, self._until = token, until
        return token, until
