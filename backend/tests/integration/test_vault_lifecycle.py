"""T03B04 CR-3: the fake vault permission lifecycle (consent, ACTIVE, quarantine, delete).

Order in time is the contract (``vault-charge.md`` §4, ``DEP-5``):
``manual confirmation -> SUBMITTED entry and receipt -> consent and save -> ACTIVE
permission -> close-time eligibility``. Phase 3 ships no real save path, so every
ACTIVE permission here comes from the injected ``FakePaymentVaultProvider``.

The tests also pin the credential rules (rule 27): the payment token id appears in
no response body, log record, audit payload, notification or search document;
buyers see four characters; no provider step runs while a pool or entry lock is
held; and the fake builds no network client at all (I12, I14).
"""

from __future__ import annotations

import ast
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.errors import ApplicationError
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.vault import INVALID_HOST, FakePaymentVaultProvider
from fairpool.infra.clock import DbClock
from fairpool.infra.crypto import AesGcmCipher, key_from_config_value
from fairpool.logging import JsonFormatter, RedactionFilter
from fairpool.modules.pools.vault import VaultProviderUnknown, VaultService, consent_text_sha256
from fairpool.ports import PaymentVaultProvider
from tests.integration.test_close_commitments import (
    add_buyer,
    insert_pool,
    joined_entry,
    run_close,
    set_close_in_the_past,
)
from tests.integration.test_join_receipts import (
    join_service,
    login,
    manual_confirm,
    settings_for,
    wipe_join_data,
)
from tests.integration.test_triggers import iso_in
from tests.unit.test_settings import vault_key

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "backend" / "src" / "fairpool"
TOKEN_PREFIX = "fake-payment-token-"
SETUP_PREFIX = "fake-setup-token-"
ENTRY_COLUMNS = (
    "status, cap_cents, consent_version, consent_text_sha256, consented_at, deleted_at, "
    "token_label, token_ciphertext, token_nonce"
)


def cipher() -> AesGcmCipher:
    return AesGcmCipher(key_from_config_value(vault_key()))


def decrypt(nonce: Any, ciphertext: Any) -> str:
    return cipher().open(bytes(nonce), bytes(ciphertext))


def service(
    provider: FakePaymentVaultProvider | None = None, *, real_save_enabled: bool = True
) -> VaultService:
    return VaultService(
        DbClock(),
        FakeAuditLog(),
        cipher(),
        provider or FakePaymentVaultProvider(),
        consent_version="v1",
        setup_ttl_s=900,
        real_save_enabled=real_save_enabled,
    )


def vault_client(
    db: AsyncSession, *, provider: FakePaymentVaultProvider | None = None, enabled: bool = True
) -> httpx.AsyncClient:
    app = create_app(
        settings_for(
            payment_mode="vault_charge",
            vault_token_key=vault_key(),
            vault_real_save_enabled=enabled,
        )
    )
    # Phase 3 has no real provider implementation: the route is handed the fake (DEP-5).
    app.state.vault_provider = provider or FakePaymentVaultProvider()

    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[database_session] = session
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://api.test")


@pytest.fixture
async def live_client(db_session: AsyncSession) -> AsyncIterator[dict[str, Any]]:
    """An enabled vault client plus its scripted fake and the shared session."""
    provider = FakePaymentVaultProvider()
    client = vault_client(db_session, provider=provider)
    async with client:
        yield {"client": client, "provider": provider, "db": db_session}


async def entered(
    client: httpx.AsyncClient, db: AsyncSession, email: str, *, cap: int = 60000
) -> tuple[str, uuid.UUID, uuid.UUID]:
    """Up to the join: confirmation, then a SUBMITTED entry with its signed receipt."""
    csrf = await login(client, email)
    user_id = uuid.UUID((await client.get("/api/v1/me")).json()["user_id"])
    pool_id = await insert_pool(db)
    confirmed = await manual_confirm(db, user_id, pool_id, max_total_cents=cap)
    outcome = await join_service().join(
        db,
        pool_id=pool_id,
        user_id=user_id,
        confirmed_request_id=confirmed,
        idempotency_key=f"vault-join-{email}",
    )
    return csrf, pool_id, uuid.UUID(str(outcome.body["entry_id"]))


