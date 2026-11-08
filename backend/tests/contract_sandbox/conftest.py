"""Gate and shared gateway for ``backend/tests/contract_sandbox`` (``paypal-adapter.md`` §11).

Two rules live here so no contract test can quietly break them:

* a test marked ``sandbox_interactive`` needs a human to approve one order, so it skips
  unless the operator opts in with ``FAIRPOOL_SANDBOX_APPROVAL=1``; a missing approval is
  a skip with a reason, never a pass;
* every provider test builds its gateway from exported variables through
  ``support.settings`` and skips when they are absent, so CI never calls PayPal (rule 18).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from fairpool.adapters.paypal.gateway import RestPayPalGateway
from tests.contract_sandbox.support import requires_credentials, settings

#: Set to ``1`` once a human is ready to approve orders in the Sandbox buyer account.
APPROVAL_ENV = "FAIRPOOL_SANDBOX_APPROVAL"

APPROVAL_SKIP_REASON = (
    "needs a human approval: export "
    f"{APPROVAL_ENV}=1, have the Sandbox buyer account ready, and re-run"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the approval runs before they create an order, so a default run is safe."""
    if os.environ.get(APPROVAL_ENV) == "1":
        return
    skip = pytest.mark.skip(reason=APPROVAL_SKIP_REASON)
    for item in items:
        if item.get_closest_marker("sandbox_interactive"):
            item.add_marker(skip)


@pytest.fixture
async def gateway() -> AsyncIterator[RestPayPalGateway]:
    """A real Sandbox gateway on the exported app-owning seller; no mock, no ``.env``."""
    requires_credentials()
    value = RestPayPalGateway(settings())
    try:
        yield value
    finally:
        await value.close()
