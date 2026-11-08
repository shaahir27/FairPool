"""F29: a double click or two tabs still creates one provider order (I9).

Both clicks enter ``buyer.continue`` at the same time. The engine's guard takes the
lot and buyer-order row locks (``engine.decide``), so the second click waits at BO-01
until the first commits; it then reads ORDER_CREATED and answers from the stored
``paypal_orders`` row. The provider is called once under ``create:{order}:0``, the
database holds one row for that attempt, and neither tab gets an error. Money never
moves here; the state guard is what makes the second click safe.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fairpool.db.session import normalize_database_url
from fairpool.modules.allocation.read_service import PostgresAllocationRead
from fairpool.modules.checkout.authorize import CheckoutAuthorizeHandlers
from tests.conftest import database_url
from tests.integration.test_open_checkout import (
    World,
    build_world,
    make_directory,
    make_router,
    open_handler,
)

pytestmark = pytest.mark.concurrency


@pytest.fixture
async def engine() -> AsyncEngine:
    parsed, connect_args = normalize_database_url(database_url())
    created = create_async_engine(
        parsed, connect_args=connect_args, pool_size=5, max_overflow=5, pool_timeout=60
    )
    try:
        yield created
    finally:
        await created.dispose()


async def test_f29_double_click_two_tabs_one_order(engine: AsyncEngine) -> None:
    """F29 (I9): two concurrent continues produce one provider order and one row."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        world = await build_world(session, seats=1, seated=1, waitlisted=0, moq=1)
        await open_handler(world).open(session, {"lot_id": str(world.lot_id)})
        await session.commit()
    order_id = uuid.UUID(
        str(
            await _scalar(
                maker, "SELECT id FROM buyer_orders WHERE lot_id = :lot", {"lot": world.lot_id}
            )
        )
    )

    router = make_router()
    handler = CheckoutAuthorizeHandlers(
        engine=world.ports.engine,
        clock=world.ports.clock,
        jobs=world.ports.jobs,
        allocations=PostgresAllocationRead(),
        directory=make_directory(world.merchant_id),
        router=router,
        hmac_key="test-hmac-key",
        allowed_payer_countries=("US",),
        dedupe_mode="two_keys",
        public_base_url="https://app.test",
    )

    async def click() -> object:
        async with maker() as session, session.begin():
            return await handler.continue_order(session, buyer_order_id=order_id)

    results = await asyncio.gather(click(), click(), return_exceptions=True)

    try:
        failures = [item for item in results if isinstance(item, BaseException)]
        assert not failures, f"a double click must not fail a tab: {failures!r}"
        ids = {str(item["paypal_order_id"]) for item in results}  # type: ignore[index]
        assert len(ids) == 1, "both tabs must show the one provider order"
        assert (
            await _scalar(
                maker,
                "SELECT count(*) FROM paypal_orders WHERE buyer_order_id = :id",
                {"id": order_id},
            )
            == 1
        )
        assert len(router.gateway.orders) == 1
        assert f"create:{order_id}:0" in router.gateway.replays
        # A third click after the row settled is the same answer, still one row.
        third = await click()
        assert str(third["paypal_order_id"]) in ids  # type: ignore[index]
        assert (
            await _scalar(
                maker,
                "SELECT count(*) FROM paypal_orders WHERE buyer_order_id = :id",
                {"id": order_id},
            )
            == 1
        )
        assert (
            await _scalar(
                maker,
                "SELECT status::text FROM buyer_orders WHERE id = :id",
                {"id": order_id},
            )
            == "ORDER_CREATED"
        )
    finally:
        await _wipe(engine, world)


async def _scalar(
    maker: async_sessionmaker[AsyncSession], sql: str, params: dict[str, object]
) -> object:
    async with maker() as session:
        return await session.scalar(text(sql), params)


async def _wipe(engine: AsyncEngine, world: World) -> None:
    """Delete the rows a rollback would have removed.

    ``awards`` is append-only by trigger (db-schema.md), so the lot and its pool
    cannot be deleted once an award exists. The per-order rows go; the award and its
    parents stay, as every other committed-award test leaves them.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM paypal_orders WHERE buyer_order_id IN "
                "(SELECT id FROM buyer_orders WHERE lot_id = :lot)"
            ),
            {"lot": world.lot_id},
        )
        await conn.execute(
            text("DELETE FROM buyer_orders WHERE lot_id = :lot"), {"lot": world.lot_id}
        )
        await conn.execute(
            text("DELETE FROM allocations WHERE lot_id = :lot"), {"lot": world.lot_id}
        )
        # The award is append-only, so the lot stays; move it off CHECKOUT_OPEN so a
        # later test's global alert query cannot see this committed fixture as overdue.
        await conn.execute(
            text(
                "UPDATE lots SET status = 'CANCELLED'::lot_status, fund_deadline_at = NULL "
                "WHERE id = :lot"
            ),
            {"lot": world.lot_id},
        )
