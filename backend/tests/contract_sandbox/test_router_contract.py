"""C-16: the payee-email router is a schema value that refuses to run (S7, G11).

No provider call, no marker: this runs in the default suite, so a regression that
re-enables a router S7 proved cannot void or refund fails CI instead of a demo.
"""

from __future__ import annotations

import pytest

from fairpool.adapters.paypal.routers import ROUTER_SPECS, SINGLE_SELLER_LABEL, label, require
from fairpool.domain.payments import NotEnabled, PaymentError


def test_c16_payee_email_router_not_enabled() -> None:
    """C-16 (S7, G11): ``payee_email`` raises ``NotEnabled`` and never reaches a host.

    S7 (Oct 28) found a separately selected seller could receive captures but void and
    refund returned ``PERMISSION_DENIED``, so a lot routed there could not be failed
    safely. The enum value stays only so stored rows and this test match.
    """
    with pytest.raises(NotEnabled) as rejected:
        require("payee_email")
    # A CONFIG refusal, not a provider error: nothing was sent (I1, I2, I14).
    assert isinstance(rejected.value, PaymentError)
    assert rejected.value.category == "CONFIG"
    assert rejected.value.code == "ROUTER_DISABLED"

    assert ROUTER_SPECS["payee_email"].enabled is False
    assert ROUTER_SPECS["payee_email"].label is None
    with pytest.raises(NotEnabled):
        label("payee_email")

    # The positive control: the single live fallback still builds, with its contract label.
    assert require("single_seller").label == SINGLE_SELLER_LABEL
