"""T01A02: fake ledger netting and distinct-buyer counts (I4, I5)."""

from __future__ import annotations

from uuid import uuid4

from fairpool.fakes.ledger import FakeLedger


async def test_fake_ledger_counts_completed_captures_and_net_paid():
    ledger = FakeLedger()
    lot = uuid4()
    buyer_one = uuid4()
    buyer_two = uuid4()

    async def record(buyer, kind, amount, key):
        return await ledger.record(
            None,  # type: ignore[arg-type]
            lot_id=lot,
            buyer_order_id=buyer,
            kind=kind,
            amount_cents=amount,
            paypal_ref=key,
            idempotency_key=key,
            source="api",
        )

    assert await record(buyer_one, "CAPTURE_COMPLETED", 50_000, "cap-1")
    assert not await record(buyer_one, "CAPTURE_COMPLETED", 50_000, "cap-1")
    assert await record(buyer_two, "CAPTURE_COMPLETED", 50_000, "cap-2")
    assert await record(buyer_one, "CAPTURE_PENDING", 10_000, "pending-1")
    assert await record(buyer_two, "CAPTURE_DECLINED", 10_000, "declined-1")

    assert await ledger.net_paid_cents(None, lot) == 100_000  # type: ignore[arg-type]
    assert await ledger.completed_capture_count(None, lot) == 2  # type: ignore[arg-type]

    assert await record(buyer_two, "REFUND_COMPLETED", 50_000, "refund-1")
    assert await ledger.net_paid_cents(None, lot) == 50_000  # type: ignore[arg-type]
    assert await ledger.completed_capture_count(None, lot) == 2  # type: ignore[arg-type]
