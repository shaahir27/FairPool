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

from fairpool.config import Settings
from fairpool.domain.errors import ApplicationError
from fairpool.modules.checkout import mock_gateway

#: The SDK v6 core script on the Sandbox checkout host (INT-7).
SDK_URL: Final[str] = "https://www.sandbox.paypal.com/web-sdk/v6/core"
SDK_COMPONENTS: Final[tuple[str, ...]] = ("paypal-payments",)
SANDBOX_LABEL: Final[str] = "SANDBOX"
#: The short label of DEP-4, shown wherever the stand-in routing applies.
FALLBACK_LABEL: Final[str] = "FALLBACK: single stand-in seller"
#: The contract caches a client token until one minute before expiry.
TOKEN_SAFETY_MARGIN_S: Final[int] = 60


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
    ) -> None:
        self.gateway = gateway
        self.client_id = client_id
        self.sdk_auth = sdk_auth
        self.approval_ui = approval_ui
        self.fallback = fallback
        self.domain = domain
        self._lock = asyncio.Lock()
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
        )

    def config(self) -> dict[str, Any]:
        """The exact public object of ``api.md`` section 4.1; no secret, no amount."""
        labels = [SANDBOX_LABEL]
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
        async with self._lock:
            now = time.monotonic()
            if self._token is not None and now < self._until:
                return {"client_token": self._token, "expires_in": max(1, int(self._until - now))}
            token, expires_in = await self.gateway.client_token(self.domain)
            ttl = max(1, int(expires_in) - TOKEN_SAFETY_MARGIN_S)
            self._token = token
            self._until = time.monotonic() + ttl
            return {"client_token": token, "expires_in": ttl}
