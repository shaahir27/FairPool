"""F24: a refund that cannot complete leaves the lot FAILING, never closed."""

from __future__ import annotations

import pytest

from tests.integration.test_failure_path import (  # noqa: F401
    test_f24_a_failed_refund_keeps_the_lot_failing,
)

pytestmark = [pytest.mark.integration, pytest.mark.faults]