async def attempt_rows(db: AsyncSession, entry_id: uuid.UUID) -> list[Any]:
    return list(
        (
            await db.execute(
                text(
                    "SELECT operation_key, status, consumed_at, last_error "
                    "FROM vault_setup_attempts WHERE entry_id = :e"
                ),
                {"e": entry_id},
            )
        ).all()
    )


async def token_row(db: AsyncSession, entry_id: uuid.UUID) -> Any:
    return (
        await db.execute(
            text(f"SELECT {ENTRY_COLUMNS} FROM vault_tokens WHERE entry_id = :e"), {"e": entry_id}
        )
    ).first()


async def start(client: httpx.AsyncClient, csrf: str, entry_id: uuid.UUID) -> httpx.Response:
    return await client.post(
        f"/api/v1/entries/{entry_id}/vault",
        json={"consent_version": "v1", "cap_cents": 60000},
        headers={"X-CSRF-Token": csrf},
    )


async def reject_status(db: AsyncSession, entry_id: uuid.UUID) -> tuple[str, str | None]:
    row = (
        await db.execute(
            text("SELECT status, reject_reason FROM pool_entries WHERE id = :e"), {"e": entry_id}
        )
    ).first()
    return str(row[0]), row[1]


# ---------------------------------------------------------------- feature gate


async def test_real_save_disabled_answers_feature_disabled_and_writes_no_half_state(
    db_session: AsyncSession,
) -> None:
    """DEP-5: a consented-but-unsaved permission must not be able to exist."""
    provider = FakePaymentVaultProvider()
    client = vault_client(db_session, provider=provider, enabled=False)
    async with client:
        csrf, _, entry_id = await entered(client, db_session, "vault-off@example.test")
        response = await start(client, csrf, entry_id)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert await attempt_rows(db_session, entry_id) == []
    assert await token_row(db_session, entry_id) is None
    assert provider.calls == []
    # The entry is still only a SUBMITTED entry: nothing about it moved.
    assert await reject_status(db_session, entry_id) == ("SUBMITTED", None)


# ------------------------------------------------------- consent, save, ACTIVE


async def test_start_records_the_consent_and_one_attempt_that_owns_the_identity(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="consent")
    cap = int(
        await db_session.scalar(
            text("SELECT cap_cents FROM pool_entries WHERE id = :e"), {"e": entry_id}
        )
    )
    provider = FakePaymentVaultProvider()
    subject = service(provider)

    redirect = await subject.start(db_session, entry_id=entry_id)

    rows = await attempt_rows(db_session, entry_id)
    assert len(rows) == 1
    operation_key, status, consumed, last_error = rows[0]
    # One row owns the identity of both provider steps for this attempt (CR-3).
    assert operation_key == f"vs:{entry_id}:1"
    assert status == "PENDING" and consumed is None and last_error is None
    stored = (
        await db_session.execute(
            text(
                "SELECT provider_setup_nonce, provider_setup_ciphertext "
                "FROM vault_setup_attempts WHERE entry_id = :e"
            ),
            {"e": entry_id},
        )
    ).first()
    assert decrypt(stored[0], stored[1]) == redirect.setup_token_id
    assert redirect.setup_token_id == f"{SETUP_PREFIX}{entry_id}"

    row = await token_row(db_session, entry_id)
    (
        token_status,
        token_cap,
        consent_version,
        consent_hash,
        consented_at,
        deleted_at,
        label,
        ciphertext,
        nonce,
    ) = row
    assert token_status == "SETUP_PENDING"
    # Cap, version, SHA-256 of the exact rendered text and the time are recorded here;
    # the pool is carried by the entry (vault-charge.md §6, db-schema.md).
    assert token_cap == cap and consented_at is not None and deleted_at is None
    assert consent_version == "v1" and consent_hash == consent_text_sha256("v1", cap)
    assert label is None and ciphertext is None and nonce is None

    # Reopening reuses that row and its identity: still one row, one operation key.
    again = await subject.start(db_session, entry_id=entry_id)
    assert again.setup_token_id == redirect.setup_token_id
    assert [item[0] for item in await attempt_rows(db_session, entry_id)] == [f"vs:{entry_id}:1"]
    assert provider.calls.count(f"start_setup:{entry_id}") == 2


