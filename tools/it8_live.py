"""IT-8 end-to-end harness (docs/testing-strategy.md IT-8, T08X01).

Runs the Phase 8 acceptance path **in process** over the app's own ASGI app and the
loopback Postgres database, with no external server and no live PayPal traffic in
the main run:

    python tools/it8_live.py --out .tmp/it8_report.json
    python tools/it8_live.py --live-verify --out .tmp/it8_live_verify.json

The default run makes fixtures, opens one two-lot pool with the fake payment
router, has three buyers join and two merchants bid through the console, funds
the first lot with two completed captures from distinct buyers, exercises the
merchant fulfillment surface (progress, JSON, CSV, shipments, manifest and the
fake-router verification), calls all ten Merchant Agent API operations, reads one
SSE tick from the merchant feed, and runs a 10,000-entry simulation that must
allocate in under ten seconds and stay invisible on public surfaces.

``--live-verify`` is the optional second run: with ``PAYMENT_ROUTER=single_seller``
and the sandbox credentials already in ``.env``, it calls the verification service
directly for the IT-7 funded lot on the local ``fairpool`` database and records
the read-only PayPal result (matched/total/totals).

No secret, API key, session cookie, approval URL, provider token or delivery
address is ever written to stdout or the JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

#: The IT-7 funded lot and the capture recorded in docs/testing-strategy.md.
IT7_LOT_ID = UUID("6354b29d-8a83-4506-9b95-19543ce781d9")
IT7_CAPTURE_ID = "67454261HL110735P"

#: Fixture delivery address. It is sent to the fake router and never reported.
SHIPPING: dict[str, str] = {
    "name": "IT8 Buyer",
    "line1": "12 Example Street",
    "city": "Albany",
    "region": "NY",
    "postal_code": "12207",
    "country_code": "US",
}

TEMPLATE: dict[str, Any] = {
    "product_key": "monitor-27-4k",
    "variant": "black",
    "title": "Desk 27-inch 4K monitor",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "delivery_sla_days": 7,
    "fund_by": "2027-06-30",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
}

#: Two lots: the first funds and is fulfilled; the second need not.
LOT_PLAN: list[dict[str, Any]] = [
    {"zone_id": "US-EAST", "lots": [{"seats": 2, "min_seats": 2}, {"seats": 1, "min_seats": 1}]}
]

ALL_SCOPES = [
    "lots:read",
    "bids:read",
    "bids:write",
    "fulfillment:read",
    "shipments:write",
    "manifest:read",
]

MERCHANT_API_OPERATIONS = (
    "get_bid",
    "get_lot",
    "get_lot_fulfillment",
    "get_lot_progress",
    "get_lot_verification",
    "get_verification_manifest",
    "list_bids",
    "list_lots",
    "submit_bid",
    "submit_shipments",
)


class StepFailure(RuntimeError):
    """A named step failed; the top level prints its name and exits non-zero."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


def load_it7() -> Any:
    """Import the IT-7 harness without running its ``__main__`` block."""
    name = "it7_live"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "it7_live.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("tools/it7_live.py is missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_env() -> None:
    """The repository ``.env`` fills only variables the shell did not set."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def loopback_database_url() -> str:
    """Derive the loopback ``fairpool`` URL from ``TEST_DATABASE_URL``.

    The hosted demo URL in ``.env`` is never used: this harness writes fixtures,
    captures and a 10,000-entry simulation and must only touch the local server.
    """
    from sqlalchemy.engine import make_url

    raw = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("IT-8: TEST_DATABASE_URL or DATABASE_URL is required")
    url = make_url(raw)
    host = (url.host or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1", ""}:
        raise SystemExit(
            "IT-8: TEST_DATABASE_URL is not a loopback host; refusing to touch a hosted database"
        )
    # ``str(URL)`` masks the password; the engine needs the real value.
    return url.set(database="fairpool").render_as_string(hide_password=False)


def _error_code(response: httpx.Response) -> str:
    """The contract code only; never a response body that could carry buyer data."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
        return "" if code is None else f" {code}"
    if isinstance(body, dict) and body.get("detail"):
        return f" {body['detail']}"
    return ""


def must(
    response: httpx.Response,
    route: str | None = None,
    expect: tuple[int, ...] = (200, 201, 202, 204),
) -> httpx.Response:
    """An unexpected status is a failed assertion naming the route and code."""
    if response.status_code not in expect:
        path = route or response.request.url.path
        raise AssertionError(f"{path} -> {response.status_code}{_error_code(response)}")
    return response


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Report:
    """The JSON report: named steps, timings, counts; never secrets or addresses."""

    def __init__(self, mode: str, out: Path) -> None:
        self.out = out
        self.data: dict[str, Any] = {
            "test": "IT-8",
            "mode": mode,
            "status": "running",
            "started_at": now_iso(),
            "steps": [],
            "run_id": uuid.uuid4().hex[:12],
        }

    @asynccontextmanager
    async def step(self, name: str) -> Any:
        record: dict[str, Any] = {"step": name, "status": "running", "started_at": now_iso()}
        started = time.perf_counter()
        try:
            yield record
        except StepFailure:
            record["status"] = "failed"
            raise
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = type(exc).__name__
            raise StepFailure(name, str(exc)) from exc
        else:
            record["status"] = "passed"
        finally:
            record["duration_ms"] = int((time.perf_counter() - started) * 1000)
            self.data["steps"].append(record)

    def write(self, status: str) -> None:
        self.data["status"] = status
        self.data["finished_at"] = now_iso()
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.out.write_text(json.dumps(self.data, indent=2, default=str), encoding="utf-8")


