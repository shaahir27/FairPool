"""T07A03: the router registry owns the exact labels and the enabled set.

``paypal-adapter.md`` section 9 fixes the single-seller sentence verbatim, keeps
``payee_email`` rejected by S7 (void and refund were denied for a second seller)
and ``platform`` unavailable after G4/G9. The wiring's router must not carry a
second copy of either sentence (the API notices read this registry).
"""

from __future__ import annotations

import pytest

from fairpool.adapters.paypal import routers
from fairpool.domain.payments import NotEnabled
from fairpool.modules.checkout.mock_gateway import FaultInjectingGateway
from fairpool.wiring import payment_router
from tests.unit.test_settings import make_settings

SINGLE_SELLER_LABEL = "Sandbox demo: one test seller stands in for the winning merchant."


def test_single_seller_is_live_with_the_verbatim_label() -> None:
    spec = routers.require("single_seller")

    assert spec.enabled is True
    assert routers.label("single_seller") == SINGLE_SELLER_LABEL


def test_fake_router_is_labelled_simulated() -> None:
    assert routers.label("fake") == "SIMULATED"


@pytest.mark.parametrize("name", ["payee_email", "platform"])
def test_rejected_routers_raise_not_enabled(name: str) -> None:
    with pytest.raises(NotEnabled):
        routers.require(name)
    with pytest.raises(NotEnabled):
        routers.label(name)


def test_unknown_router_name_raises_not_enabled() -> None:
    with pytest.raises(NotEnabled):
        routers.require("nope")


def test_wiring_delegates_its_label_and_refuses_a_rejected_router() -> None:
    simulated = payment_router(make_settings(), simulated=True)
    assert simulated.label() == "SIMULATED"

    live = payment_router(
        make_settings(payment_router="single_seller", single_seller_email="seller@example.test")
    )
    assert live.label() == routers.SINGLE_SELLER_LABEL

    with pytest.raises(NotEnabled):
        payment_router(make_settings(payment_router="payee_email"))
    with pytest.raises(NotEnabled):
        payment_router(make_settings(payment_router="platform"))


def test_mock_wrapper_exists_only_behind_the_toggle_flag() -> None:
    plain = payment_router(make_settings(payment_router="fake"))
    assert not isinstance(plain.gateway, FaultInjectingGateway)

    wrapped = payment_router(make_settings(payment_router="fake", mock_toggles_enabled=True))
    assert isinstance(wrapped.gateway, FaultInjectingGateway)
