"""Payment routers and their user-facing labels (T07A03; ``paypal-adapter.md`` §9).

One registry owns every label string, so the sentence a buyer reads on the offer,
the order page and the checkout config cannot drift from the router the lot was
stamped with at award time (N8, DEP-4). Only two routers are live:

* ``single_seller`` -- G4 failed and S7 rejected the alternative, so every order's
  payee is the sandbox business account that owns the REST app. Its label is the
  verbatim sentence of ``paypal-adapter.md`` section 9.
* ``fake`` -- the offline gateway of SIMULATION pools and tests (I12).

``payee_email`` and ``platform`` keep their enum values only so stored rows and
tests match; constructing either raises ``NotEnabled`` and never reaches a host
(S7, G4, G9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fairpool.domain.payments import NotEnabled

#: The verbatim label of the only live fallback (``paypal-adapter.md`` section 9).
SINGLE_SELLER_LABEL: Final[str] = (
    "Sandbox demo: one test seller stands in for the winning merchant."
)

#: The simulation banner's short label (FR-SM-01, I12).
SIMULATED_LABEL: Final[str] = "SIMULATED"


@dataclass(frozen=True)
class RouterSpec:
    name: str
    enabled: bool
    label: str | None


#: Every value the ``payment_router`` enum can hold, and whether it may be built.
ROUTER_SPECS: Final[dict[str, RouterSpec]] = {
    "fake": RouterSpec("fake", True, SIMULATED_LABEL),
    "single_seller": RouterSpec("single_seller", True, SINGLE_SELLER_LABEL),
    # S7 (Oct 28): a second seller received captures but void and refund were
    # denied, so a lot routed there could not be failed safely. G4/G9 kept the
    # platform router unavailable (no partner permission, no assertion, no fee).
    "payee_email": RouterSpec("payee_email", False, None),
    "platform": RouterSpec("platform", False, None),
}


def require(name: str) -> RouterSpec:
    """The spec of an enabled router; a rejected or unknown name is ``NotEnabled``."""
    spec = ROUTER_SPECS.get(name)
    if spec is None or not spec.enabled:
        raise NotEnabled()
    return spec


def label(name: str) -> str | None:
    """The user-facing label for an enabled router (``SIMULATED`` for ``fake``)."""
    return require(name).label