async def test_return_exchanges_the_stored_setup_token_and_activates_a_label_only(
    live_client: dict[str, Any],
) -> None:
    client, db = live_client["client"], live_client["db"]
    csrf, _, entry_id = await entered(client, db, "vault-active@example.test")

    started = await start(client, csrf, entry_id)
    assert started.status_code == 200, started.text
    assert sorted(started.json()) == ["approve_url", "consent_version"]
    assert started.json()["consent_version"] == "v1"
    # A local, inert URL on the RFC 2606 reserved host: nothing here can call a host.
    assert started.json()["approve_url"].startswith(INVALID_HOST)

    returned = await client.get(f"/api/v1/entries/{entry_id}/vault/return")
    assert returned.status_code == 302
    assert returned.headers["location"] == f"http://localhost:5173/entries/{entry_id}"
    assert returned.text == ""

    row = await token_row(db, entry_id)
    assert row[0] == "ACTIVE"
    assert row[6] == f"{entry_id}"[-4:]  # the label is the last four characters
    assert decrypt(row[8], row[7]) == f"{TOKEN_PREFIX}{entry_id}"
    assert (await attempt_rows(db, entry_id))[0][1] == "EXCHANGED"
    assert (await attempt_rows(db, entry_id))[0][2] is not None

    payloads = (
        (
            await db.execute(
                text("SELECT payload::text FROM audit_log WHERE subject_id = :e"),
                {"e": str(entry_id)},
            )
        )
        .scalars()
        .all()
    )
    assert payloads
    for payload in payloads:
        assert TOKEN_PREFIX not in str(payload)
    assert any(row[6] in str(payload) for payload in payloads)


async def test_two_callbacks_cannot_both_exchange(live_client: dict[str, Any]) -> None:
    client, db, provider = live_client["client"], live_client["db"], live_client["provider"]
    csrf, _, entry_id = await entered(client, db, "vault-double@example.test")
    await start(client, csrf, entry_id)

    first = await client.get(f"/api/v1/entries/{entry_id}/vault/return")
    second = await client.get(f"/api/v1/entries/{entry_id}/vault/return")

    assert first.status_code == 302 and second.status_code == 302
    # Exactly one exchange ran: the second callback found the row already fenced.
    assert provider.calls.count(f"exchange:{entry_id}") == 1
    assert (
        await db.scalar(
            text("SELECT count(*) FROM vault_tokens WHERE status = 'ACTIVE' AND entry_id = :e"),
            {"e": entry_id},
        )
        == 1
    )


async def test_the_query_string_is_never_authority_for_anything(
    live_client: dict[str, Any],
) -> None:
    client, db, provider = live_client["client"], live_client["db"], live_client["provider"]
    csrf, _, entry_id = await entered(client, db, "vault-spoof@example.test")
    await start(client, csrf, entry_id)

    forged = await client.get(
        f"/api/v1/entries/{entry_id}/vault/return",
        params={"token": f"{SETUP_PREFIX}someone-else", "PayerID": "PAYER-X"},
    )

    assert forged.status_code == 422
    assert forged.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.calls == [f"start_setup:{entry_id}"]
    assert (await token_row(db, entry_id))[0] == "SETUP_PENDING"
    assert (await attempt_rows(db, entry_id))[0][2] is None

    # Another buyer's entry id answers like an unknown one: no existence hint at all.
    async with vault_client(db, provider=provider) as other:
        other_csrf = await login(other, "vault-other@example.test")
        stolen = await other.get(
            f"/api/v1/entries/{entry_id}/vault/return", headers={"X-CSRF-Token": other_csrf}
        )
        stranger_delete = await other.delete(
            f"/api/v1/entries/{uuid.uuid4()}/vault", headers={"X-CSRF-Token": other_csrf}
        )
    assert stolen.status_code == 404 and stranger_delete.status_code == 404
    assert stolen.json()["error"]["message"] == stranger_delete.json()["error"]["message"]


