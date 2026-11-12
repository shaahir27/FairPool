"""T08A01: fulfillment gates, CSV, shipments, manifest and live verification.

Every acceptance bullet from the task row is a named test here:

* fulfillment, shipments and the manifest answer ``409 LOT_NOT_FUNDED`` before the
  lot reaches FUNDED/CLOSED, and progress is readable while checkout runs;
* the CSV carries the contracted columns with every field quoted and a leading
  apostrophe on values a spreadsheet would execute;
* a foreign or unknown lot is the same ``404`` and its body holds no address;
* shipment rows are validated per row, recorded once per buyer order and audited
  once, and ``shipments.submit`` fills the tracker columns through the adapter;
* the manifest lists CAPTURED orders only and carries no buyer personal data;
* live verification is read-only GETs, matches amounts and statuses, and answers
  ``429 RATE_LIMITED`` on the eleventh call in a minute.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain.payments import PaymentError, PayPalCapture, PayPalOrder
from fairpool.fakes.payments import FakePayPalGateway
from fairpool.modules.checkout.shipping import ShippingCipher
from fairpool.modules.fulfillment import csv as fulfillment_csv
from fairpool.wiring import checkout_services, worker_handlers
from tests.integration.test_bid_sealing import bidding_world, lot_with_deadline, structured
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_merchant_api_keys import merchant
from tests.integration.test_open_checkout import World, build_world

pytestmark = pytest.mark.integration

SETTINGS = settings_for()
API = "/api/v1/merchant/lots"
HOW_TO_VERIFY = (
    "In your AI client connected to the PayPal MCP server, look up each order ID "
    "with a read-only get-order tool and confirm the capture amounts add up to "
    "expected_captured_total_cents."
)
DEFAULT_ADDRESS = {
    "name": "Demo Buyer",
    "line1": "1 Test Street",
    "line2": "",
    "city": "New York",
    "region": "NY",
    "postal_code": "10001",
    "country_code": "US",
}
INJECTION_ADDRESS = {
    "name": "=SUM(A1)",
    "line1": "+1 Main Street",
    "line2": "",
    "city": "-City",
    "region": "@Region",
    "postal_code": "\t12345",
    "country_code": "US",
}


@dataclass
class Awarded:
    world: World
    order_ids: list[UUID]
    capture_ids: list[str]
    paypal_order_ids: list[str]
    address: dict[str, str]


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


async def console_merchant(
    client: httpx.AsyncClient, db_session: AsyncSession, email: str
) -> tuple[str, UUID]:
    return await merchant(client, db_session, email)


async def build_awarded_world(
    session: AsyncSession,
    merchant_id: UUID,
    *,
    status: str = "FUNDED",
    captured: int = 2,
    address: dict[str, str] | None = None,
) -> Awarded:
    """One lot with an award held by ``merchant_id`` and CAPTURED buyer orders."""
    world = await build_world(
        session,
        lot_status=status,
        with_award=False,
        seats=2,
        seated=2,
        waitlisted=0,
        moq=2,
    )
    award_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, "
            "item_cents, moq, totals, valid_until, rule_version, award_hash) "
            "VALUES (:id, :lot, NULL, :merchant, 0, 47000, 2, CAST(:totals AS jsonb), "
            ":valid_until, 'ranking_v1', :hash)"
        ),
        {
            "id": award_id,
            "lot": world.lot_id,
            "merchant": merchant_id,
            "totals": json.dumps(world.totals),
            "valid_until": world.now,
            "hash": "0" * 64,
        },
    )
    await session.execute(
        text(
            "UPDATE lots SET award_id = :award, fund_deadline_at = :deadline, "
            "refill_waves = 1 WHERE id = :lot"
        ),
        {"award": award_id, "deadline": world.now, "lot": world.lot_id},
    )
    cipher = ShippingCipher(SETTINGS.address_encryption_key.get_secret_value())
    chosen = dict(address or DEFAULT_ADDRESS)
    sealed = cipher.seal(chosen)
    order_ids: list[UUID] = []
    capture_ids: list[str] = []
    paypal_order_ids: list[str] = []
    for entry_id in world.entry_ids[:captured]:
        order_id = uuid4()
        total = int(world.totals[str(entry_id)]["total_cents"])
        breakdown = {
            "item_cents": int(world.totals[str(entry_id)]["item_cents"]),
            "shipping_cents": int(world.totals[str(entry_id)]["shipping_cents"]),
            "tax_cents": int(world.totals[str(entry_id)]["tax_cents"]),
        }
        await session.execute(
            text(
                "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, "
                "total_cents, breakdown, shipping_enc) VALUES (:id, :lot, :entry, 'CAPTURED', "
                ":expires, :total, CAST(:breakdown AS jsonb), :enc)"
            ),
            {
                "id": order_id,
                "lot": world.lot_id,
                "entry": entry_id,
                "expires": world.now,
                "total": total,
                "breakdown": json.dumps(breakdown),
                "enc": sealed,
            },
        )
        paypal_order_id = "ORDER-" + uuid4().hex
        capture_id = "CAPTURE-" + uuid4().hex
        await session.execute(
            text(
                "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, "
                "status, intent, amount_cents, raw) VALUES (:id, :order, 0, :paypal, "
                "'COMPLETED', 'AUTHORIZE', :amount, '{}'::jsonb)"
            ),
            {
                "id": uuid4(),
                "order": order_id,
                "paypal": paypal_order_id,
                "amount": total,
            },
        )
        await session.execute(
            text(
                "INSERT INTO paypal_captures (id, buyer_order_id, paypal_auth_id, "
                "paypal_capture_id, status, amount_cents, final_capture, raw) VALUES "
                "(:id, :order, NULL, :capture, 'COMPLETED', :amount, true, '{}'::jsonb)"
            ),
            {
                "id": uuid4(),
                "order": order_id,
                "capture": capture_id,
                "amount": total,
            },
        )
        await session.execute(
            text(
                "INSERT INTO ledger_entries (id, lot_id, buyer_order_id, kind, amount_cents, "
                "paypal_ref, idempotency_key, source) VALUES (:id, :lot, :order, "
                "CAST('CAPTURE_COMPLETED' AS ledger_kind), :amount, :capture, :key, "
                "CAST('api' AS ledger_source))"
            ),
            {
                "id": uuid4(),
                "lot": world.lot_id,
                "order": order_id,
                "amount": total,
                "capture": capture_id,
                "key": f"seed:{capture_id}",
            },
        )
        order_ids.append(order_id)
        capture_ids.append(capture_id)
        paypal_order_ids.append(paypal_order_id)
    await session.flush()
    return Awarded(
        world=world,
        order_ids=order_ids,
        capture_ids=capture_ids,
        paypal_order_ids=paypal_order_ids,
        address=chosen,
    )


async def set_lot_status(session: AsyncSession, lot_id: UUID, status: str) -> None:
    await session.execute(
        text("UPDATE lots SET status = CAST(:status AS lot_status) WHERE id = :lot"),
        {"status": status, "lot": lot_id},
    )
    await session.flush()


class CountingGateway(FakePayPalGateway):
    """Counts read-only GETs and answers from the seeded order mirror."""

    def __init__(self) -> None:
        super().__init__()
        self.get_order_calls = 0

    async def get_order(self, paypal_order_id: str) -> PayPalOrder:
        self.get_order_calls += 1
        return await super().get_order(paypal_order_id)


def seed_gateway(gateway: CountingGateway, awarded: Awarded) -> None:
    for index, paypal_order_id in enumerate(awarded.paypal_order_ids):
        entry_id = awarded.world.entry_ids[index]
        total = int(awarded.world.totals[str(entry_id)]["total_cents"])
        capture_id = awarded.capture_ids[index]
        gateway.orders[paypal_order_id] = PayPalOrder(
            id=paypal_order_id,
            status="COMPLETED",
            intent="AUTHORIZE",
            currency="USD",
            amount_cents=total,
            payee_email=None,
            payee_merchant_id=None,
            payer_id=None,
            payer_country="US",
            approve_url=None,
            authorizations=[],
            captures=[PayPalCapture(capture_id, "COMPLETED", total, True, None)],
            debug_id=None,
            raw={},
        )


# ------------------------------------------------------------------ gates


async def test_progress_reads_and_fulfillment_waits_for_funded(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, merchant_id = await console_merchant(client, db_session, "gates@example.test")
    awarded = await build_awarded_world(db_session, merchant_id, status="AWARDED")
    lot_id = awarded.world.lot_id

    progress = await client.get(f"{API}/{lot_id}/progress")
    assert progress.status_code == 200, progress.text
    body = progress.json()
    assert body["status"] == "AWARDED"
    assert body["seats"] == 2 and body["moq"] == 2
    assert body["holds_placed"] == 2
    assert body["captures_completed"] == 2
    assert body["refills_offered"] == 1
    assert body["counts"]["CAPTURED"] == 2
    assert body["counts"]["OFFERED"] == 0
    assert len(body["counts"]) == 16
    assert body["fund_deadline_at"] is not None
    assert body["labels"] == ["SANDBOX", "FALLBACK: single stand-in seller"]
    assert csrf

    for path in ("fulfillment", "verification-manifest"):
        refused = await client.get(f"{API}/{lot_id}/{path}")
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "LOT_NOT_FUNDED"
    shipments = await client.post(
        f"{API}/{lot_id}/shipments",
        headers={"X-CSRF-Token": csrf},
        json={
            "shipments": [
                {
                    "buyer_order_id": str(awarded.order_ids[0]),
                    "carrier": "UPS",
                    "tracking_number": "1Z999",
                }
            ]
        },
    )
    assert shipments.status_code == 409
    assert shipments.json()["error"]["code"] == "LOT_NOT_FUNDED"

    await set_lot_status(db_session, lot_id, "FUNDED")
    funded = await client.get(f"{API}/{lot_id}/fulfillment")
    assert funded.status_code == 200, funded.text
    assert {row["buyer_order_id"] for row in funded.json()} == {
        str(order_id) for order_id in awarded.order_ids
    }


async def test_a_foreign_or_unknown_lot_is_not_found_without_addresses(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _csrf, owner_id = await console_merchant(client, db_session, "owner-fulfill@example.test")
    awarded = await build_awarded_world(db_session, owner_id)
    _other_csrf, _other_id = await console_merchant(
        client, db_session, "foreign-fulfill@example.test"
    )

    for path in ("fulfillment", "verification-manifest", "progress", "verification"):
        refused = await client.get(f"{API}/{awarded.world.lot_id}/{path}")
        assert refused.status_code == 404, (path, refused.text)
        assert refused.json()["error"]["code"] == "NOT_FOUND"
        rendered = refused.text
        for value in (awarded.address["name"], awarded.address["line1"], awarded.address["city"]):
            assert value not in rendered

    unknown = await client.get(f"{API}/{uuid4()}/fulfillment")
    assert unknown.status_code == 404


# -------------------------------------------------------------------- CSV


async def test_csv_quotes_every_field_and_defuses_formulas(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _csrf, merchant_id = await console_merchant(client, db_session, "csv@example.test")
    awarded = await build_awarded_world(db_session, merchant_id, address=INJECTION_ADDRESS)

    response = await client.get(
        f"{API}/{awarded.world.lot_id}/fulfillment", headers={"Accept": "text/csv"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.split("\r\n")
    assert lines[0] == (
        '"buyer_order_id","name","line1","line2","city","region","postal_code",'
        '"country_code","item_cents","shipping_cents","tax_cents","total_cents",'
        '"paypal_capture_id"'
    )
    assert lines[-1] == "" and len(lines) == 4  # header plus two rows plus the final CRLF
    assert '"\'=SUM(A1)"' in response.text
    assert '"\'+1 Main Street"' in response.text
    assert '"\'-City"' in response.text
    assert '"\'@Region"' in response.text
    # The address normaliser strips surrounding whitespace, so a stored field can never
    # begin with a tab: the writer's tab and CR prefixes are proved directly, because
    # those are the values that actually need one and no stored row can carry them.
    assert '"12345"' in response.text
    written = fulfillment_csv.render([{"name": "\t=SUM(A1)", "city": "\r=1+1"}])
    assert '"\'\t=SUM(A1)"' in written
    assert '"\'\r=1+1"' in written
    assert "\n" not in response.text.replace("\r\n", "")


# -------------------------------------------------------------- shipments


async def test_shipment_rows_are_per_row_and_recorded_once(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf, merchant_id = await console_merchant(client, db_session, "ship@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)
    lot_id = awarded.world.lot_id
    payload = {
        "shipments": [
            {
                "buyer_order_id": str(awarded.order_ids[0]),
                "carrier": "UPS",
                "tracking_number": "1Z999",
            },
            {
                "buyer_order_id": str(uuid4()),
                "carrier": "UPS",
                "tracking_number": "1Z888",
            },
            {
                "buyer_order_id": str(awarded.order_ids[1]),
                "carrier": "  ",
                "tracking_number": " ",
            },
        ]
    }

    first = await client.post(
        f"{API}/{lot_id}/shipments", headers={"X-CSRF-Token": csrf}, json=payload
    )

    assert first.status_code == 202, first.text
    body = first.json()
    assert body["accepted"] == 1
    assert [row["status"] for row in body["rows"]] == ["RECORDED", "INVALID", "INVALID"]
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
            )
            or 0
        )
        == 1
    )
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM audit_log WHERE action = 'shipment.recorded'")
            )
            or 0
        )
        == 1
    )

    replay = await client.post(
        f"{API}/{lot_id}/shipments", headers={"X-CSRF-Token": csrf}, json=payload
    )
    assert replay.status_code == 202
    assert replay.json()["accepted"] == 1
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
            )
            or 0
        )
        == 1
    )
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM audit_log WHERE action = 'shipment.recorded'")
            )
            or 0
        )
        == 1
    )
    queued = int(
        await db_session.scalar(
            text(
                "SELECT count(*) FROM jobs WHERE kind = 'shipments.submit' "
                "AND payload->>'lot_id' = :lot"
            ),
            {"lot": str(lot_id)},
        )
        or 0
    )
    assert queued == 1

    # The registered handler fills the tracker columns through the adapter and a
    # failure is recorded on the row rather than raised.
    surface = checkout_services(SETTINGS)
    surface.router.name = "single_seller"
    handler = worker_handlers(SETTINGS, checkout=surface)["shipments.submit"]
    await handler(db_session, {"lot_id": str(lot_id)})
    status = await db_session.scalar(
        text("SELECT paypal_tracker_status FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
    )
    assert str(status) == "SUBMITTED"


class FailingTracker:
    """The provider refusing the batch, as the adapter reports it."""

    async def add_trackers(self, items: list[Any]) -> list[Any]:
        raise PaymentError("RETRYABLE", "TRACKERS", debug_id="DBG-TRACKERS")


async def test_a_failed_tracker_row_is_retried_by_the_next_resubmission(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A FAILED row is not terminal: the merchant's resubmission is the retry."""
    from fairpool.modules.fulfillment.tracking import ShipmentTracking

    csrf, merchant_id = await console_merchant(client, db_session, "retry@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)
    lot_id = awarded.world.lot_id
    payload = {
        "shipments": [
            {
                "buyer_order_id": str(awarded.order_ids[0]),
                "carrier": "UPS",
                "tracking_number": "1Z777",
            }
        ]
    }

    async def queued() -> int:
        return int(
            await db_session.scalar(
                text(
                    "SELECT count(*) FROM jobs WHERE kind = 'shipments.submit' "
                    "AND payload->>'lot_id' = :lot"
                ),
                {"lot": str(lot_id)},
            )
            or 0
        )

    assert (
        await client.post(f"{API}/{lot_id}/shipments", headers={"X-CSRF-Token": csrf}, json=payload)
    ).status_code == 202
    assert await queued() == 1

    # The worker runs, the provider refuses, the row records FAILED and the job is done.
    await ShipmentTracking(gateway=FailingTracker(), enabled=True).submit(
        db_session, {"lot_id": str(lot_id)}
    )
    status = await db_session.scalar(
        text("SELECT paypal_tracker_status FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
    )
    assert str(status) == "FAILED"
    await db_session.execute(
        text(
            "UPDATE jobs SET status = 'DONE' WHERE kind = 'shipments.submit' "
            "AND payload->>'lot_id' = :lot"
        ),
        {"lot": str(lot_id)},
    )

    replay = await client.post(
        f"{API}/{lot_id}/shipments", headers={"X-CSRF-Token": csrf}, json=payload
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["rows"][0]["paypal_tracker_status"] == "FAILED"
    assert await queued() == 2, "a resubmission re-enqueues the failed row"

    # An enqueue that never landed is the same problem: the next call restores it.
    await db_session.execute(
        text("DELETE FROM jobs WHERE kind = 'shipments.submit' AND payload->>'lot_id' = :lot"),
        {"lot": str(lot_id)},
    )
    await client.post(f"{API}/{lot_id}/shipments", headers={"X-CSRF-Token": csrf}, json=payload)
    assert await queued() == 1, "a lost enqueue is restored by the next submission"

    surface = checkout_services(SETTINGS)
    surface.router.name = "single_seller"
    handler = worker_handlers(SETTINGS, checkout=surface)["shipments.submit"]
    await handler(db_session, {"lot_id": str(lot_id)})
    retried = await db_session.scalar(
        text("SELECT paypal_tracker_status FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
    )
    assert str(retried) == "SUBMITTED"


async def test_a_shipment_for_an_uncaptured_order_is_invalid(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Only a CAPTURED order of this lot may ship; the trigger remains the last word."""
    csrf, merchant_id = await console_merchant(client, db_session, "uncaptured@example.test")
    awarded = await build_awarded_world(db_session, merchant_id, captured=1)
    lot_id = awarded.world.lot_id
    offered_order = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO buyer_orders (id, lot_id, entry_id, status, offer_expires_at, "
            "total_cents, breakdown) VALUES (:id, :lot, :entry, 'OFFERED', :expires, 47000, "
            "CAST('{}' AS jsonb))"
        ),
        {
            "id": offered_order,
            "lot": lot_id,
            "entry": awarded.world.entry_ids[1],
            "expires": awarded.world.now,
        },
    )

    response = await client.post(
        f"{API}/{lot_id}/shipments",
        headers={"X-CSRF-Token": csrf},
        json={
            "shipments": [
                {"buyer_order_id": str(offered_order), "carrier": "UPS", "tracking_number": "1Z1"}
            ]
        },
    )

    assert response.status_code == 202, response.text
    assert response.json()["rows"] == [
        {"buyer_order_id": str(offered_order), "status": "INVALID", "paypal_tracker_status": None}
    ]
    assert (
        int(
            await db_session.scalar(
                text("SELECT count(*) FROM shipments WHERE lot_id = :lot"), {"lot": lot_id}
            )
            or 0
        )
        == 0
    )


# --------------------------------------------------------------- manifest


async def test_the_manifest_lists_captures_only_and_never_the_buyer(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _csrf, merchant_id = await console_merchant(client, db_session, "manifest@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)

    response = await client.get(f"{API}/{awarded.world.lot_id}/verification-manifest")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lot_id"] == str(awarded.world.lot_id)
    assert body["currency"] == "USD"
    assert body["funded"] is True
    assert body["expected_captured_total_cents"] == 100_000
    assert body["how_to_verify"] == HOW_TO_VERIFY
    assert {item["paypal_order_id"] for item in body["items"]} == set(awarded.paypal_order_ids)
    assert {item["paypal_capture_id"] for item in body["items"]} == set(awarded.capture_ids)
    assert set(body["items"][0]) == {
        "paypal_order_id",
        "paypal_capture_id",
        "amount_cents",
        "captured_at",
    }
    rendered = json.dumps(body)
    for value in (
        awarded.address["name"],
        awarded.address["line1"],
        awarded.address["city"],
        awarded.address["postal_code"],
        str(awarded.order_ids[0]),
    ):
        assert value not in rendered


# ----------------------------------------------------------- verification


async def test_simulated_verification_never_calls_paypal(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _csrf, merchant_id = await console_merchant(client, db_session, "sim-verify@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)
    await db_session.execute(
        text("UPDATE lots SET payment_router = 'fake' WHERE id = :lot"),
        {"lot": awarded.world.lot_id},
    )
    gateway = CountingGateway()
    seed_gateway(gateway, awarded)
    client._transport.app.state.fulfillment_gateway = gateway  # type: ignore[attr-defined]

    response = await client.get(f"{API}/{awarded.world.lot_id}/verification")

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FEATURE_DISABLED"
    assert "simulated" in response.json()["error"]["message"].lower()
    assert gateway.get_order_calls == 0
    manifest = await client.get(f"{API}/{awarded.world.lot_id}/verification-manifest")
    assert manifest.status_code == 200


async def test_verification_uses_read_only_gets_and_charges_the_provider_budget(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    from fairpool.modules.fulfillment.verification import VERIFY_PROVIDER_BUDGET

    _csrf, merchant_id = await console_merchant(client, db_session, "verify@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)
    gateway = CountingGateway()
    seed_gateway(gateway, awarded)
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.fulfillment_gateway = gateway

    # Each request reads two captures, and the window is charged once per item.
    allowed = VERIFY_PROVIDER_BUDGET // 2
    for _ in range(allowed):
        response = await client.get(f"{API}/{awarded.world.lot_id}/verification")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["matched"] == 2 and body["total"] == 2
        assert body["all_match"] is True
        assert body["expected_captured_total_cents"] == 100_000
        assert body["paypal_captured_total_cents"] == 100_000
        assert all(item["match"] for item in body["items"])
        assert body["items"][0]["paypal_capture_status"] == "COMPLETED"
    assert gateway.get_order_calls == VERIFY_PROVIDER_BUDGET

    limited = await client.get(f"{API}/{awarded.world.lot_id}/verification")
    assert limited.status_code == 429, limited.text
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.headers["retry-after"].isdigit()
    assert gateway.get_order_calls == VERIFY_PROVIDER_BUDGET, "a refused call makes no PayPal GET"


async def test_verification_reports_a_mismatched_capture(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    _csrf, merchant_id = await console_merchant(client, db_session, "mismatch@example.test")
    awarded = await build_awarded_world(db_session, merchant_id)
    gateway = CountingGateway()
    seed_gateway(gateway, awarded)
    first = gateway.orders[awarded.paypal_order_ids[0]]
    gateway.orders[awarded.paypal_order_ids[0]] = replace(
        first,
        captures=[PayPalCapture(awarded.capture_ids[0], "DECLINED", 99_999, True, None)],
    )
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.fulfillment_gateway = gateway

    response = await client.get(f"{API}/{awarded.world.lot_id}/verification")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["matched"] == 1 and body["total"] == 2
    assert body["all_match"] is False
    mismatched = next(
        item for item in body["items"] if item["paypal_capture_id"] == awarded.capture_ids[0]
    )
    matched = next(
        item for item in body["items"] if item["paypal_capture_id"] == awarded.capture_ids[1]
    )
    assert mismatched["match"] is False
    assert mismatched["paypal_capture_status"] == "DECLINED"
    assert mismatched["paypal_amount_cents"] == 99_999
    assert matched["match"] is True


async def test_a_second_merchants_bid_is_not_found_at_the_console(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """PT-15 for the bids list: a merchant reads only its own bids (I11)."""
    world = await bidding_world(db_session)
    lot_id = await lot_with_deadline(db_session, world, offset_s=600)
    csrf, _merchant_id = await console_merchant(client, db_session, "bidder-list@example.test")
    saved = await client.put(
        f"/api/v1/merchant/lots/{lot_id}/bid",
        headers={"X-CSRF-Token": csrf},
        json={"structured": structured()},
    )
    assert saved.status_code == 200, saved.text
    mine = await client.get("/api/v1/merchant/bids")
    assert mine.status_code == 200, mine.text
    assert [item["bid_id"] for item in mine.json()["items"]] == [saved.json()["bid_id"]]

    await console_merchant(client, db_session, "bidder-empty@example.test")
    theirs = await client.get("/api/v1/merchant/bids")
    assert theirs.status_code == 200
    assert theirs.json()["items"] == []
