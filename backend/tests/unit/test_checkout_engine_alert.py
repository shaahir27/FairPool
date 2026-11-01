"""T03A01 acceptance 4: an illegal transition is alerted as well as raised.

CR-3 note 5 requires one structured ERROR record naming the machine, the pair, the
attempted trigger and the correlation ids available. These tests capture the log
records at emit time, because the correlation contextvars are reset as soon as the
refusal is written, and they check that nothing secret-shaped reaches the line (I14).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool import logging as correlation
from fairpool.domain.checkout_guards import Observation
from fairpool.domain.errors import IllegalTransition
from fairpool.logging import CORRELATION_FIELDS, JsonFormatter, redact_text
from fairpool.modules.checkout.engine import TransitionRequest
from tests.unit.test_checkout_engine import (
    insert_capture,
    insert_paypal_order,
    make_scene,
    stored_status,
    trigger_for,
)

pytestmark = pytest.mark.integration

ENGINE_LOGGER = "fairpool.checkout.engine"


class _Capture(logging.Handler):
    """Collect every record with the correlation contextvars as they were at emit."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[tuple[logging.LogRecord, dict[str, str | None]]] = []

    def emit(self, record: logging.LogRecord) -> None:
        ids = {name: getattr(correlation, name).get() for name in CORRELATION_FIELDS}
        self.records.append((record, ids))


@pytest.fixture
def capture() -> Any:
    handler = _Capture()
    logger = logging.getLogger(ENGINE_LOGGER)
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _messages(handler: _Capture) -> list[str]:
    return [record.getMessage() for record, _ in handler.records]


async def test_illegal_transition_raises_and_alerts_once(
    db_session: AsyncSession, capture: _Capture
) -> None:
    """T03A01 acceptance 4: one ERROR record, machine, pair, trigger and ids."""
    scene = await make_scene(db_session, status="CAPTURED")
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="OFFERED",
                trigger="job:order.capture",
            ),
        )
    assert len(capture.records) == 1
    record, ids = capture.records[0]
    assert record.levelname == "ERROR"
    assert record.name == ENGINE_LOGGER
    assert record.machine == "buyer_order"
    assert record.from_state == "CAPTURED"
    assert record.to_state == "OFFERED"
    assert record.trigger == "job:order.capture"
    message = record.getMessage()
    for fragment in ("machine=buyer_order", "from_state=CAPTURED", "to_state=OFFERED"):
        assert fragment in message
    assert ids["lot_id"] == str(scene.lot_id)
    assert ids["buyer_order_id"] == str(scene.order_id)
    assert ids["pool_id"] == str(scene.pool_id)
    line = json.loads(JsonFormatter().format(record))
    assert line["level"] == "ERROR"
    assert line["logger"] == ENGINE_LOGGER
    assert await stored_status(db_session, scene.order_id) == "CAPTURED"


async def test_guard_failure_alerts_with_the_reason(
    db_session: AsyncSession, capture: _Capture
) -> None:
    """T03A01 acceptance 4: a listed pair with an unmet guard alerts too."""
    scene = await make_scene(db_session, offer_in=-1)
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="ORDER_CREATED",
                trigger=trigger_for("BO-01"),
            ),
        )
    assert len(capture.records) == 1
    record, _ = capture.records[0]
    assert "guard unmet" in record.getMessage()
    assert "offer_expires_at" in record.getMessage()


async def test_each_refusal_writes_exactly_one_record(
    db_session: AsyncSession, capture: _Capture
) -> None:
    """T03A01 acceptance 4: no duplicate alerting, no silent swallowing."""
    scene = await make_scene(db_session, status="AUTHORIZED")
    for to_state in ("OFFERED", "CAPTURED", "REFUNDED"):
        with pytest.raises(IllegalTransition):
            await scene.ports.engine.apply(
                db_session,
                TransitionRequest(buyer_order_id=scene.order_id, to_state=to_state, trigger="x"),
            )
    assert len(capture.records) == 3
    assert [record.to_state for record, _ in capture.records] == [
        "OFFERED",
        "CAPTURED",
        "REFUNDED",
    ]


async def test_foreign_evidence_alerts_and_writes_nothing(
    db_session: AsyncSession, capture: _Capture
) -> None:
    """T03A01 acceptance 4 and 9: refused evidence alerts; no ledger row appears."""
    scene = await make_scene(db_session, status="CAPTURING")
    other_pool = await make_scene(db_session, status="CAPTURING")
    foreign_capture = await insert_capture(other_pool.session, other_pool.order_id)
    await insert_paypal_order(db_session, scene.order_id)
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="CAPTURED",
                trigger=trigger_for("BO-07"),
                observation=Observation(
                    "capture", "COMPLETED", foreign_capture, amount_cents=50_000
                ),
            ),
        )
    assert len(capture.records) == 1
    assert "does not own" in capture.records[0][0].getMessage()
    assert scene.ports.ledger.entries == []
    assert scene.ports.audit.rows == []


def test_alert_line_carries_no_secret(capture: _Capture) -> None:
    """T03A01 acceptance 4 (I14): the alert names ids only, never a body."""
    correlation.lot_id.set("11111111-1111-4111-8111-111111111111")
    from fairpool.modules.checkout.engine import alert_illegal_transition

    alert_illegal_transition(
        machine="buyer_order",
        from_state="AUTHORIZED",
        to_state="OFFERED",
        trigger="job:void.run",
        reason="the pair is not in the whitelist (I10)",
        lot_id=None,
        buyer_order_id=None,
        pool_id=None,
    )
    assert len(capture.records) == 1
    record, _ = capture.records[0]
    line = record.getMessage()
    assert redact_text(line) == line
    for attribute in ("approval_url", "payment_token", "client_secret", "raw_body"):
        assert attribute not in record.__dict__
    correlation.lot_id.set(None)