# --------------------------------------------------------------------- delete


async def test_delete_removes_the_provider_resource_before_clearing_the_columns(
    live_client: dict[str, Any],
) -> None:
    client, db, provider = live_client["client"], live_client["db"], live_client["provider"]
    csrf, _, entry_id = await entered(client, db, "vault-delete@example.test")
    await start(client, csrf, entry_id)
    await client.get(f"/api/v1/entries/{entry_id}/vault/return")

    deleted = await client.delete(
        f"/api/v1/entries/{entry_id}/vault", headers={"X-CSRF-Token": csrf}
    )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "entry_id": str(entry_id),
        "vault_status": "DELETED",
        "vault_label": f"{entry_id}"[-4:],
    }
    assert provider.deleted_ids == [f"{TOKEN_PREFIX}{entry_id}"]
    assert provider.calls == [
        f"start_setup:{entry_id}",
        f"exchange:{entry_id}",
        f"delete:{TOKEN_PREFIX}{entry_id}",
    ]

    row = await token_row(db, entry_id)
    # Provider first, columns after: nothing encrypted survives a deletion.
    assert row[0] == "DELETED" and row[5] is not None
    assert row[7] is None and row[8] is None

    repeated = await client.delete(
        f"/api/v1/entries/{entry_id}/vault", headers={"X-CSRF-Token": csrf}
    )
    assert repeated.status_code == 200 and repeated.json() == deleted.json()
    # Idempotent: an already-deleted permission is not deleted twice.
    assert provider.deleted_ids == [f"{TOKEN_PREFIX}{entry_id}"]


async def test_a_provider_404_counts_as_deleted(live_client: dict[str, Any]) -> None:
    client, db, provider = live_client["client"], live_client["db"], live_client["provider"]
    provider.delete_outcome = "not_found"
    csrf, _, entry_id = await entered(client, db, "vault-404@example.test")
    await start(client, csrf, entry_id)
    await client.get(f"/api/v1/entries/{entry_id}/vault/return")

    deleted = await client.delete(
        f"/api/v1/entries/{entry_id}/vault", headers={"X-CSRF-Token": csrf}
    )

    assert deleted.status_code == 200
    assert deleted.json()["vault_status"] == "DELETED"
    assert (await token_row(db, entry_id))[7] is None


async def test_a_failing_provider_delete_keeps_the_credential_tracked(
    live_client: dict[str, Any],
) -> None:
    client, db, provider = live_client["client"], live_client["db"], live_client["provider"]
    provider.delete_outcome = "unavailable"
    csrf, _, entry_id = await entered(client, db, "vault-delfail@example.test")
    await start(client, csrf, entry_id)
    await client.get(f"/api/v1/entries/{entry_id}/vault/return")

    failed = await client.delete(
        f"/api/v1/entries/{entry_id}/vault", headers={"X-CSRF-Token": csrf}
    )

    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "PAYPAL_UNAVAILABLE"
    row = await token_row(db, entry_id)
    # The columns are cleared only once the provider confirms the deletion.
    assert row[0] == "ACTIVE" and row[7] is not None and row[5] is None


# ------------------------------------------------------------------- outcomes


async def test_an_unknown_start_outcome_reuses_the_same_identity(
    db_session: AsyncSession,
) -> None:
    provider = FakePaymentVaultProvider(start_outcome="unknown")
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="unknownstart")
    subject = service(provider)

    for _ in range(2):
        with pytest.raises(ApplicationError) as raised:
            await subject.start(db_session, entry_id=entry_id)
        assert raised.value.code == "PAYPAL_UNAVAILABLE"

    rows = await attempt_rows(db_session, entry_id)
    assert len(rows) == 1
    assert rows[0][0] == f"vs:{entry_id}:1"
    assert rows[0][1] == "PENDING" and rows[0][2] is None
    assert rows[0][3] == VaultProviderUnknown.code
    assert provider.calls.count(f"start_setup:{entry_id}") == 2


