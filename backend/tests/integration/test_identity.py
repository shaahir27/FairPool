import pytest
from sqlalchemy import text

from fairpool.domain.errors import ApplicationError
from fairpool.infra.clock import DbClock
from fairpool.modules.identity.service import IdentityService
from fairpool.modules.notify.service import PostgresNotifier


async def test_sessions_are_signed_expiring_revocable_and_csrf_bound(db_session):
    service = IdentityService("test-signing-key", DbClock())
    user = await service.register(
        db_session, email="person@example.test", password="a safe password", display_name="Person"
    )
    assert user["role"] == "buyer"
    login = await service.login(db_session, email="PERSON@example.test", password="a safe password")
    principal = await service.authenticate(db_session, login.cookie)
    assert principal.user_id == user["user_id"]
    assert await service.authenticate(db_session, login.cookie, csrf=login.csrf_token, unsafe=True)
    with pytest.raises(ApplicationError):
        await service.authenticate(db_session, login.cookie + "changed")
    with pytest.raises(ApplicationError):
        await service.authenticate(db_session, login.cookie, csrf="wrong", unsafe=True)
    with pytest.raises(ApplicationError):
        await service.login(db_session, email="person@example.test", password="wrong password")
    await PostgresNotifier().notify(
        db_session, user_id=principal.user_id, kind="test", payload={"ok": True}
    )
    assert (await service.me(db_session, principal))["unread_notifications"] == 1
    await service.logout(db_session, principal)
    with pytest.raises(ApplicationError):
        await service.authenticate(db_session, login.cookie)
    second = await service.login(
        db_session, email="person@example.test", password="a safe password"
    )
    await db_session.execute(
        text("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE user_id=:id"),
        {"id": principal.user_id},
    )
    with pytest.raises(ApplicationError):
        await service.authenticate(db_session, second.cookie)
