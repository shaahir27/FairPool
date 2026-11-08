"""T09A05 / audit F5: a lot's money balances across two independent records.

A completed capture and the ledger fact that records it are written by different code on
different paths, so "they agree" is a claim that needs checking rather than assuming. This
test forces the disagreement both ways: a capture with no ledger fact must raise
``ledger_imbalance`` on the ops alert list, and adding the matching fact must clear it.
Without the negative case an always-empty query looks exactly like a correct one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.modules.checkout import ops
from tests.integration.test_ops_views import first_order_id, seated_world

pytestmark = pytest.mark.integration

CAPTURE_CENTS = 50000


async def _capture(session: AsyncSession, buyer_order_id: object) -> None:
    await session.execute(
        text(
            "INSERT INTO paypal_captures (id, buyer_order_id, paypal_capture_id, status, "
            "amount_cents, final_capture, raw) VALUES (:id, :bo, :ref, 'COMPLETED', "
            ":amount, true, '{}'::jsonb)"
        ),
        {
            "id": uuid4(),
            "bo": buyer_order_id,
            "ref": f"CAP-{uuid4()}",
            "amount": CAPTURE_CENTS,
        },
    )
    await session.flush()


async def _ledger(session: AsyncSession, lot_id: object, buyer_order_id: object) -> None:
    await session.execute(
        text(
            "INSERT INTO ledger_entries (id, lot_id, buyer_order_id, kind, amount_cents, "
            "paypal_ref, idempotency_key, source) VALUES (:id, :lot, :bo, "
            "'CAPTURE_COMPLETED', :amount, :ref, :key, 'api')"
        ),
        {
            "id": uuid4(),
            "lot": lot_id,
            "bo": buyer_order_id,
            "amount": CAPTURE_CENTS,
            "ref": f"CAP-{uuid4()}",
            "key": f"f5-{uuid4()}",
        },
    )
    await session.flush()


def _imbalances(payload: dict) -> list[dict]:
    return [row for row in payload["alerts"] if row["kind"] == "ledger_imbalance"]


async def test_a_capture_without_its_ledger_fact_is_an_imbalance(
    db_session: AsyncSession,
) -> None:
    world = await seated_world(db_session)
    buyer_order_id = await first_order_id(db_session, world.lot_id)
    # Only ended lots are compared: one mid-flight legitimately has captures the ledger
    # has not been told about yet.
    await db_session.execute(
        text("UPDATE lots SET status = 'FUNDED' WHERE id = :lot"), {"lot": world.lot_id}
    )
    await db_session.flush()

    await _capture(db_session, buyer_order_id)
    reported = _imbalances(await ops.alerts(db_session))
    assert len(reported) == 1, reported
    row = reported[0]
    assert row["lot_id"] == str(world.lot_id)
    assert row["captured_net_cents"] == CAPTURE_CENTS
    assert row["ledger_net_cents"] == 0
    assert row["difference_cents"] == CAPTURE_CENTS

    # The matching ledger fact clears it: same money, two records, now agreeing.
    await _ledger(db_session, world.lot_id, buyer_order_id)
    assert _imbalances(await ops.alerts(db_session)) == []


async def test_a_lot_still_in_flight_is_not_compared(db_session: AsyncSession) -> None:
    world = await seated_world(db_session)
    buyer_order_id = await first_order_id(db_session, world.lot_id)
    await _capture(db_session, buyer_order_id)
    # seated_world leaves the lot before FUNDED, so an unrecorded capture is expected.
    assert _imbalances(await ops.alerts(db_session)) == []