async def test_an_unknown_exchange_outcome_never_activates_and_reserves_the_identity(
    db_session: AsyncSession,
) -> None:
    provider = FakePaymentVaultProvider()
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="unknownexchange")
    subject = service(provider)
    redirect = await subject.start(db_session, entry_id=entry_id)
    provider.exchange_outcome = "unknown"

    with pytest.raises(ApplicationError) as raised:
        await subject.complete(
            db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
        )

    assert raised.value.code == "PAYPAL_UNAVAILABLE"
    rows = await attempt_rows(db_session, entry_id)
    assert rows[0][1] == "PENDING" and rows[0][2] is not None
    assert rows[0][3] == "UNKNOWN"
    assert (await token_row(db_session, entry_id))[0] == "SETUP_PENDING"

    # While that outcome is unresolved no second identity is invented (I9): a reopen
    # refuses instead of creating another provider operation.
    with pytest.raises(ApplicationError) as again:
        await subject.start(db_session, entry_id=entry_id)
    assert again.value.code == "PAYPAL_UNAVAILABLE"
    assert len(await attempt_rows(db_session, entry_id)) == 1


async def test_a_declined_permission_never_becomes_active(db_session: AsyncSession) -> None:
    provider = FakePaymentVaultProvider(exchange_outcome="decline")
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="declined")
    subject = service(provider)
    redirect = await subject.start(db_session, entry_id=entry_id)

    with pytest.raises(ApplicationError) as raised:
        await subject.complete(
            db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
        )

    assert raised.value.code == "VAULT_REQUIRED"
    rows = await attempt_rows(db_session, entry_id)
    assert rows[0][1] == "FAILED" and rows[0][3] == "INSTRUMENT_DECLINED"
    row = await token_row(db_session, entry_id)
    assert row[0] == "FAILED" and row[7] is None

    # A declined entry is exactly the VAULT_MISSING case at close, never eligible.
    await set_close_in_the_past(db_session, pool_id)
    await run_close(db_session, pool_id, payment_mode="vault_charge")
    assert await reject_status(db_session, entry_id) == ("REJECTED", "VAULT_MISSING")


async def test_an_expired_attempt_fails_then_a_new_identity_is_created(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="expiry")
    subject = service(FakePaymentVaultProvider())
    await subject.start(db_session, entry_id=entry_id)
    await db_session.execute(
        text(
            "UPDATE vault_setup_attempts SET expires_at = now() - interval '1 second' "
            "WHERE entry_id = :e"
        ),
        {"e": entry_id},
    )

    with pytest.raises(ApplicationError) as refused:
        await subject.start(db_session, entry_id=entry_id)
    assert refused.value.code == "VAULT_SETUP_EXPIRED"
    expired = await attempt_rows(db_session, entry_id)
    assert expired[0][1] == "FAILED" and expired[0][3] == "VAULT_SETUP_EXPIRED"

    # The next attempt is genuinely new: a new row and a new identity, the old row
    # kept as FAILED rather than silently replaced.
    await subject.start(db_session, entry_id=entry_id)
    rows = {(row[0], row[1]) for row in await attempt_rows(db_session, entry_id)}
    assert rows == {(f"vs:{entry_id}:1", "FAILED"), (f"vs:{entry_id}:2", "PENDING")}


async def test_a_callback_after_expiry_or_without_an_attempt_exchanges_nothing(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="nolive")
    subject = service()

    with pytest.raises(ApplicationError) as raised:
        await subject.complete(db_session, entry_id=entry_id, setup_token_id="anything")
    assert raised.value.code == "NOT_FOUND"

    await db_session.execute(
        text(
            "INSERT INTO vault_setup_attempts (id, entry_id, operation_key, status, expires_at) "
            "VALUES (:id, :e, :k, 'PENDING'::vault_setup_status, now() - interval '1 second')"
        ),
        {"id": uuid.uuid4(), "e": entry_id, "k": f"vs:{entry_id}:9"},
    )
    with pytest.raises(ApplicationError) as expired:
        await subject.complete(db_session, entry_id=entry_id, setup_token_id="anything")
    assert expired.value.code == "VAULT_SETUP_EXPIRED"
    assert (
        await db_session.scalar(
            text("SELECT status FROM vault_setup_attempts WHERE entry_id = :e"), {"e": entry_id}
        )
        == "FAILED"
    )
    # An expired attempt is refused before its credential is read, so nothing is exchanged.
    assert await token_row(db_session, entry_id) is None


