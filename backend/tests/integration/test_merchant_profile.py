"""T05A06: merchant profile, the three attestations and the merchant-row gate."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.deps import require_merchant
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import Principal
from fairpool.modules.merchants.profile import ATTESTATION_KEYS, MerchantProfileService

pytestmark = pytest.mark.integration


async def merchant_user(session: AsyncSession, *, role: str = "merchant") -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO users (id, email, password_hash, display_name, role) "
            "VALUES (:id, :email, 'hash', 'Merchant', :role)"
        ),
        {"id": user_id, "email": f"merchant-{user_id}@example.test", "role": role},
    )
    await session.flush()
    return user_id


def principal(user_id: UUID, *, role: str = "merchant") -> Principal:
    return Principal(user_id=user_id, session_id=uuid4(), role=role)


async def test_profile_is_created_as_demo_with_three_timestamps(db_session: AsyncSession) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    merchant = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email="seller@example.test",
        paypal_merchant_id=None,
        attestations={key: {"accepted": True} for key in ATTESTATION_KEYS},
    )
    assert merchant.onboarding_status == "DEMO"
    for key in ATTESTATION_KEYS:
        assert merchant.attestations[key]["accepted"] is True
        assert isinstance(merchant.attestations[key]["at"], str)


async def test_an_accepted_attestation_keeps_its_first_timestamp(
    db_session: AsyncSession,
) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    first = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={"inventory_reserved": {"accepted": True}},
    )
    original = first.attestations["inventory_reserved"]["at"]
    again = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={"inventory_reserved": {"accepted": True}},
    )
    assert again.attestations["inventory_reserved"]["at"] == original


async def test_an_unknown_attestation_is_rejected(db_session: AsyncSession) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    with pytest.raises(Exception) as caught:
        await service.upsert(
            db_session,
            user_id=user_id,
            display_name="Demo Merchant Alpha",
            payee_email=None,
            paypal_merchant_id=None,
            attestations={"not_a_thing": {"accepted": True}},
        )
    assert "VALIDATION_ERROR" in str(caught.value)


async def test_the_role_alone_does_not_pass_the_merchant_gate(db_session: AsyncSession) -> None:
    user_id = await merchant_user(db_session)
    with pytest.raises(HTTPException) as caught:
        await require_merchant(principal(user_id), db_session)
    assert caught.value.status_code == 403


async def test_a_merchant_with_a_profile_passes_the_gate(db_session: AsyncSession) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={},
    )
    result = await require_merchant(principal(user_id), db_session)
    assert result.user_id == user_id
