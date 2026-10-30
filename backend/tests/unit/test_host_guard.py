"""T00A03: only the two PayPal Sandbox hosts may ever be used (FR-PP-06)."""

from __future__ import annotations

import pytest

from fairpool.api.app import create_app
from fairpool.config import (
    SANDBOX_API_HOST,
    SANDBOX_CHECKOUT_HOST,
    ForbiddenHost,
    Settings,
    assert_sandbox_host,
)
from tests.unit.test_settings import make_settings


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api-m.sandbox.paypal.com", SANDBOX_API_HOST),
        ("https://api-m.sandbox.paypal.com/v2/checkout/orders", SANDBOX_API_HOST),
        ("https://api-m.sandbox.paypal.com:443/v1/oauth2/token", SANDBOX_API_HOST),
        ("https://www.sandbox.paypal.com", SANDBOX_CHECKOUT_HOST),
        ("https://www.sandbox.paypal.com/checkoutnow?token=dummy", SANDBOX_CHECKOUT_HOST),
    ],
)
def test_sandbox_origins_are_accepted(url: str, expected: str) -> None:
    assert_sandbox_host(url, expected)


@pytest.mark.parametrize(
    "url",
    [
        "https://api-m.paypal.com",
        "https://www.paypal.com",
        "https://api-m.sandbox.paypal.com.evil.test",
        "https://evil.api-m.sandbox.paypal.com",
        "https://user:pass@api-m.sandbox.paypal.com",
        "https://api-m.sandbox.paypal.com@evil.test",
        "http://api-m.sandbox.paypal.com",
        "https://api-m.sandbox.paypal.com:8443",
        "ftp://api-m.sandbox.paypal.com",
        "",
        "not a url",
    ],
)
def test_non_sandbox_origins_raise_forbidden_host(url: str) -> None:
    with pytest.raises(ForbiddenHost):
        assert_sandbox_host(url, SANDBOX_API_HOST)


def test_checkout_host_is_not_accepted_in_place_of_api_host() -> None:
    with pytest.raises(ForbiddenHost):
        assert_sandbox_host("https://www.sandbox.paypal.com", SANDBOX_API_HOST)


def test_settings_reject_live_api_host() -> None:
    with pytest.raises(ForbiddenHost):
        make_settings(paypal_api_base="https://api-m.paypal.com")


def test_settings_reject_live_checkout_host() -> None:
    with pytest.raises(ForbiddenHost):
        make_settings(paypal_checkout_base="https://www.paypal.com")


def test_create_app_rechecks_hosts_on_a_hand_built_object() -> None:
    live = Settings.model_construct(
        paypal_api_base="https://api-m.paypal.com",
        paypal_checkout_base="https://www.sandbox.paypal.com",
    )
    with pytest.raises(ForbiddenHost):
        create_app(live)


def test_create_app_accepts_validated_sandbox_settings() -> None:
    app = create_app(make_settings())
    assert app.state.settings is not None
    assert app.state.settings.paypal_api_base == "https://api-m.sandbox.paypal.com"
