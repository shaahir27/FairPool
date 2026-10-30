"""T00A02: JSON logs with correlation IDs never leak secrets or approval URLs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from _pytest.logging import LogCaptureFixture

from fairpool.logging import (
    CORRELATION_FIELDS,
    REDACTED,
    REDACTED_URL,
    JsonFormatter,
    RedactionFilter,
    buyer_order_id,
    lot_id,
    paypal_debug_id,
    pool_id,
    redact_text,
    request_id,
)

LOGGER_NAME = "fairpool.test.redaction"


@pytest.fixture(autouse=True)
def redact_caplog(caplog: LogCaptureFixture) -> Iterator[None]:
    """Attach the production filter to caplog's handler, as configure_logging does."""
    caplog.handler.addFilter(RedactionFilter())
    yield


def logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def render_last(caplog: LogCaptureFixture) -> tuple[logging.LogRecord, str, dict[str, Any]]:
    assert caplog.records, "no log record captured"
    record = caplog.records[-1]
    assert RedactionFilter().filter(record) is True
    text = JsonFormatter().format(record)
    payload = json.loads(text)
    return record, text, payload


@pytest.mark.parametrize(
    ("template", "args", "secret"),
    [
        ("client_secret=%s", ("dummy-client-secret-value",), "dummy-client-secret-value"),
        ("token=%s", ("dummy-token-value",), "dummy-token-value"),
        ('{"vault_token": "%s"}', ("dummy-vault-token",), "dummy-vault-token"),
        ("password=%s", ("dummy-password",), "dummy-password"),
        ("PayPal-Auth-Assertion: %s", ("dummy.assertion.value",), "dummy.assertion.value"),
        ("Authorization: Bearer %s", ("fpd_prefix_secret",), "fpd_prefix_secret"),
        ("merchant key fpm_prefix_secret", (), "fpm_prefix_secret"),
        (
            "approve https://www.sandbox.paypal.com/checkoutnow?token=%s",
            ("PAYPALORDER123",),
            "PAYPALORDER123",
        ),
        (
            "vault https://www.sandbox.paypal.com/agreements/approve?approval_session_id=%s",
            ("APPROVALSESSION123",),
            "APPROVALSESSION123",
        ),
    ],
)
def test_message_values_are_redacted(
    caplog: LogCaptureFixture,
    template: str,
    args: tuple[str, ...],
    secret: str,
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        logger().info(template, *args)
    _, text, payload = render_last(caplog)
    assert secret not in text
    assert secret not in caplog.text
    assert isinstance(payload["message"], str)


def test_sensitive_extra_attributes_are_masked(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        logger().info(
            "checkout prepared",
            extra={
                "client_secret": "dummy-extra-secret",
                "payment_token": "dummy-payment-token",
                "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER42",
                "vault_status": "ACTIVE",
            },
        )
    record, text, _ = render_last(caplog)
    assert record.client_secret == REDACTED
    assert record.payment_token == REDACTED
    assert record.approval_url == REDACTED
    assert record.vault_status == REDACTED
    assert "dummy-extra-secret" not in text
    assert "dummy-payment-token" not in text
    assert "ORDER42" not in text


def test_non_sensitive_extra_values_are_still_scanned(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        logger().info(
            "links",
            extra={
                "checkout_url": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER42",
                "note": "delegation fpd_prefix_secret",
            },
        )
    record, text, _ = render_last(caplog)
    assert "ORDER42" not in record.checkout_url
    assert record.note == f"delegation {REDACTED}"
    assert "ORDER42" not in text


def test_exception_text_is_redacted(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        try:
            raise RuntimeError("upstream said token=dummy-exception-token")
        except RuntimeError:
            logger().exception("handler failed")
    record, text, _ = render_last(caplog)
    assert record.exc_info is None
    assert "dummy-exception-token" not in text
    assert "dummy-exception-token" not in caplog.text


def test_json_shape_and_correlation_ids(caplog: LogCaptureFixture) -> None:
    tokens = [
        request_id.set("req-1"),
        pool_id.set("pool-1"),
        lot_id.set("lot-1"),
        buyer_order_id.set("buyer-order-1"),
        paypal_debug_id.set("debug-1"),
    ]
    try:
        with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
            logger().info("pool opened")
        _, _, payload = render_last(caplog)
    finally:
        for variable, token in zip(
            (request_id, pool_id, lot_id, buyer_order_id, paypal_debug_id),
            tokens,
            strict=True,
        ):
            variable.reset(token)

    assert set(payload) == {"timestamp", "level", "logger", "message", *CORRELATION_FIELDS}
    assert datetime.fromisoformat(str(payload["timestamp"]))
    assert payload["level"] == "INFO"
    assert payload["logger"] == LOGGER_NAME
    assert payload["message"] == "pool opened"
    assert payload["request_id"] == "req-1"
    assert payload["pool_id"] == "pool-1"
    assert payload["lot_id"] == "lot-1"
    assert payload["buyer_order_id"] == "buyer-order-1"
    assert payload["paypal_debug_id"] == "debug-1"


def test_correlation_fields_are_absent_when_unset(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        logger().info("no context")
    _, _, payload = render_last(caplog)
    assert set(payload) == {"timestamp", "level", "logger", "message"}


def test_redact_text_masks_urls_and_tokens_but_keeps_prose() -> None:
    masked = redact_text("approve https://www.sandbox.paypal.com/checkoutnow?token=ORDER42 now")
    assert REDACTED_URL in masked
    assert "approve" in masked
    assert "now" in masked
    assert "ORDER42" not in masked
    assert redact_text("lot opened for bidding") == "lot opened for bidding"
