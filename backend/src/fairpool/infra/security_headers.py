"""Browser hardening headers and the inbound correlation-ID sanitiser.

The API answers JSON and one SPA, so the same five headers are right for every
response: no MIME sniffing, no referrer, no framing (the app is never embedded),
no device APIs, and HSTS only where the transport is already https.

``sanitize_request_id`` is the other half: the request ID is echoed into a
response header and every structured log line, so an inbound value is only kept
when it is an identifier and not a free-text channel into our logs (I14).
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Fixed values, never per request: a header that changes per response would
#: defeat the point of a static policy.
HEADERS: Final[dict[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

#: One year, this host only: a wildcard suffix would pin sibling onrender.com apps.
HSTS_VALUE: Final[str] = "max-age=31536000"

_REQUEST_ID_RE: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")


def sanitize_request_id(value: str | None) -> str:
    """The caller's correlation ID when it is well formed, else a fresh one.

    The value reaches the response header and every log line, so a free-text or
    header-injection shaped value is replaced rather than reflected.
    """
    if value is not None and _REQUEST_ID_RE.fullmatch(value):
        return value
    return uuid.uuid4().hex


class SecurityHeadersMiddleware:
    """Add the browser policy to every http response (``app.add_middleware``)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        secure = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in HEADERS.items():
                    # ``setdefault``: a route that pinned its own value keeps it.
                    if name not in headers:
                        headers[name] = value
                if secure and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = HSTS_VALUE
            await send(message)

        await self.app(scope, receive, send_with_headers)


__all__ = ["HEADERS", "HSTS_VALUE", "SecurityHeadersMiddleware", "sanitize_request_id"]