class LogCapture(logging.Handler):
    """Collects log messages so a PII check can prove the CSV never reached a log."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    def text(self) -> str:
        return "\n".join(self.messages)


def new_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://api.test",
        timeout=120.0,
    )


async def login(client: httpx.AsyncClient, email: str, password: str) -> None:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    must(response, "/api/v1/auth/login")
    token = response.json().get("csrf_token")
    if not token:
        raise AssertionError("login returned no csrf token")
    client.headers["X-CSRF-Token"] = str(token)


async def create_pool(
    admin: httpx.AsyncClient,
    *,
    title: str,
    template: dict[str, Any],
    lot_plan: list[dict[str, Any]],
    pool_timeline: dict[str, Any],
) -> str:
    """The same admin-route creation ``tools/it7_live.py`` uses, over ASGI."""
    body = {
        "title": title,
        "template": template,
        "lot_plan": lot_plan,
        "timeline": pool_timeline,
        "require_paypal_link": False,
        "rule_version": "allocation_v1",
    }
    created = must(await admin.post("/api/v1/admin/pools", json=body)).json()
    published = must(
        await admin.post(f"/api/v1/admin/pools/{created['pool_id']}/publish", json={})
    ).json()
    if published.get("status") != "PUBLISHED":
        raise AssertionError(f"publish answered {published.get('status')}")
    return str(created["pool_id"])


def structured(
    seats: int, price_cents: int, *, total_capacity: int | None = None
) -> dict[str, Any]:
    """A bid exactly sized for one lot: MOQ and capacity equal its seats."""
    total = seats if total_capacity is None else total_capacity
    return {
        "v": 1,
        "product_key": "monitor-27-4k",
        "condition": "NEW",
        "bundle_contents": ["monitor", "stand", "power cable"],
        "capacity": seats,
        "target_quantity": seats,
        "moq": seats,
        "tiers": [{"min_qty": seats, "item_price_cents": price_cents}],
        "shipping_cents_by_zone": {},
        "tax": {"mode": "INCLUDED"},
        "delivery": {"sla_days": 7},
        "returns": {"days": 30},
        "valid_until": "2027-12-31T00:00:00Z",
        "total_capacity": total,
        "evidence": {"note": "units reserved in the warehouse", "url": None},
    }


async def drive(
    drainer: Any,
    kinds: tuple[str, ...],
    predicate: Any,
    *,
    deadline_s: float,
    what: str,
    interval: float = 0.4,
) -> None:
    """Run due jobs of these kinds until ``predicate`` holds, or fail naming it."""
    deadline = time.monotonic() + deadline_s
    while True:
        await drainer.run_due(kinds=kinds)
        if await predicate():
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(interval)


async def order_statuses(factory: Any, buyer_order_ids: list[str]) -> dict[str, str]:
    from sqlalchemy import text

    async with factory() as session:
        return {
            value: str(
                await session.scalar(
                    text("SELECT status::text FROM buyer_orders WHERE id = :id"),
                    {"id": UUID(value)},
                )
                or "MISSING"
            )
            for value in buyer_order_ids
        }


async def read_sim(factory: Any, *, sim_run_id: str, pool_id: str) -> dict[str, Any]:
    from sqlalchemy import text

    async with factory() as session:
        results = await session.scalar(
            text("SELECT results FROM sim_runs WHERE id = :id"), {"id": UUID(sim_run_id)}
        )
        pool = (
            await session.execute(
                text(
                    "SELECT mode::text, status::text, entries_count, seed_is_demo "
                    "FROM pools WHERE id = :pool"
                ),
                {"pool": UUID(pool_id)},
            )
        ).one()
        allocations = await session.scalar(
            text("SELECT count(*) FROM allocations WHERE pool_id = :pool"),
            {"pool": UUID(pool_id)},
        )
        entries = await session.scalar(
            text("SELECT count(*) FROM pool_entries WHERE pool_id = :pool"),
            {"pool": UUID(pool_id)},
        )
    return {
        "results": results,
        "mode": str(pool[0]),
        "status": str(pool[1]),
        "entries_count": int(pool[2]),
        "seed_is_demo": bool(pool[3]),
        "allocations": int(allocations or 0),
        "entries": int(entries or 0),
    }


async def read_captures(factory: Any, lot_id: str) -> list[dict[str, Any]]:
    """Completed captures for one lot, one row per buyer order, newest first."""
    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (bo.id) bo.id, bo.total_cents, "
                    "c.paypal_capture_id, c.amount_cents, "
                    "(SELECT paypal_order_id FROM paypal_orders "
                    " WHERE buyer_order_id = bo.id ORDER BY attempt DESC LIMIT 1) "
                    "FROM buyer_orders bo JOIN paypal_captures c "
                    "ON c.buyer_order_id = bo.id AND c.status = 'COMPLETED' "
                    "WHERE bo.lot_id = :lot AND bo.status = 'CAPTURED' "
                    "ORDER BY bo.id, c.created_at DESC"
                ),
                {"lot": UUID(lot_id)},
            )
        ).all()
    return [
        {
            "buyer_order_id": str(row[0]),
            "total_cents": int(row[1]),
            "paypal_capture_id": str(row[2]),
            "amount_cents": int(row[3]),
            "paypal_order_id": None if row[4] is None else str(row[4]),
        }
        for row in rows
    ]


async def read_tracker_statuses(factory: Any, lot_id: str) -> list[str]:
    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text("SELECT paypal_tracker_status FROM shipments WHERE lot_id = :lot"),
                {"lot": UUID(lot_id)},
            )
        ).scalars()
        values = list(rows)
    return [str(value) for value in values]


async def seed_fake_verification(factory: Any, gateway: Any, lot_id: str) -> int:
    """Make the fake gateway's GETs answer with the captures the run just made.

    ``FakePayPalGateway.capture_authorization`` records the capture but does not
    rebuild the order mirror; the verification service checks the order's capture
    list, so the harness (not the backend) completes the fake's own mirror.
    """
    from fairpool.domain.payments import PayPalCapture

    captures = await read_captures(factory, lot_id)
    for item in captures:
        paypal_order_id = item["paypal_order_id"]
        if paypal_order_id is None:
            raise AssertionError("a captured order has no provider order identity")
        existing = gateway.orders.get(paypal_order_id)
        if existing is None:
            raise AssertionError("the fake gateway has no order mirror for the capture")
        gateway.orders[paypal_order_id] = replace(
            existing,
            captures=[
                PayPalCapture(
                    item["paypal_capture_id"], "COMPLETED", item["amount_cents"], True, None
                )
            ],
        )
    return len(captures)


async def first_sse_frame(app: Any, cookie: str) -> tuple[int, dict[str, str], str]:
    """Drive the ASGI app directly: ``httpx.ASGITransport`` waits for the stream to end."""
    received: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    headers = [
        (b"cookie", f"__Host-session={cookie}".encode()),
        (b"accept", b"text/event-stream"),
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "headers": headers,
        "scheme": "https",
        "path": "/api/v1/merchant/events",
        "raw_path": b"/api/v1/merchant/events",
        "query_string": b"",
        "server": ("api.test", 443),
        "client": ("127.0.0.1", 50000),
        "root_path": "",
    }

    async def receive() -> dict[str, Any]:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict[str, Any]) -> None:
        received.put_nowait(message)

    task = asyncio.create_task(app(scope, receive, send))
    try:
        start = await asyncio.wait_for(received.get(), timeout=5.0)
        if start.get("type") != "http.response.start":
            raise AssertionError("the stream did not answer with a response start")
        response_headers = {
            key.decode().lower(): value.decode() for key, value in start.get("headers", [])
        }
        body = ""
        while "event: tick" not in body:
            message = await asyncio.wait_for(received.get(), timeout=5.0)
            if message.get("type") != "http.response.body":
                raise AssertionError("the stream answered with a non-body message")
            body += str(message.get("body", b"").decode())
            if not message.get("more_body", False):
                break
        return int(start["status"]), response_headers, body
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def configure_fake_environment() -> None:
    os.environ["APP_ENV"] = "local"
    os.environ["PAYMENT_ROUTER"] = "fake"
    os.environ["PAYMENT_MODE"] = "authorize_capture"
    os.environ["PAYMENT_APPROVAL_UI"] = "redirect"
    os.environ["AI_ENABLED"] = "false"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["SEARCH_BACKEND"] = "postgres"
    os.environ["PUBLIC_BASE_URL"] = "https://api.test"
    os.environ["BEACON_MODE"] = "demo"
    os.environ["SHIPMENT_TRACKING_ENABLED"] = "true"
    os.environ["MOCK_TOGGLES_ENABLED"] = "false"
    os.environ["WEBHOOKS_ENABLED"] = "false"


def assert_no_forbidden(payload: Any, *, password: str) -> None:
    rendered = json.dumps(payload, default=str)
    forbidden = [
        SHIPPING["name"],
        SHIPPING["line1"],
        SHIPPING["city"],
        SHIPPING["postal_code"],
    ]
    if len(password) >= 6:
        forbidden.append(password)
    for value in forbidden:
        if value and value in rendered:
            raise AssertionError("the report would carry a secret or an address")


async def run_fake(args: argparse.Namespace, report: Report) -> None:
    from fairpool.api.app import create_app
    from fairpool.api.deps import database_session
    from fairpool.api.merchant_api.app import app as merchant_api_app
    from fairpool.config import Settings
    from fairpool.db.session import create_engine
    from fairpool.wiring import checkout_services, worker_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker

    it7 = load_it7()
    password = os.environ.get("IT8_LOCAL_PASSWORD", "")
    if not password:
        raise SystemExit(
            "IT-8: set IT8_LOCAL_PASSWORD (a local fixture password, never printed) and retry"
        )
    configure_fake_environment()
    os.environ["DATABASE_URL"] = loopback_database_url()
    settings = Settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    surface = checkout_services(settings)
    gateway = surface.router.gateway
    app = create_app(settings)
    app.state.checkout_services = surface
    app.state.fulfillment_gateway = gateway
    app.state.session_factory = factory
    merchant_api_app.state.fulfillment_gateway = gateway
    merchant_api_app.state.fulfillment_service = None

    async def request_session() -> Any:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            if session.in_transaction():
                await session.commit()

    app.dependency_overrides[database_session] = request_session
    merchant_api_app.dependency_overrides[database_session] = request_session
    handlers = worker_handlers(settings, surface)

    class ScopedDrainer(it7.Drainer):
        """The IT-7 worker, but claims only this run's jobs.

        The local ``fairpool`` database keeps pending jobs from earlier harness
        attempts. Claiming every due job of a kind would execute those abandoned
        rows and could fail this run for data it never wrote.
        """

        def __init__(self) -> None:
            super().__init__(factory, handlers)
            self.allowed: set[str] = set()

        async def run_due(
            self,
            *,
            kinds: tuple[str, ...] | None = None,
            exclude: tuple[str, ...] = (),
            limit: int = 200,
        ) -> int:
            allowed_kinds = tuple(k for k in (kinds or self.handlers) if k not in exclude)
            if not allowed_kinds or not self.allowed:
                return 0
            count = 0
            while count < limit:
                async with self.factory.begin() as session:
                    job = await self._claim_one(session, allowed_kinds)
                if job is None:
                    break
                await self._execute(job)
                count += 1
            self.ran += count
            return count

        async def _claim_one(self, session: Any, kinds: tuple[str, ...]) -> Any:
            from fairpool.infra.jobs import CLAIM_LOCK, ClaimedJob
            from sqlalchemy import text

            ids = ",".join(sorted(self.allowed))
            kind_list = ",".join(kinds)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CLAIM_LOCK})
            await session.execute(
                text(
                    "WITH expired AS (SELECT id FROM jobs WHERE status = 'RUNNING' "
                    "AND locked_until < now() FOR UPDATE SKIP LOCKED) "
                    "UPDATE jobs SET status = CASE WHEN attempts >= max_attempts "
                    "THEN 'FAILED'::job_status ELSE 'PENDING'::job_status END, "
                    "locked_by = NULL, locked_until = NULL "
                    "WHERE id IN (SELECT id FROM expired)"
                )
            )
            row = (
                await session.execute(
                    text(
                        "SELECT j.id, j.concurrency_key FROM jobs j "
                        "WHERE j.status = 'PENDING' AND j.run_at <= now() "
                        "AND j.kind = ANY(string_to_array(:kinds, ',')) "
                        "AND (j.concurrency_key IS NULL OR NOT EXISTS ("
                        "  SELECT 1 FROM jobs r WHERE r.status = 'RUNNING' "
                        "  AND r.concurrency_key = j.concurrency_key)) "
                        "AND (j.payload->>'pool_id' = ANY(string_to_array(:ids, ',')) "
                        "  OR j.payload->>'lot_id' = ANY(string_to_array(:ids, ',')) "
                        "  OR j.payload->>'buyer_order_id' = ANY(string_to_array(:ids, ',')) "
                        "  OR j.payload->>'sim_run_id' = ANY(string_to_array(:ids, ','))) "
                        "ORDER BY j.run_at, j.created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
                    ),
                    {"kinds": kind_list, "ids": ids},
                )
            ).first()
            if row is None:
                return None
            claimed = (
                await session.execute(
                    text(
                        "UPDATE jobs SET status = 'RUNNING', locked_by = :worker, "
                        "locked_until = now() + make_interval(secs => :lease), "
                        "attempts = attempts + 1 WHERE id = :id "
                        "RETURNING id, kind, payload, attempts, max_attempts"
                    ),
                    {"worker": self.worker_id, "lease": 300, "id": row[0]},
                )
            ).one()
            return ClaimedJob(
                id=claimed[0],
                kind=claimed[1],
                payload=claimed[2],
                attempts=claimed[3],
                max_attempts=claimed[4],
            )

    drainer = ScopedDrainer()
    clients: dict[str, httpx.AsyncClient] = {}
    report.data["environment"] = {
        "router": "fake",
        "mode": "authorize_capture",
        "app_env": "local",
        "database": "loopback",
        "ai_enabled": False,
        # The login, join, agent and verification limits stay off so the fixtures can
        # run; ``rate_limits`` below records the one limit this run exercised.
        "rate_limit_enabled": False,
    }
    try:
        async with report.step("fixtures") as record:
            stamp = uuid.uuid4().hex[:8]
            accounts = await it7.make_fixtures(factory, settings, password, stamp)
            for key in ("admin", "merchant1", "merchant2", "buyer1", "buyer2", "buyer3"):
                clients[key] = new_client(app)
                await login(clients[key], accounts[key]["email"], password)
            record["accounts"] = sorted(clients)
            record["note"] = "in-process fixtures, IT-7 pattern"

        admin, merchant1, merchant2 = clients["admin"], clients["merchant1"], clients["merchant2"]
        buyer_keys = ("buyer1", "buyer2", "buyer3")
        api: dict[str, str] = {}
        merchant_api_called: list[str] = []

        def called(operation: str) -> None:
            """Record a keyed operation only after it answered (IT-8 honesty)."""
            if operation not in merchant_api_called:
                merchant_api_called.append(operation)

        now = datetime.now(UTC)
        pool_timeline = it7.timeline(
            now,
            open_s=1,
            close_s=10,
            beacon_delay_s=1,
            bid_window_s=10,
            offer_window_s=180,
            fund_deadline_s=300,
            capture_grace_s=60,
            pending_wait_s=60,
            max_refill_waves=1,
        )

        async with report.step("pool_created") as record:
            pool_id = await create_pool(
                admin,
                title=f"IT8 monitors {stamp}",
                template=TEMPLATE,
                lot_plan=LOT_PLAN,
                pool_timeline=pool_timeline,
            )
            record["pool_id"] = pool_id
            report.data["pool_id"] = pool_id
            drainer.allowed.add(pool_id)

        async def pool_open() -> bool:
            body = must(await admin.get(f"/api/v1/pools/{pool_id}")).json()
            return body.get("status") == "OPEN"

        async with report.step("pool_open") as record:
            await drive(
                drainer,
                ("pool.open",),
                pool_open,
                deadline_s=30,
                what="the pool to open",
                interval=0.5,
            )
            record["status"] = "OPEN"

        async with report.step("buyers_joined") as record:
            entries: dict[str, str] = {}
            for key in buyer_keys:
                client = clients[key]
                confirmed = must(
                    await client.post(
                        "/api/v1/intake/manual",
                        json={
                            "pool_id": pool_id,
                            "delivery": {"region": "NY"},
                            "required_by": "2027-12-31",
                            "max_total_cents": 60000,
                            "firm": [],
                            "preferences": [],
                        },
                    )
                ).json()
                joined = must(
                    await client.post(
                        f"/api/v1/pools/{pool_id}/entries",
                        json={"confirmed_request_id": confirmed["confirmed_request_id"]},
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    )
                ).json()
                receipt = joined.get("receipt") or {}
                if not receipt.get("signature"):
                    raise AssertionError(f"{key} join returned no signed receipt")
                entries[key] = str(joined["entry_id"])
            record["entries"] = entries

        async def lots_bidding() -> bool:
            lots = await it7.read_lots(factory, pool_id)
            # pool.allocate writes the lots and their lot.bid_open jobs; their ids are
            # known only after it runs, so the scoped drain learns them here.
            drainer.allowed.update(lot["lot_id"] for lot in lots)
            return len(lots) == 2 and all(lot["status"] == "BIDDING" for lot in lots)

        async with report.step("lots_open_for_bidding") as record:
            close_at = datetime.fromisoformat(str(pool_timeline["close_at"]))
            deadline = time.monotonic() + max(
                20.0, (close_at - datetime.now(UTC)).total_seconds() + 90
            )
            await drive(
                drainer,
                ("pool.close", "pool.seed", "pool.allocate", "lot.bid_open"),
                lots_bidding,
                deadline_s=max(1.0, deadline - time.monotonic()),
                what="pool.close, pool.seed, pool.allocate and lot.bid_open",
                interval=0.5,
            )
            lots = await it7.read_lots(factory, pool_id)
            record["lots"] = {lot["lot_order"]: lot["status"] for lot in lots}
            report.data["lots"] = lots

        lots = await it7.read_lots(factory, pool_id)
        drainer.allowed.update(lot["lot_id"] for lot in lots)
        lot1 = next(lot for lot in lots if lot["lot_order"] == 1)
        lot2 = next(lot for lot in lots if lot["lot_order"] == 2)

        async with report.step("merchants_bid") as record:
            saved = must(
                await merchant1.put(
                    f"/api/v1/merchant/lots/{lot1['lot_id']}/bid",
                    json={"structured": structured(2, 47_000)},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            confirmed = must(
                await merchant1.post(
                    f"/api/v1/merchant/bids/{saved['bid_id']}/confirm",
                    json={"revision": saved["revision"]},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            if confirmed.get("status") != "CONFIRMED":
                raise AssertionError(f"lot 1 console bid ended {confirmed.get('status')}")
            record["merchant1_lot1_bid"] = saved["bid_id"]

            saved2 = must(
                await merchant2.put(
                    f"/api/v1/merchant/lots/{lot2['lot_id']}/bid",
                    json={"structured": structured(1, 48_000)},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            confirmed2 = must(
                await merchant2.post(
                    f"/api/v1/merchant/bids/{saved2['bid_id']}/confirm",
                    json={"revision": saved2["revision"]},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            if confirmed2.get("status") != "CONFIRMED":
                raise AssertionError(f"lot 2 console bid ended {confirmed2.get('status')}")
            record["merchant2_lot2_bid"] = saved2["bid_id"]
            report.data["bids"] = {
                "merchant1_lot1": saved["bid_id"],
                "merchant2_lot2": saved2["bid_id"],
            }

        async with report.step("merchant_agent_api_bidding") as record:
            created = must(
                await merchant1.post(
                    "/api/v1/merchant/api-keys",
                    json={"name": "it8-all", "scopes": ALL_SCOPES},
                ),
                expect=(201,),
            ).json()
            api["key"] = str(created["key"])
            api["key_id"] = str(created["id"])
            key_headers = {"Authorization": f"Bearer {api['key']}"}
            narrow = must(
                await merchant2.post(
                    "/api/v1/merchant/api-keys",
                    json={"name": "it8-narrow", "scopes": ["lots:read"]},
                ),
                expect=(201,),
            ).json()
            narrow_headers = {"Authorization": f"Bearer {narrow['key']}"}

            anonymous = await merchant1.get("/merchant-api/v1/lots")
            if anonymous.status_code != 401:
                raise AssertionError(f"no key answered {anonymous.status_code}")
            record["missing_key_status"] = 401
            refused = await merchant2.get(
                f"/merchant-api/v1/lots/{lot1['lot_id']}/progress", headers=narrow_headers
            )
            if refused.status_code != 403:
                raise AssertionError(f"a missing scope answered {refused.status_code}")
            record["missing_scope_status"] = 403

            listed = must(await merchant1.get("/merchant-api/v1/lots", headers=key_headers)).json()
            called("list_lots")
            listed_ids = {str(item["lot_id"]) for item in listed}
            if {lot1["lot_id"], lot2["lot_id"]} - listed_ids:
                raise AssertionError("list_lots did not list both lots")
            one = must(
                await merchant1.get(f"/merchant-api/v1/lots/{lot1['lot_id']}", headers=key_headers)
            ).json()
            called("get_lot")
            if int(one["seats"]) != 2:
                raise AssertionError("get_lot did not carry the lot's seats")
            listed_bids = must(
                await merchant1.get("/merchant-api/v1/bids", headers=key_headers)
            ).json()
            called("list_bids")
            bid_ids = {str(item["bid_id"]) for item in listed_bids["items"]}
            if str(report.data["bids"]["merchant1_lot1"]) not in bid_ids:
                raise AssertionError("list_bids did not list the console bid")
            one_bid = must(
                await merchant1.get(
                    f"/merchant-api/v1/bids/{report.data['bids']['merchant1_lot1']}",
                    headers=key_headers,
                )
            ).json()
            called("get_bid")
            if one_bid.get("status") != "CONFIRMED":
                raise AssertionError("get_bid did not show the confirmed bid")

            key_bid = must(
                await merchant1.put(
                    f"/merchant-api/v1/lots/{lot2['lot_id']}/bid",
                    json={
                        "structured": structured(1, 47_000, total_capacity=3),
                        "notes": None,
                        "confirmed": True,
                    },
                    headers={**key_headers, "Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            if key_bid.get("status") != "CONFIRMED":
                raise AssertionError(f"submit_bid ended {key_bid.get('status')}")
            if len(str(key_bid["receipt"]["hash"])) != 64:
                raise AssertionError("submit_bid returned no 64-hex receipt")
            called("submit_bid")
            record["called"] = list(merchant_api_called)
            report.data["merchant_api"] = {
                "key_id": str(created["id"]),
                "called": list(record["called"]),
                "missing_key_status": 401,
                "missing_scope_status": 403,
            }
            del key_headers, narrow_headers

        async def lots_checkout_open() -> bool:
            current = {
                lot["lot_order"]: lot["status"] for lot in await it7.read_lots(factory, pool_id)
            }
            return current.get(1) == "CHECKOUT_OPEN" and current.get(2) == "CHECKOUT_OPEN"

        async with report.step("awarded_checkout_open") as record:
            close_at = datetime.fromisoformat(str(pool_timeline["close_at"]))
            bid_close = close_at + timedelta(seconds=int(pool_timeline["bid_window_s"]))
            await drive(
                drainer,
                ("lot.bid_close", "lot.award", "lot.open_checkout"),
                lots_checkout_open,
                deadline_s=max(20.0, (bid_close - datetime.now(UTC)).total_seconds() + 90),
                what="lot.bid_close, lot.award and lot.open_checkout",
                interval=0.5,
            )
            statuses = {
                lot["lot_order"]: lot["status"] for lot in await it7.read_lots(factory, pool_id)
            }
            record["lots"] = statuses

        async with report.step("offers_continued_approved") as record:
            orders = await it7.read_orders(factory, pool_id)
            if len(orders) != 3:
                raise AssertionError(f"expected three offers, saw {len(orders)}")
            user_to_key = {str(accounts[key]["user_id"]): key for key in buyer_keys}
            targets: list[dict[str, Any]] = []
            for order in orders:
                buyer_key = user_to_key.get(str(order["user_id"]))
                if buyer_key is None:
                    raise AssertionError("an offer belongs to an account outside the fixtures")
                body = must(
                    await clients[buyer_key].post(
                        f"/api/v1/offers/{order['buyer_order_id']}/continue",
                        json={"shipping": SHIPPING},
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    )
                ).json()
                paypal_order_id = body.get("paypal_order_id")
                if not paypal_order_id:
                    raise AssertionError("continue returned no provider order id")
                # The fake gateway gives every order the same payer id, and the
                # approval checks refuse a payer held by another seat in the pool
                # (DUPLICATE_PAYER). Distinct fixture buyers need distinct fake ids.
                if paypal_order_id in gateway.orders:
                    gateway.orders[paypal_order_id] = replace(
                        gateway.orders[paypal_order_id],
                        payer_id=f"IT8-PAYER-{len(targets) + 1}",
                    )
                answer = must(
                    await clients[buyer_key].post(
                        f"/api/v1/offers/{order['buyer_order_id']}/approved",
                        json={"paypal_order_id": paypal_order_id},
                    )
                ).json()
                if answer.get("status") != "APPROVED":
                    raise AssertionError(
                        f"approved answered {answer.get('status')} {answer.get('reason')}"
                    )
                targets.append(
                    {
                        "buyer_order_id": order["buyer_order_id"],
                        "buyer_key": buyer_key,
                        "lot_id": order["lot_id"],
                        "total_cents": int(order["total_cents"]),
                        "user_id": str(order["user_id"]),
                    }
                )
            record["orders"] = len(targets)
            drainer.allowed.update(target["buyer_order_id"] for target in targets)
            report.data["checkout_orders"] = [
                {
                    "buyer": target["buyer_key"],
                    "lot_order": 1 if target["lot_id"] == lot1["lot_id"] else 2,
                    "buyer_order_id": target["buyer_order_id"],
                    "total_cents": target["total_cents"],
                }
                for target in targets
            ]
            report.data["_targets"] = targets

        targets = report.data["_targets"]
        lot1_targets = [t for t in targets if t["lot_id"] == lot1["lot_id"]]

        async with report.step("orders_authorized") as record:
            ids = [t["buyer_order_id"] for t in targets]

            async def all_authorized() -> bool:
                statuses = await order_statuses(factory, ids)
                return all(status == "AUTHORIZED" for status in statuses.values())

            await drive(
                drainer,
                ("order.authorize",),
                all_authorized,
                deadline_s=60,
                what="the three order.authorize jobs",
                interval=0.5,
            )
            record["statuses"] = await order_statuses(factory, ids)

        async with report.step("lot_funded") as record:

            async def lot1_funding() -> bool:
                return await it7.read_lot_status(factory, lot1["lot_id"]) == "FUNDING"

            await drive(
                drainer,
                ("lot.try_fund",),
                lot1_funding,
                deadline_s=30,
                what="lot 1 FUNDING",
                interval=0.4,
            )
            if len(lot1_targets) != 2:
                raise AssertionError(f"lot 1 has {len(lot1_targets)} offers, not two")
            for target in lot1_targets:
                await drainer.run_capture(UUID(target["buyer_order_id"]))

            async def lot1_funded() -> bool:
                return await it7.read_lot_status(factory, lot1["lot_id"]) in {
                    "FUNDED",
                    "CLOSED",
                }

            await drive(
                drainer,
                ("lot.try_fund",),
                lot1_funded,
                deadline_s=30,
                what="lot 1 FUNDED on two completed captures",
                interval=0.4,
            )
            ledger = await it7.read_ledger(factory, lot1["lot_id"])
            completed = [
                entry for entry in ledger["entries"] if entry["kind"] == "CAPTURE_COMPLETED"
            ]
            if len(completed) != 2:
                raise AssertionError(f"lot 1 ledger has {len(completed)} completed captures")
            expected = sum(target["total_cents"] for target in lot1_targets)
            if ledger["net_paid_cents"] != expected:
                raise AssertionError(
                    f"lot 1 net paid {ledger['net_paid_cents']} != offered {expected}"
                )
            users = {target["user_id"] for target in lot1_targets}
            if len(users) != 2:
                raise AssertionError("the two lot-1 captures do not come from distinct buyers")
            record["status"] = await it7.read_lot_status(factory, lot1["lot_id"])
            record["ledger_capture_entries"] = len(completed)
            record["net_paid_cents"] = ledger["net_paid_cents"]
            record["distinct_buyers"] = len(users)
            report.data["lot1"] = {
                "lot_id": lot1["lot_id"],
                "status": record["status"],
                "ledger_capture_entries": len(completed),
                "net_paid_cents": ledger["net_paid_cents"],
                "distinct_buyers": len(users),
            }

        seeded = await seed_fake_verification(factory, gateway, lot1["lot_id"])
        order_totals = {t["buyer_order_id"]: t["total_cents"] for t in lot1_targets}

        async with report.step("fulfillment") as record:
            progress = must(
                await merchant1.get(f"/api/v1/merchant/lots/{lot1['lot_id']}/progress")
            ).json()
            if progress.get("status") not in {"FUNDED", "CLOSED"}:
                raise AssertionError(f"progress shows {progress.get('status')}")
            if int(progress["seats"]) != 2 or int(progress["moq"]) != 2:
                raise AssertionError("progress did not carry seats and MOQ")
            if int(progress["captures_completed"]) != 2:
                raise AssertionError("progress did not count two completed captures")
            if int(progress["counts"].get("CAPTURED", 0)) != 2:
                raise AssertionError("progress did not count two CAPTURED orders")
            if "SIMULATED" not in progress["labels"] or "SANDBOX" not in progress["labels"]:
                raise AssertionError(f"progress labels are {progress['labels']}")

            rows = must(
                await merchant1.get(f"/api/v1/merchant/lots/{lot1['lot_id']}/fulfillment")
            ).json()
            if len(rows) != 2:
                raise AssertionError(f"fulfillment returned {len(rows)} rows, not two")
            if {row["buyer_order_id"] for row in rows} != set(order_totals):
                raise AssertionError("fulfillment rows do not match the two captured orders")

            logs = LogCapture()
            root = logging.getLogger()
            root.addHandler(logs)
            try:
                csv_response = must(
                    await merchant1.get(
                        f"/api/v1/merchant/lots/{lot1['lot_id']}/fulfillment",
                        headers={"Accept": "text/csv"},
                    )
                )
            finally:
                root.removeHandler(logs)
            if csv_response.headers.get("content-type") != "text/csv; charset=utf-8":
                raise AssertionError("the CSV content type is wrong")
            if "attachment" not in csv_response.headers.get("content-disposition", ""):
                raise AssertionError("the CSV is not an attachment")
            lines = csv_response.text.split("\r\n")
            header = (
                '"buyer_order_id","name","line1","line2","city","region","postal_code",'
                '"country_code","item_cents","shipping_cents","tax_cents","total_cents",'
                '"paypal_capture_id"'
            )
            if lines[0] != header:
                raise AssertionError("the CSV header does not match the contract")
            if len(lines) != 4 or lines[-1] != "":
                raise AssertionError(f"the CSV has {len(lines)} lines, not header plus two rows")
            for line in lines[1:3]:
                if not line.startswith('"') or not line.endswith('"'):
                    raise AssertionError("a CSV row is not fully quoted")
                if line.count('","') != 12:
                    raise AssertionError("a CSV row has an unquoted field")
            logged = logs.text()
            for value in (
                SHIPPING["name"],
                SHIPPING["line1"],
                SHIPPING["city"],
                SHIPPING["postal_code"],
            ):
                if value in logged:
                    raise AssertionError("a delivery address reached the logs")

            shipment_body = {
                "shipments": [
                    {
                        "buyer_order_id": target["buyer_order_id"],
                        "carrier": "UPS",
                        "tracking_number": f"IT8TRACK{index}",
                    }
                    for index, target in enumerate(lot1_targets, start=1)
                ]
            }
            shipments = must(
                await merchant1.post(
                    f"/api/v1/merchant/lots/{lot1['lot_id']}/shipments",
                    json=shipment_body,
                ),
                expect=(202,),
            ).json()
            if int(shipments["accepted"]) != 2:
                raise AssertionError(f"shipments accepted {shipments['accepted']} rows")
            if [row["status"] for row in shipments["rows"]] != ["RECORDED", "RECORDED"]:
                raise AssertionError("a shipment row was not RECORDED")
            await drainer.run_due(kinds=("shipments.submit",))
            tracker = await read_tracker_statuses(factory, lot1["lot_id"])
            if tracker != ["SUBMITTED", "SUBMITTED"]:
                raise AssertionError(f"tracker statuses are {tracker}")

            manifest = must(
                await merchant1.get(f"/api/v1/merchant/lots/{lot1['lot_id']}/verification-manifest")
            ).json()
            expected_total = sum(order_totals.values())
            if manifest.get("funded") is not True:
                raise AssertionError("the manifest does not say funded")
            if int(manifest["expected_captured_total_cents"]) != expected_total:
                raise AssertionError("the manifest total does not match the captures")
            if len(manifest["items"]) != 2:
                raise AssertionError("the manifest does not list two captures")
            rendered = json.dumps(manifest)
            for value in (
                SHIPPING["name"],
                SHIPPING["line1"],
                SHIPPING["city"],
                SHIPPING["postal_code"],
            ):
                if value in rendered:
                    raise AssertionError("the manifest carries buyer personal data")
            if set(manifest["items"][0]) != {
                "paypal_order_id",
                "paypal_capture_id",
                "amount_cents",
                "captured_at",
            }:
                raise AssertionError("a manifest item carries an unexpected field")

            verification = must(
                await merchant1.get(f"/api/v1/merchant/lots/{lot1['lot_id']}/verification")
            ).json()
            if verification.get("all_match") is not True:
                raise AssertionError("the fake-router verification did not match")
            if int(verification["matched"]) != 2 or int(verification["total"]) != 2:
                raise AssertionError(
                    f"verification matched {verification['matched']}/{verification['total']}"
                )
            if (
                int(verification["expected_captured_total_cents"])
                != int(verification["paypal_captured_total_cents"])
                or int(verification["paypal_captured_total_cents"]) != expected_total
            ):
                raise AssertionError("the verification totals do not add up")

            record["progress"] = {
                "status": progress["status"],
                "seats": int(progress["seats"]),
                "moq": int(progress["moq"]),
                "captures_completed": int(progress["captures_completed"]),
                "counts": progress["counts"],
                "labels": progress["labels"],
            }
            record["fulfillment_rows"] = len(rows)
            record["csv_rows"] = len(lines) - 2
            record["csv_quoted"] = True
            record["logs_clean"] = True
            record["shipments_accepted"] = int(shipments["accepted"])
            record["tracker_statuses"] = tracker
            record["manifest_items"] = len(manifest["items"])
            record["manifest_no_pii"] = True
            record["verification"] = {
                "matched": int(verification["matched"]),
                "total": int(verification["total"]),
                "all_match": bool(verification["all_match"]),
                "expected_captured_total_cents": int(verification["expected_captured_total_cents"]),
                "paypal_captured_total_cents": int(verification["paypal_captured_total_cents"]),
            }
            report.data["fulfillment"] = {
                "rows": len(rows),
                "csv_rows": len(lines) - 2,
                "shipments_accepted": int(shipments["accepted"]),
                "tracker_statuses": tracker,
                "manifest_items": len(manifest["items"]),
                "verification": record["verification"],
                "seeded_fake_orders": seeded,
            }

        async with report.step("merchant_agent_api") as record:
            key_headers = {"Authorization": f"Bearer {api['key']}"}
            anonymous = await merchant1.get("/merchant-api/v1/lots")
            if anonymous.status_code != 401:
                raise AssertionError(f"no key answered {anonymous.status_code}")

            progress = must(
                await merchant1.get(
                    f"/merchant-api/v1/lots/{lot1['lot_id']}/progress", headers=key_headers
                )
            ).json()
            called("get_lot_progress")
            rows = must(
                await merchant1.get(
                    f"/merchant-api/v1/lots/{lot1['lot_id']}/fulfillment", headers=key_headers
                )
            ).json()
            called("get_lot_fulfillment")
            if len(rows) != 2:
                raise AssertionError("the key's fulfillment read did not return two rows")
            replay = must(
                await merchant1.post(
                    f"/merchant-api/v1/lots/{lot1['lot_id']}/shipments",
                    headers=key_headers,
                    json={
                        "shipments": [
                            {
                                "buyer_order_id": target["buyer_order_id"],
                                "carrier": "UPS",
                                "tracking_number": f"IT8TRACK{index}",
                            }
                            for index, target in enumerate(lot1_targets, start=1)
                        ]
                    },
                ),
                expect=(202,),
            ).json()
            if int(replay["accepted"]) != 2 or [row["status"] for row in replay["rows"]] != [
                "RECORDED",
                "RECORDED",
            ]:
                raise AssertionError("the key's shipment replay was not RECORDED")
            called("submit_shipments")
            manifest = must(
                await merchant1.get(
                    f"/merchant-api/v1/lots/{lot1['lot_id']}/verification-manifest",
                    headers=key_headers,
                )
            ).json()
            called("get_verification_manifest")
            verification = must(
                await merchant1.get(
                    f"/merchant-api/v1/lots/{lot1['lot_id']}/verification",
                    headers=key_headers,
                )
            ).json()
            if verification.get("all_match") is not True:
                raise AssertionError("the key's verification did not match")
            called("get_lot_verification")

            document = must(await merchant1.get("/merchant-api/v1/openapi.json")).json()
            operation_ids = sorted(
                operation["operationId"]
                for path in document.get("paths", {}).values()
                for operation in path.values()
                if isinstance(operation, dict) and "operationId" in operation
            )
            if len(operation_ids) != 10:
                raise AssertionError(
                    f"the Merchant Agent API declares {len(operation_ids)} operationIds, not 10"
                )
            if tuple(operation_ids) != MERCHANT_API_OPERATIONS:
                raise AssertionError(f"the operationIds are {operation_ids}")

            calls = sorted(merchant_api_called)
            if tuple(calls) != MERCHANT_API_OPERATIONS:
                raise AssertionError(f"only these operations were called: {calls}")
            record["operation_ids"] = operation_ids
            record["called"] = calls
            record["progress_captures"] = int(progress["captures_completed"])
            record["manifest_items"] = len(manifest["items"])
            record["verification_all_match"] = bool(verification["all_match"])
            report.data["merchant_api"] = {
                "key_id": api["key_id"],
                "called": calls,
                "operation_ids": operation_ids,
                "missing_key_status": 401,
                "missing_scope_status": report.data["merchant_api"]["missing_scope_status"],
            }
            del key_headers

        async with report.step("merchant_sse") as record:
            cookie = merchant1.cookies.get("__Host-session")
            if not cookie:
                raise AssertionError("the merchant session cookie is missing")
            status, headers, frame = await first_sse_frame(app, cookie)
            if status != 200:
                raise AssertionError(f"the SSE feed answered {status}")
            if not headers.get("content-type", "").startswith("text/event-stream"):
                raise AssertionError("the SSE content type is wrong")
            if "event: tick" not in frame:
                raise AssertionError("the first SSE frame carried no tick")
            record["events"] = ["tick"]
            record["content_type"] = headers.get("content-type")

        async with report.step("simulation") as record:
            created = must(
                await admin.post(
                    "/api/v1/admin/sim/run",
                    json={"entries": 10_000, "merchants": 8, "seed": 7},
                ),
                expect=(202,),
            ).json()
            sim_run_id, sim_pool_id = str(created["sim_run_id"]), str(created["pool_id"])
            drainer.allowed.add(sim_run_id)
            started = time.perf_counter()
            await drainer.run_due(kinds=("sim.run",))
            wall_ms = int((time.perf_counter() - started) * 1000)
            sim = await read_sim(factory, sim_run_id=sim_run_id, pool_id=sim_pool_id)
            results = sim["results"]
            if not isinstance(results, dict):
                raise AssertionError("the simulation stored no results")
            measured_ms = int(results.get("measured_ms", 10**9))
            if int(results.get("entries", 0)) != 10_000:
                raise AssertionError("the simulation did not store 10,000 entries")
            if measured_ms >= 10_000:
                raise AssertionError(f"the measured allocation took {measured_ms} ms")
            if sim["mode"] != "SIMULATION":
                raise AssertionError(f"the simulation pool is {sim['mode']}")
            if sim["status"] != "ALLOCATED":
                raise AssertionError(f"the simulation pool is {sim['status']}")
            if sim["allocations"] != 10_000 or sim["entries"] != 10_000:
                raise AssertionError(
                    f"the simulation has {sim['allocations']} allocations "
                    f"and {sim['entries']} entries"
                )
            listed = must(await admin.get("/api/v1/pools", params={"limit": 100})).json()
            listed_ids = {str(item["pool_id"]) for item in listed}
            if pool_id not in listed_ids:
                raise AssertionError("the live pool is missing from the public list")
            if sim_pool_id in listed_ids:
                raise AssertionError("the simulation pool reached the public pool list")
            audit = await admin.get(f"/api/v1/public/pools/{sim_pool_id}/audit")
            if audit.status_code != 404:
                raise AssertionError(f"the simulation audit answered {audit.status_code}")
            record["sim_pool_id"] = sim_pool_id
            record["measured_ms"] = measured_ms
            record["wall_ms"] = wall_ms
            record["allocations"] = sim["allocations"]
            record["mode"] = sim["mode"]
            record["public_list_absent"] = True
            record["public_audit_status"] = 404
            report.data["simulation"] = {
                "sim_run_id": sim_run_id,
                "pool_id": sim_pool_id,
                "entries": sim["entries"],
                "allocations": sim["allocations"],
                "measured_ms": measured_ms,
                "wall_ms": wall_ms,
                "mode": sim["mode"],
                "status": sim["status"],
                "public_list_absent": True,
                "public_audit_status": 404,
            }

        async with report.step("merchant_api_rate_limit") as record:
            # RATE_LIMIT_ENABLED is off for the rest of this run (limits stay out of the
            # way of the fixtures), so the switch is turned on for one fresh key and a
            # fresh 120/min window: the 121st request must answer 429 RATE_LIMITED.
            from fairpool.api.deps import MERCHANT_KEY_LIMIT
            from fairpool.infra.limits import SlidingWindowLimiter

            original_settings = merchant_api_app.state.settings
            merchant_api_app.state.settings = original_settings.model_copy(
                update={"rate_limit_enabled": True}
            )
            merchant_api_app.state.merchant_key_limiter = SlidingWindowLimiter(
                limit=MERCHANT_KEY_LIMIT
            )
            try:
                limited = must(
                    await merchant1.post(
                        "/api/v1/merchant/api-keys",
                        json={"name": "it8-rate", "scopes": ["lots:read"]},
                    ),
                    expect=(201,),
                ).json()
                limited_headers = {"Authorization": f"Bearer {limited['key']}"}
                for _ in range(MERCHANT_KEY_LIMIT):
                    allowed = await merchant1.get("/merchant-api/v1/lots", headers=limited_headers)
                    if allowed.status_code != 200:
                        raise AssertionError(
                            f"the keyed request under the limit answered {allowed.status_code}"
                        )
                refused = await merchant1.get("/merchant-api/v1/lots", headers=limited_headers)
                retry_after = refused.headers.get("retry-after", "")
                if refused.status_code != 429:
                    raise AssertionError(f"the 121st keyed request answered {refused.status_code}")
                if refused.json().get("error", {}).get("code") != "RATE_LIMITED":
                    raise AssertionError("the 429 did not carry RATE_LIMITED")
                if not retry_after.isdigit():
                    raise AssertionError("the 429 carried no Retry-After")
            finally:
                merchant_api_app.state.settings = original_settings
                merchant_api_app.state.merchant_key_limiter = SlidingWindowLimiter(
                    limit=MERCHANT_KEY_LIMIT
                )
            record["limit_per_minute"] = MERCHANT_KEY_LIMIT
            record["allowed"] = MERCHANT_KEY_LIMIT
            record["status"] = 429
            record["code"] = "RATE_LIMITED"
            record["retry_after"] = int(retry_after)
            report.data["rate_limits"] = {
                "switch": "RATE_LIMIT_ENABLED=false for the run",
                "per_key_429": {
                    "limit_per_minute": MERCHANT_KEY_LIMIT,
                    "allowed": MERCHANT_KEY_LIMIT,
                    "status": 429,
                    "code": "RATE_LIMITED",
                    "retry_after": int(retry_after),
                },
                "note": (
                    "the 120/min per-key boundary is proved by "
                    "test_the_121st_request_in_a_minute_is_rate_limited; this run turns "
                    "the switch on for one fresh key and checks the 429 for real"
                ),
            }
            del limited_headers

        async with report.step("metrics_scrape") as record:
            scrape = await admin.get("/metrics")
            if scrape.status_code != 200:
                raise AssertionError(f"/metrics answered {scrape.status_code}")
            if not scrape.headers.get("content-type", "").startswith("text/plain"):
                raise AssertionError("/metrics is not the Prometheus text format")
            families = sorted(
                {
                    line.split("{", 1)[0].split(" ", 1)[0]
                    for line in scrape.text.splitlines()
                    if line and not line.startswith("#")
                }
            )
            stages = sorted(
                {
                    line.split('stage="', 1)[1].split('"', 1)[0]
                    for line in scrape.text.splitlines()
                    if line.startswith("fairpool_funnel_buyer_orders{")
                }
            )
            if "fairpool_funnel_buyer_orders" not in families:
                raise AssertionError("the scrape carried no funnel gauge")
            record["content_type"] = scrape.headers.get("content-type")
            record["families"] = families
            record["funnel_stages"] = stages
            report.data["metrics"] = {
                "status": scrape.status_code,
                "content_type": scrape.headers.get("content-type"),
                "families": families,
                "funnel_stages": stages,
            }

        report.data.pop("_targets", None)
        final_lots = await it7.read_lots(factory, pool_id)
        report.data["final_lots"] = {
            lot["lot_order"]: {"lot_id": lot["lot_id"], "status": lot["status"]}
            for lot in final_lots
        }
        assert_no_forbidden(report.data, password=password)
        report.write("passed")
        print(f"\nIT-8 passed; report: {report.out}")
    finally:
        for client in clients.values():
            await client.aclose()
        merchant_api_app.dependency_overrides.clear()
        app.dependency_overrides.clear()
        merchant_api_app.state.fulfillment_gateway = None
        merchant_api_app.state.fulfillment_service = None
        closer = getattr(gateway, "close", None)
        if closer is not None:
            await closer()
        await engine.dispose()


async def run_live_verify(report: Report) -> None:
    """The optional read-only PayPal run for the IT-7 funded lot."""
    from fairpool.adapters.paypal.gateway import RestPayPalGateway
    from fairpool.config import Settings
    from fairpool.db.models import Award, Lot
    from fairpool.db.session import create_engine
    from fairpool.infra.clock import DbClock
    from fairpool.modules.fulfillment.manifest import manifest_items
    from fairpool.modules.fulfillment.service import AwardedLot
    from fairpool.modules.fulfillment.verification import verify_lot
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    os.environ["APP_ENV"] = "local"
    os.environ["PAYMENT_ROUTER"] = "single_seller"
    os.environ["PAYMENT_MODE"] = "authorize_capture"
    os.environ["AI_ENABLED"] = "false"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["SEARCH_BACKEND"] = "postgres"
    os.environ["DATABASE_URL"] = loopback_database_url()
    settings = Settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    report.data["environment"] = {
        "router": "single_seller",
        "mode": "authorize_capture",
        "app_env": "local",
        "database": "loopback",
        "read_only_provider": True,
    }
    try:
        async with report.step("it7_lot_present") as record:
            async with factory() as session:
                lot = await session.get(Lot, IT7_LOT_ID)
                award = await session.scalar(select(Award).where(Award.lot_id == IT7_LOT_ID))
                if lot is None or award is None:
                    raise AssertionError("the IT-7 funded lot is absent from the local database")
                items = await manifest_items(session, IT7_LOT_ID)
                capture_present = any(item["paypal_capture_id"] == IT7_CAPTURE_ID for item in items)
                if not capture_present:
                    raise AssertionError("the IT-7 capture is absent from the manifest")
                record["lot_status"] = str(lot.status)
                record["manifest_items"] = len(items)
                record["capture_present"] = True
                report.data["it7"] = {
                    "lot_id": str(IT7_LOT_ID),
                    "status": str(lot.status),
                    "manifest_items": len(items),
                    "capture_present": True,
                }

        async with report.step("live_verification") as record:
            gateway = RestPayPalGateway(settings)
            try:
                async with factory() as session:
                    lot = await session.get(Lot, IT7_LOT_ID)
                    award = await session.scalar(select(Award).where(Award.lot_id == IT7_LOT_ID))
                    if lot is None or award is None:
                        raise AssertionError("the IT-7 lot disappeared")
                    result = await verify_lot(
                        session,
                        awarded=AwardedLot(lot=lot, moq=int(award.moq)),
                        merchant_id=award.merchant_id,
                        gateway=gateway,
                        clock=DbClock(),
                    )
            finally:
                await gateway.close()
            matched = int(result["matched"])
            total = int(result["total"])
            expected = int(result["expected_captured_total_cents"])
            paypal_total = int(result["paypal_captured_total_cents"])
            if total < 1:
                raise AssertionError("the live verification had no items")
            if matched != total or result["all_match"] is not True:
                raise AssertionError(f"the live verification matched {matched}/{total}")
            if expected != paypal_total:
                raise AssertionError(
                    f"the live verification totals differ: expected {expected}, "
                    f"PayPal {paypal_total}"
                )
            record["matched"] = matched
            record["total"] = total
            record["all_match"] = True
            record["expected_captured_total_cents"] = expected
            record["paypal_captured_total_cents"] = paypal_total
            record["item_statuses"] = sorted(
                {str(item["paypal_capture_status"]) for item in result["items"]}
            )
            report.data["live_verification"] = {
                "lot_id": str(IT7_LOT_ID),
                "matched": matched,
                "total": total,
                "all_match": True,
                "expected_captured_total_cents": expected,
                "paypal_captured_total_cents": paypal_total,
                "item_statuses": record["item_statuses"],
            }
            report.write("passed")
            print(f"\nIT-8 live verification passed; report: {report.out}")
    finally:
        await engine.dispose()


async def main(args: argparse.Namespace) -> int:
    load_env()
    out = (
        Path(args.out)
        if args.out
        else Path(".tmp/it8_live_verify.json" if args.live_verify else ".tmp/it8_report.json")
    )
    report = Report("live_verify" if args.live_verify else "fake", out)
    try:
        if args.live_verify:
            await run_live_verify(report)
        else:
            await run_fake(args, report)
    except StepFailure as exc:
        report.write("failed")
        print(f"\nIT-8 FAILED at step '{exc.step}': {exc.message}")
        print(f"report: {report.out}")
        return 1
    except SystemExit:
        raise
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-verify",
        action="store_true",
        help="call the verification service for the IT-7 lot against PayPal Sandbox",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="report path (default .tmp/it8_report.json, or .tmp/it8_live_verify.json)",
    )
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(main(arguments)))
