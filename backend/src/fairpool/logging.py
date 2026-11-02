"""Structured JSON logging with correlation IDs and secret redaction (T00A02/T00A03).

Logs are newline-delimited JSON. Correlation IDs travel in contextvars so
handlers never have to thread them through arguments. The redaction filter is
the last line of defence for I14: it masks secret-shaped keys, agent tokens and
PayPal approval URLs before a record is formatted, and it is attached to
uvicorn's own loggers as well, because their access line echoes the request
query string (an OAuth ``code``/``state`` or a vault ``token``) that our root
handler would never see (M3).
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

#: Loggers uvicorn creates and configures itself. Its access logger prints the full
#: request line, query string included, so it is redacted like our own output (M3).
UVICORN_LOGGERS: Final[tuple[str, ...]] = ("uvicorn.access", "uvicorn.error")

# Keys that may never carry a value into a log record (AGENTS.md section 3 rule 2).
_SENSITIVE_KEY = re.compile(
    r"(?:secret|token|assertion|password|approval|client_secret|payment_token|vault)",
    re.IGNORECASE,
)
_EXACT_SENSITIVE_KEYS: Final[frozenset[str]] = frozenset(
    {"code", "state", "nonce", "payer_id", "access_token", "refresh_token", "setup_token_id"}
)
_APPROVAL_URL = re.compile(
    r"https://(?:www\.)?sandbox\.paypal\.com/"
    r"[^\s\"'<>]*(?:checkoutnow|approve|webapps|token=|approval_session_id=|ba_token=)"
    r"[^\s\"'<>]*",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]+")
_AGENT_TOKEN = re.compile(r"\b(?:fpd|fpm)_[A-Za-z0-9._\-]+")
# An OAuth authorization code, the single-use state, the nonce and the PayPal
# payer id arrive in a query string, so any access or error line that echoes the
# URL would leak a live credential. \b keeps `from_state=` and `to_state=` (which
# are diagnostics, not secrets) out of the mask.
_OAUTH_PARAM = re.compile(
    r"(?i)\b(code|state|nonce|PayerID|ba_token|auth_code)([\"']?\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"
)
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
    masked = _KEY_VALUE.sub(_mask_key_value, masked)
    return _OAUTH_PARAM.sub(_mask_key_value, masked)


class RedactionFilter(logging.Filter):
    """Remove secrets from a record before any handler formats it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name == "uvicorn.access"
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            # Uvicorn's formatter unpacks these fields after redaction (I14).
            record.msg = redact_text(str(record.msg))
            record.args = tuple(
                redact_text(arg) if isinstance(arg, str) else arg for arg in record.args
            )
            message = record.getMessage()
        else:
            message = redact_text(record.getMessage())
            record.msg = message
            record.args = ()
        record.message = message

        for key in list(record.__dict__):
            if key in _STANDARD_RECORD_KEYS or key == "message":
                continue
            value = record.__dict__[key]
            if key == "color_message":
                record.__dict__[key] = message
            elif _SENSITIVE_KEY.search(key) or key in _EXACT_SENSITIVE_KEYS:
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


def _redact_logger(name: str) -> None:
    """Put the redaction filter on a logger uvicorn owns (M3).

    ``uvicorn.access`` formats the whole request line, so the OAuth callback's
    ``?code=...&state=...`` and a vault return's ``?token=...`` would otherwise be
    printed verbatim: a filter on the root handler never sees those records, because
    uvicorn attaches its own handler to its own logger and the record stops there.
    Both the logger and any handler it already has get the filter, so the order of
    ``configure_logging`` versus uvicorn's own logging setup does not matter.
    """
    target = logging.getLogger(name)
    if not any(isinstance(existing, RedactionFilter) for existing in target.filters):
        target.addFilter(RedactionFilter())
    for handler in target.handlers:
        if not any(isinstance(existing, RedactionFilter) for existing in handler.filters):
            handler.addFilter(RedactionFilter())


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler once on the root logger."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for name in UVICORN_LOGGERS:
        _redact_logger(name)
    for handler in root.handlers:
        if getattr(handler, "_fairpool_json", False):
            return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())
    handler._fairpool_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
