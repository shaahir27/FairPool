"""T05A06: merchant profile, the three attestations and the merchant-row gate."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session, require_merchant
from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import Principal
from fairpool.modules.merchants.profile import ATTESTATION_KEYS, MerchantProfileService
from tests.integration.test_join_receipts import PASSWORD, login, settings_for

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


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings_for())

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def test_the_profile_route_keeps_fields_the_request_omits(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A later save without a payee must not overwrite the stored payee or attestations."""
    email = "profile-keeper@example.test"
    await login(client, email)
    await db_session.execute(
        text("UPDATE users SET role = 'merchant' WHERE email = :email"), {"email": email}
    )
    await db_session.flush()
    signed_in = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    csrf = str(signed_in.json()["csrf_token"])
    headers = {"X-CSRF-Token": csrf}

    first = await client.post(
        "/api/v1/merchant/profile",
        headers=headers,
        json={
            "display_name": "Keeper",
            "payee_email": "seller@example.test",
            "paypal_merchant_id": "MERCHANT-1",
            "attestations": {key: {"accepted": True} for key in ATTESTATION_KEYS},
        },
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/v1/merchant/profile",
        headers=headers,
        json={"display_name": "Keeper renamed"},
    )
    assert second.status_code == 200, second.text

    row = await db_session.execute(
        text(
            "SELECT m.payee_email, m.paypal_merchant_id, m.attestations "
            "FROM merchants m JOIN users u ON u.id = m.user_id WHERE u.email = :email"
        ),
        {"email": email},
    )
    stored = row.mappings().one()
    assert stored["payee_email"] == "seller@example.test"
    assert stored["paypal_merchant_id"] == "MERCHANT-1"
    for key in ATTESTATION_KEYS:
        assert stored["attestations"][key]["accepted"] is True


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


async def test_absent_payee_fields_and_attestations_keep_the_stored_row(
    db_session: AsyncSession,
) -> None:
    """A save that omits a field must not erase what the merchant already recorded."""
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email="seller@example.test",
        paypal_merchant_id="MERCHANT-1",
        attestations={key: {"accepted": True} for key in ATTESTATION_KEYS},
    )
    kept = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={},
        present={"display_name"},
    )
    assert kept.payee_email == "seller@example.test"
    assert kept.paypal_merchant_id == "MERCHANT-1"
    for key in ATTESTATION_KEYS:
        assert kept.attestations[key]["accepted"] is True


async def test_an_explicit_null_clears_only_the_sent_payee_field(
    db_session: AsyncSession,
) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email="seller@example.test",
        paypal_merchant_id="MERCHANT-1",
        attestations={"inventory_reserved": {"accepted": True}},
    )
    cleared = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={},
        present={"payee_email"},
    )
    assert cleared.payee_email is None
    assert cleared.paypal_merchant_id == "MERCHANT-1"
    assert cleared.attestations["inventory_reserved"]["accepted"] is True


async def test_a_non_boolean_answer_is_not_an_attestation(db_session: AsyncSession) -> None:
    """A merchant's word is a yes or a no: ``"false"`` must not read as accepted."""
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    with pytest.raises(ApplicationError) as caught:
        await service.upsert(
            db_session,
            user_id=user_id,
            display_name="Demo Merchant Alpha",
            payee_email=None,
            paypal_merchant_id=None,
            attestations={"map_compliance": {"accepted": "false"}},
        )
    assert caught.value.code == "VALIDATION_ERROR"


async def test_a_declined_attestation_is_stored_as_declined(db_session: AsyncSession) -> None:
    user_id = await merchant_user(db_session)
    service = MerchantProfileService(clock=DbClock(), demo=True)
    merchant = await service.upsert(
        db_session,
        user_id=user_id,
        display_name="Demo Merchant Alpha",
        payee_email=None,
        paypal_merchant_id=None,
        attestations={"map_compliance": {"accepted": False}},
    )
    assert merchant.attestations["map_compliance"]["accepted"] is False


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