async def test_start_refuses_a_non_submitted_entry(db_session: AsyncSession) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="withdrawn-entry")
    await db_session.execute(
        text("UPDATE pool_entries SET status = 'WITHDRAWN'::entry_status WHERE id = :e"),
        {"e": entry_id},
    )

    with pytest.raises(ApplicationError) as raised:
        await service().start(db_session, entry_id=entry_id)

    assert raised.value.code == "ORDER_STATE_INVALID"
    assert await attempt_rows(db_session, entry_id) == []


# ---------------------------------------------------------------- quarantine


async def test_a_token_that_arrives_after_withdrawal_is_quarantined_and_deleted(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="quarantine-w")
    provider = FakePaymentVaultProvider()
    subject = service(provider)
    redirect = await subject.start(db_session, entry_id=entry_id)

    user_id = await db_session.scalar(
        text("SELECT user_id FROM pool_entries WHERE id = :e"), {"e": entry_id}
    )
    await join_service().withdraw(db_session, pool_id=pool_id, user_id=user_id)

    permission = await subject.complete(
        db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
    )

    assert permission.status == "DELETED" and permission.label is None
    assert (await attempt_rows(db_session, entry_id))[0][1] == "QUARANTINED"
    assert (await attempt_rows(db_session, entry_id))[0][2] is not None
    # Never exchanged, never activated, never copied into vault_tokens in the clear,
    # and deleted at the provider through the same vd:{entry_id} step (CR-3).
    assert f"exchange:{entry_id}" not in provider.calls
    assert provider.deleted_ids == [redirect.setup_token_id]
    row = await token_row(db_session, entry_id)
    assert row[0] == "DELETED" and row[5] is not None
    assert row[7] is None and row[8] is None
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM vault_tokens WHERE status = 'ACTIVE' AND entry_id = :e"),
            {"e": entry_id},
        )
        == 0
    )


async def test_a_token_that_arrives_after_close_is_quarantined(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="quarantine-c")
    provider = FakePaymentVaultProvider()
    subject = service(provider)
    redirect = await subject.start(db_session, entry_id=entry_id)
    await db_session.execute(
        text(
            "UPDATE pools SET timeline = jsonb_set(timeline, '{close_at}', "
            "to_jsonb(CAST(:t AS text))) WHERE id = :id"
        ),
        {"id": pool_id, "t": iso_in(-5)},
    )

    permission = await subject.complete(
        db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
    )

    assert permission.status == "DELETED"
    assert (await attempt_rows(db_session, entry_id))[0][1] == "QUARANTINED"
    assert provider.deleted_ids == [redirect.setup_token_id]
    assert (await token_row(db_session, entry_id))[0] == "DELETED"


# -------------------------------------------------------------------- secrets


