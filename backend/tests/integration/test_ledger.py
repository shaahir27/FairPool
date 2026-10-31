import pytest
from sqlalchemy import text

from fairpool.modules.ledger.service import PostgresLedger
from tests.integration.test_triggers import add_buyer_order, add_entry, add_lot, add_pool


async def test_ledger_exact_net_distinct_buyers_dedupe_and_association(db_session):
    ledger = PostgresLedger()
    pool = await add_pool(db_session)
    lot = await add_lot(db_session, pool)
    other = await add_lot(db_session, pool, lot_index=1, lot_order=1)
    entry = await add_entry(db_session, pool)
    order = await add_buyer_order(db_session, lot, entry)
    kwargs = dict(
        lot_id=lot, buyer_order_id=order, amount_cents=12345, paypal_ref="CAP", source="api"
    )
    assert await ledger.record(
        db_session, **kwargs, kind="CAPTURE_COMPLETED", idempotency_key="one"
    )
    assert not await ledger.record(
        db_session, **kwargs, kind="CAPTURE_COMPLETED", idempotency_key="one"
    )
    await ledger.record(
        db_session, **{**kwargs, "amount_cents": 45}, kind="REFUND_COMPLETED", idempotency_key="two"
    )
    await ledger.record(db_session, **kwargs, kind="CAPTURE_PENDING", idempotency_key="three")
    await ledger.record(db_session, **kwargs, kind="CAPTURE_DECLINED", idempotency_key="four")
    assert await ledger.net_paid_cents(db_session, lot) == 12300
    assert await ledger.completed_capture_count(db_session, lot) == 1
    with pytest.raises(ValueError):
        await ledger.record(
            db_session,
            **{**kwargs, "lot_id": other},
            kind="CAPTURE_COMPLETED",
            idempotency_key="bad",
        )
    with pytest.raises(ValueError):
        await ledger.record(
            db_session,
            **{**kwargs, "amount_cents": 1},
            kind="CAPTURE_COMPLETED",
            idempotency_key="one",
        )
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await ledger.record(
                db_session, **kwargs, kind="CAPTURE_COMPLETED", idempotency_key="rollback"
            )
            raise RuntimeError()
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM ledger_entries WHERE idempotency_key='rollback'")
        )
        == 0
    )


async def test_concurrent_duplicate_ledger_insert_is_one_fact(db_engine):
    import asyncio
    from uuid import uuid4

    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    ledger = PostgresLedger()
    async with factory.begin() as db:
        pool = await add_pool(db)
        lot = await add_lot(db, pool)
        entry = await add_entry(db, pool)
        order = await add_buyer_order(db, lot, entry)
    key = f"concurrent-{uuid4()}"

    async def insert():
        async with factory.begin() as db:
            return await ledger.record(
                db,
                lot_id=lot,
                buyer_order_id=order,
                kind="CAPTURE_COMPLETED",
                amount_cents=100,
                paypal_ref="CAP",
                idempotency_key=key,
                source="api",
            )

    assert sorted(await asyncio.gather(insert(), insert())) == [False, True]
    async with factory() as db:
        assert await ledger.net_paid_cents(db, lot) == 100
        assert await ledger.completed_capture_count(db, lot) == 1
