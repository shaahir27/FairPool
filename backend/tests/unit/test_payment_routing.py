"""Network routing refuses simulated pools even when a lot was mis-stamped."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.domain.errors import ApplicationError
from fairpool.modules.checkout.routing import require_payment_router


@pytest.mark.parametrize("stored", [("single_seller", "SIMULATION"), ("fake", "LIVE_SANDBOX")])
async def test_network_gateway_cannot_process_offline_data(stored: tuple[str, str]) -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.first.return_value = stored
    session.execute.return_value = result
    with pytest.raises(ApplicationError) as caught:
        await require_payment_router(session, lot_id=uuid4(), router_name="single_seller")
    assert caught.value.code == "FEATURE_DISABLED"


async def test_offline_gateway_cannot_process_a_real_stamped_lot() -> None:
    session = AsyncMock(spec=AsyncSession)
    result = MagicMock()
    result.first.return_value = ("single_seller", "LIVE_SANDBOX")
    session.execute.return_value = result
    with pytest.raises(ApplicationError) as caught:
        await require_payment_router(session, lot_id=uuid4(), router_name="fake")
    assert caught.value.code == "ORDER_STATE_INVALID"
