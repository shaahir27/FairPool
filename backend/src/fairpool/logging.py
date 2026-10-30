"""Structured JSON logging with correlation IDs and secret redaction (T00A02/T00A03).

Logs are newline-delimited JSON. Correlation IDs travel in contextvars so
handlers never have to thread them through arguments. The redaction filter is
the last line of defence for I14: it masks secret-shaped keys, agent tokens and
PayPal approval URLs before a record is formatted.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Final

REDACTED: Final[str] = "[REDACTED]"
REDACTED_URL: Final[str] = "[REDACTED_URL]"

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
pool_id: ContextVar[str | None] = ContextVar("pool_id", default=None)
lot_id: ContextVar[str | None] = ContextVar("lot_id", default=None)
buyer_order_id: ContextVar[str | None] = ContextVar("buyer_order_id", default=None)
paypal_debug_id: ContextVar[str | None] = ContextVar("paypal_debug_id", default=None)

CORRELATION_FIELDS: Final[tuple[str, ...]] = (
    "request_id",
    "pool_id",
    "lot_id",
    "buyer_order_id",
    "paypal_debug_id",
)

_CONTEXT_VARS: Final[dict[str, ContextVar[str | None]]] = {
    "request_id": request_id,
    "pool_id": pool_id,
    "lot_id": lot_id,
    "buyer_order_id": buyer_order_id,
    "paypal_debug_id": paypal_debug_id,
}

# Keys that may never carry a value into a log record (agents.md section 3 rule 2).
_SENSITIVE_KEY = re.compile(
    r"(?:secret|token|assertion|password|approval|client_secret|payment_token|vault)",
    re.IGNORECASE,
)
_APPROVAL_URL = re.compile(
    r"https://(?:www\.)?sandbox\.paypal\.com/"
    r"[^\s\"'<>]*(?:checkoutnow|approve|webapps|token=|approval_session_id=|ba_token=)"
    r"[^\s\"'<>]*",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+")
_AGENT_TOKEN = re.compile(r"\b(?:fpd|fpm)_[A-Za-z0-9._\-]+")
_KEY_VALUE = re.compile(
    r"(?i)\b("
    r"[A-Za-z0-9_.\-]*(?:secret|token|assertion|password|approval|vault)[A-Za-z0-9_.\-]*"
    r")([\"']?\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)

_STANDARD_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", (), None))
)


def _mask_key_value(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}{REDACTED}"


def redact_text(text: str) -> str:
    """Mask secret-shaped values inside free text."""
    masked = _APPROVAL_URL.sub(REDACTED_URL, text)
    masked = _BEARER.sub(f"Bearer {REDACTED}", masked)
    masked = _AGENT_TOKEN.sub(REDACTED, masked)
    return _KEY_VALUE.sub(_mask_key_value, masked)


class RedactionFilter(logging.Filter):
    """Remove secrets from a record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact_text(record.getMessage())
        record.msg = message
        record.args = ()
        record.message = message

        for key in list(record.__dict__):
            if key in _STANDARD_RECORD_KEYS or key == "message":
                continue
            value = record.__dict__[key]
            if _SENSITIVE_KEY.search(key):
                record.__dict__[key] = REDACTED
            elif isinstance(value, str):
                record.__dict__[key] = redact_text(value)

        # Tracebacks may embed a secret in an exception message; keep the type
        # and stack but never the raw text.
        if record.exc_info is not None:
            rendered = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact_text(rendered)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line with timestamp, level, logger and message."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        for name in CORRELATION_FIELDS:
            value = _CONTEXT_VARS[name].get()
            if value:
                payload[name] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler once on the root logger."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in root.handlers:
        if getattr(handler, "_fairpool_json", False):
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    handler._fairpool_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
