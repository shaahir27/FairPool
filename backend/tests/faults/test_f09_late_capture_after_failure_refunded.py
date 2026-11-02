"""F9: a capture that completes after the failure pass is refunded before close.

The case is written once, beside the failure path it exercises; this module gives
it the ``faults`` marker so the gate's fault run collects it.
"""

from __future__ import annotations

import pytest

from tests.integration.test_failure_path import (  # noqa: F401
    test_f09_a_capture_that_completes_late_is_refunded,
)

pytestmark = [pytest.mark.integration, pytest.mark.faults]