class Capture(logging.Handler):
    """The production redaction path: filter then JSON format, captured in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.addFilter(RedactionFilter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(JsonFormatter().format(record))


async def test_the_token_id_appears_in_no_response_log_audit_notification_or_document(
    live_client: dict[str, Any],
) -> None:
    client, db = live_client["client"], live_client["db"]
    csrf, pool_id, entry_id = await entered(client, db, "vault-secret@example.test")
    token_id = f"{TOKEN_PREFIX}{entry_id}"

    handler = Capture()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        responses = [await start(client, csrf, entry_id)]
        responses.append(await client.get(f"/api/v1/entries/{entry_id}/vault/return"))
        responses.append(
            await client.delete(f"/api/v1/entries/{entry_id}/vault", headers={"X-CSRF-Token": csrf})
        )
        responses.append(
            await client.get(f"/api/v1/pools/{pool_id}/entries/me", headers={"X-CSRF-Token": csrf})
        )
        responses.append(await client.get(f"/api/v1/public/pools/{pool_id}/audit"))
    finally:
        root.removeHandler(handler)

    bodies = [response.text for response in responses if response.status_code < 500]
    assert len(bodies) >= 4
    for body in bodies:
        assert token_id not in body
    for line in handler.lines:
        assert token_id not in line
        assert SETUP_PREFIX not in line

    stored = (
        (
            await db.execute(
                text("SELECT payload::text FROM audit_log WHERE subject_id = :e"),
                {"e": str(entry_id)},
            )
        )
        .scalars()
        .all()
    )
    assert stored
    for payload in stored:
        assert token_id not in str(payload)

    notifications = (
        (await db.execute(text("SELECT payload::text FROM notifications"))).scalars().all()
    )
    for payload in notifications:
        assert token_id not in str(payload)

    # A search document is projected from public pool and lot columns only, so a
    # saved credential has no path into one (INT-1, rule 27).
    projection = (SOURCE / "adapters" / "search" / "projection.py").read_text(encoding="utf-8")
    assert "vault" not in projection.lower()
    assert "token_ciphertext" not in projection

    # Buyers see the four-character label, never the token (vault-charge.md §5).
    delete_body = json.loads(bodies[2])
    assert delete_body["vault_label"] == token_id[-4:]
    assert len(delete_body["vault_label"]) == 4


# ----------------------------------------------------------------------- locks


async def test_no_provider_step_runs_while_a_pool_or_entry_lock_is_held(
    db_engine: AsyncEngine,
) -> None:
    """The rows were committed by another transaction and stay unlocked here."""
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        pool_id = await insert_pool(session)
        user_id = await add_buyer(session, "lockproof")
        confirmed = await manual_confirm(session, user_id, pool_id)
        outcome = await join_service().join(
            session,
            pool_id=pool_id,
            user_id=user_id,
            confirmed_request_id=confirmed,
            idempotency_key="vault-lock",
        )
        entry_id = uuid.UUID(str(outcome.body["entry_id"]))

    observed: dict[str, str] = {}

    async def probe(step: str) -> None:
        # From a different connection: succeeds only if this transaction holds no
        # lock on the pool or the entry row.
        async with db_engine.connect() as connection:
            transaction = await connection.begin()
            try:
                # FOR NO KEY UPDATE is the strength pool.close needs to write these
                # rows, and it is not the FOR KEY SHARE lock that a foreign-key write
                # of a child row always takes.
                await connection.execute(
                    text("SELECT id FROM pools WHERE id = :i FOR NO KEY UPDATE NOWAIT"),
                    {"i": pool_id},
                )
                await connection.execute(
                    text("SELECT id FROM pool_entries WHERE id = :i FOR NO KEY UPDATE NOWAIT"),
                    {"i": entry_id},
                )
            except DBAPIError as exc:
                observed[step] = "LOCKED" if "could not obtain lock" in str(exc) else "ERROR"
            else:
                observed[step] = "FREE"
            finally:
                await transaction.rollback()

    provider = FakePaymentVaultProvider(on_call=probe)
    try:
        async with maker() as session, session.begin():
            subject = service(provider)
            redirect = await subject.start(session, entry_id=entry_id)
            await subject.complete(
                session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
            )
            permission = await subject.withdraw(session, entry_id=entry_id)
    finally:
        async with db_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM vault_tokens WHERE entry_id = :e"), {"e": entry_id}
            )
            await connection.execute(
                text("DELETE FROM vault_setup_attempts WHERE entry_id = :e"), {"e": entry_id}
            )
        await wipe_join_data(db_engine, pool_id, [user_id])

    assert permission.status == "DELETED"
    assert provider.calls == [
        f"start_setup:{entry_id}",
        f"exchange:{entry_id}",
        f"delete:{TOKEN_PREFIX}{entry_id}",
    ]
    assert observed[f"start_setup:{entry_id}"] == "FREE"
    assert observed[f"exchange:{entry_id}"] == "FREE"
    assert "LOCKED" not in observed.values() and "ERROR" not in observed.values()


# ----------------------------------------------------------------------- fake


def test_the_fake_is_a_provider_that_builds_no_network_client() -> None:
    provider = FakePaymentVaultProvider()
    assert isinstance(provider, PaymentVaultProvider)
    assert vars(provider).keys() <= {
        "start_outcome",
        "exchange_outcome",
        "delete_outcome",
        "calls",
        "setup_tokens",
        "payment_tokens",
        "deleted_ids",
        "on_call",
    }
    # Nothing on the fake is a client, session or transport of any kind.
    for name, value in vars(provider).items():
        assert not hasattr(value, "request"), name
        assert not hasattr(value, "post"), name

    # Source-level proof: the fake and the vault service import no HTTP client and
    # nothing from the PayPal adapter, so a synthetic entry can never reach PayPal.
    forbidden = {"httpx", "aiohttp", "requests", "urllib3", "socket", "ssl"}
    for relative in (
        ("fakes", "vault.py"),
        ("modules", "pools", "vault.py"),
        ("modules", "pools", "close.py"),
    ):
        source = (SOURCE.joinpath(*relative)).read_text(encoding="utf-8")
        targets = _imported_names(source)
        # The PayPal adapter is unreachable by import, not by wording.
        assert not {name.split(".")[0] for name in targets} & forbidden, relative
        assert not any(name.startswith("fairpool.adapters") for name in targets), relative


def _imported_names(source: str) -> set[str]:
    """Every imported module path in the file, at any depth (imports, not prose)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_only_the_attempt_and_token_tables_are_written_by_the_vault_service() -> None:
    """Static proof that the provider path takes no pool or entry lock."""
    source = (SOURCE / "modules" / "pools" / "vault.py").read_text(encoding="utf-8")
    assert "with_for_update" not in source
    assert "FOR UPDATE" not in source.replace("``FOR UPDATE``", "")
    statements = [
        value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for value in [node.value]
        if value.lstrip().startswith("UPDATE ")
    ]
    assert statements
    for statement in statements:
        table = statement.strip().split()[1]
        assert table in {"vault_setup_attempts", "vault_tokens"}, statement


