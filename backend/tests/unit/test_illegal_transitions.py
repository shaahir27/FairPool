"""T03A01 acceptance 4 / CR-3 note 5: an unlisted transition is refused and alerted (I10).

`test_state_machines_contract.py` proves the table in `domain/states.py` equals the
YAML in `docs/contracts/state-machines.md`. This file proves the behaviour the Phase 3
handlers depend on: a pair the whitelist does not list raises for every machine, the
refusal names the machine and the pair so an operator can see which edge was asked
for, a listed pair stays reachable with its trigger, and the shared alert path writes
exactly one structured ERROR record carrying the machine, the pair, the attempted
trigger and the correlation ids (the same path the job runner's retry-exhaustion
alert uses).

The pairs below are the mis-sequencings a Phase 3 handler could actually reach for:
closing a pool that never opened, un-withdrawing an entry, awarding a lot that never
bidded, capturing an order that was never authorized.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest

from fairpool.domain.errors import IllegalTransition
from fairpool.domain.states import MACHINES, assert_transition, is_legal
from fairpool.logging import CORRELATION_FIELDS, JsonFormatter, lot_id, pool_id
from fairpool.modules.checkout.engine import alert_illegal_transition

ALERT_LOGGER = "fairpool.checkout.engine"

#: (machine, from_state, to_state) pairs the whitelist must not contain.
UNLISTED_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("pool", "PUBLISHED", "CLOSED"),  # PS-03 starts at OPEN, never at PUBLISHED
    ("pool", "OPEN", "ALLOCATED"),  # seeding and the beacon round come between
    ("pool", "CLOSED", "OPEN"),  # a closed pool does not reopen
    ("entry", "ELIGIBLE", "WITHDRAWN"),  # ES-03 starts at SUBMITTED only
    ("entry", "WITHDRAWN", "ELIGIBLE"),  # a withdrawal is never reversed
    ("lot", "PLANNED", "FUNDING"),  # checkout opens only after an award
    ("buyer_order", "OFFERED", "CAPTURED"),  # money exists only after authorize
    ("buyer_order", "CAPTURED", "OFFERED"),  # a capture is terminal for the offer
)

#: Listed pairs, kept as controls so the refusals above are about the whitelist and
#: not about a broken lookup.
LISTED_PAIRS: tuple[tuple[str, str, str, str], ...] = (
    ("pool", "PUBLISHED", "OPEN", "job:pool.open"),
    ("entry", "SUBMITTED", "ELIGIBLE", "job:pool.close"),
    ("lot", "PLANNED", "BIDDING", "job:lot.bid_open"),
    ("lot", "PLANNED", "AWARDED", "admin.force_award"),
)


@pytest.mark.parametrize(("machine", "from_state", "to_state"), UNLISTED_PAIRS)
def test_an_unlisted_pair_raises_on_its_machine(
    machine: str, from_state: str, to_state: str
) -> None:
    assert machine in MACHINES, machine
    with pytest.raises(IllegalTransition):
        assert_transition(machine, from_state, to_state)
    assert is_legal(machine, from_state, to_state) is False


@pytest.mark.parametrize(("machine", "from_state", "to_state", "trigger"), LISTED_PAIRS)
def test_a_listed_pair_stays_reachable_with_its_trigger(
    machine: str, from_state: str, to_state: str, trigger: str
) -> None:
    transition = assert_transition(machine, from_state, to_state, trigger=trigger)
    assert transition.from_states and transition.to_state == to_state


def test_the_refusal_names_the_machine_and_the_pair() -> None:
    with pytest.raises(IllegalTransition) as raised:
        assert_transition("pool", "PUBLISHED", "CLOSED")

    message = str(raised.value)
    assert "pool" in message and "PUBLISHED" in message and "CLOSED" in message


class _Capture(logging.Handler):
    """The alert record as a handler sees it, plus the JSON line it becomes."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.lines: list[str] = []
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.lines.append(JsonFormatter().format(record))


@pytest.fixture
def capture() -> Iterator[_Capture]:
    handler = _Capture()
    logger = logging.getLogger(ALERT_LOGGER)
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def test_the_alert_writes_one_structured_error_record(capture: _Capture) -> None:
    """CR-3 note 5: machine, pair, attempted trigger and the correlation ids."""
    subject: UUID = uuid4()
    token = pool_id.set(str(subject))
    try:
        alert_illegal_transition(
            machine="pool",
            from_state="PUBLISHED",
            to_state="CLOSED",
            trigger="job:pool.close",
            reason="handler asked for an edge the whitelist does not list",
            pool_id=subject,
        )
    finally:
        pool_id.reset(token)
    # Replays of the same refusal do not merge: one call, one record, no dedupe.
    assert len(capture.records) == 1
    record = capture.records[0]
    assert record.levelname == "ERROR"
    assert record.machine == "pool"
    assert record.from_state == "PUBLISHED"
    assert record.to_state == "CLOSED"
    assert record.trigger == "job:pool.close"

    payload = json.loads(capture.lines[0])
    assert payload["pool_id"] == str(subject)
    assert payload["level"] == "ERROR"
    assert "machine=pool" in payload["message"]
    assert "from_state=PUBLISHED" in payload["message"]
    assert "to_state=CLOSED" in payload["message"]
    assert "trigger=job:pool.close" in payload["message"]
    # Only ids and the pair travel: no order, no reference, no credential-shaped key.
    assert set(payload) <= {"timestamp", "level", "logger", "message", *CORRELATION_FIELDS}


def test_the_alert_carries_no_correlation_id_when_none_is_set(capture: _Capture) -> None:
    alert_illegal_transition(
        machine="buyer_order",
        from_state="CAPTURED",
        to_state="OFFERED",
        trigger=None,
        reason="replay",
        buyer_order_id=uuid4(),
    )
    assert len(capture.records) == 1
    payload = json.loads(capture.lines[0])
    assert "pool_id" not in payload and "lot_id" not in payload
    assert payload["buyer_order_id"]
    assert "trigger=none" in payload["message"]
    assert lot_id.get() is None
