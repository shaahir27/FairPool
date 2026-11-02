"""T00A02: JSON logs with correlation IDs never leak secrets or approval URLs."""

from __future__ import annotations

import io
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
    configure_logging,
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


#: The message template and argument shape uvicorn's access logger uses (H11Impl).
UVICORN_ACCESS_TEMPLATE = '%s - "%s %s HTTP/%s" %d %s'
UVICORN_ACCESS_ARGS: tuple[Any, ...] = (
    "127.0.0.1:52000",
    "GET",
    "/api/v1/auth/paypal/return?code=OAUTHCODEVALUE&state=OAUTHSTATEVALUE",
    "1.1",
    302,
    512,
)


def test_redacted_access_record_still_formats_with_uvicorn() -> None:
    from uvicorn.logging import AccessFormatter

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "127.0.0.1:52000",
            "GET",
            "/api/v1/auth/paypal/callback?code=PRIVATECODE&state=PRIVATESTATE",
            "1.1",
            200,
        ),
        None,
    )
    # Startup attaches the filter to both the logger and its handler.
    redactor = RedactionFilter()
    redactor.filter(record)
    redactor.filter(record)
    rendered = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    ).format(record)
    assert "PRIVATECODE" not in rendered and "PRIVATESTATE" not in rendered
    assert "200 OK" in rendered and "/api/v1/auth/paypal/callback" in rendered


def test_redacted_startup_record_formats_its_process_id() -> None:
    from uvicorn.logging import DefaultFormatter

    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, "Started server process [%d]", (12345,), None
    )
    record.color_message = "Started server process [%d]"
    RedactionFilter().filter(record)
    rendered = DefaultFormatter("%(message)s", use_colors=True).format(record)
    assert "12345" in rendered and "%d" not in rendered


def test_the_filter_masks_an_access_line_query_string() -> None:
    """M3: the request line uvicorn prints carries a live OAuth code and state."""
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="h11_impl.py",
        lineno=483,
        msg=UVICORN_ACCESS_TEMPLATE,
        args=UVICORN_ACCESS_ARGS,
        exc_info=None,
    )

    assert RedactionFilter().filter(record) is True

    # What uvicorn's own plain formatter would have written.
    line = record.getMessage()
    assert "OAUTHCODEVALUE" not in line and "OAUTHSTATEVALUE" not in line
    assert REDACTED in line and "/api/v1/auth/paypal/return" in line
    # A vault return carries its single-use token the same way.
    vault_args = (
        "127.0.0.1:52000",
        "GET",
        "/api/v1/entries/e/vault/return?token=SETUPTOKENVALUE",
        "1.1",
        302,
        512,
    )
    vault = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="h11_impl.py",
        lineno=483,
        msg=UVICORN_ACCESS_TEMPLATE,
        args=vault_args,
        exc_info=None,
    )
    RedactionFilter().filter(vault)
    assert "SETUPTOKENVALUE" not in vault.getMessage()

    # The same shape through the shared text masker, which every path uses: this is
    # the rule that had a separator the query string never contains.
    masked = redact_text("redirect /return?code=PLAINCODE&state=PLAINSTATE ok")
    assert "PLAINCODE" not in masked and "PLAINSTATE" not in masked
    assert "redirect" in masked and "ok" in masked
    # Diagnostics that merely mention a state are not secrets and stay readable.
    assert (
        redact_text("from_state=OFFERED to_state=APPROVED")
        == "from_state=OFFERED to_state=APPROVED"
    )


def test_configure_logging_redacts_the_loggers_uvicorn_owns() -> None:
    """The root handler is not enough: uvicorn writes through its own loggers (M3)."""
    root = logging.getLogger()
    access, error = logging.getLogger("uvicorn.access"), logging.getLogger("uvicorn.error")
    saved = (root.handlers[:], access.handlers[:], error.handlers[:])
    # The handler uvicorn's own logging config would have installed before we ran.
    access_handler = logging.StreamHandler(io.StringIO())
    access_handler.setFormatter(logging.Formatter("%(message)s"))
    access.addHandler(access_handler)
    buffer = io.StringIO()
    later = logging.StreamHandler(buffer)
    later.setFormatter(logging.Formatter("%(message)s"))
    try:
        configure_logging("INFO")
        for target in (access, error):
            assert any(isinstance(f, RedactionFilter) for f in target.filters), target.name
        assert any(isinstance(f, RedactionFilter) for f in access_handler.filters)

        access.info(UVICORN_ACCESS_TEMPLATE, *UVICORN_ACCESS_ARGS)
        rendered = access_handler.stream.getvalue()  # type: ignore[union-attr]
        assert "OAUTHCODEVALUE" not in rendered and "OAUTHSTATEVALUE" not in rendered

        # A handler uvicorn adds after startup is covered on the next call, and the
        # wiring is idempotent: it never stacks the same filter twice.
        access.addHandler(later)
        before = len(access.filters)
        configure_logging("INFO")
        assert len(access.filters) == before
        assert any(isinstance(f, RedactionFilter) for f in later.filters)
        access.log(logging.INFO, "GET /?code=LATEHANDLERSECRET")
        assert "LATEHANDLERSECRET" not in buffer.getvalue()
    finally:
        root.handlers[:] = saved[0]
        access.handlers[:] = saved[1]
        error.handlers[:] = saved[2]
        access.filters.clear()
        error.filters.clear()