async def test_the_fake_issues_inert_local_identifiers(db_session: AsyncSession) -> None:
    entry_id = uuid.uuid4()
    provider = FakePaymentVaultProvider()
    redirect = await provider.start_setup(entry_id)
    assert redirect.setup_token_id == f"{SETUP_PREFIX}{entry_id}"
    assert redirect.approve_url == f"{INVALID_HOST}{redirect.setup_token_id}"

    permission = await provider.exchange(entry_id, redirect.setup_token_id)
    assert permission.payment_token_id == f"{TOKEN_PREFIX}{entry_id}"
    assert permission.label == permission.payment_token_id[-4:]

    await provider.delete(permission.payment_token_id)
    assert provider.deleted_ids == [permission.payment_token_id]

    # A setup token the fake never issued for this entry exchanges nothing.
    with pytest.raises(VaultProviderUnknown):
        await provider.exchange(entry_id, "someone-elses-token")


async def test_status_reports_only_a_status_and_a_four_character_label(
    db_session: AsyncSession,
) -> None:
    pool_id = await insert_pool(db_session)
    entry_id = await joined_entry(db_session, pool_id, tag="statusview")
    subject = service(FakePaymentVaultProvider())

    before = await subject.status(db_session, entry_id=entry_id)
    assert before.status == "SETUP_PENDING" and before.label is None

    redirect = await subject.start(db_session, entry_id=entry_id)
    middle = await subject.status(db_session, entry_id=entry_id)
    assert middle.status == "SETUP_PENDING" and middle.label is None

    active = await subject.complete(
        db_session, entry_id=entry_id, setup_token_id=redirect.setup_token_id
    )
    assert active.status == "ACTIVE"
    assert active.label is not None and len(active.label) == 4
    assert vars(active).keys() <= {"entry_id", "status", "label"}
    assert TOKEN_PREFIX not in repr(active)

    after = await subject.withdraw(db_session, entry_id=entry_id)
    assert after.status == "DELETED" and after.label == active.label

    with pytest.raises(ApplicationError) as raised:
        await subject.status(db_session, entry_id=uuid.uuid4())
    assert raised.value.code == "NOT_FOUND"
