"""IT-7 live end-to-end harness (docs/testing-strategy.md IT-7, T07X01).

Runs the Phase 7 acceptance flow against a **running local API** on loopback:

    python tools/it7_live.py --dry-run          # preflight, fixtures, pools, open, plan
    python tools/it7_live.py --live             # the whole IT-7 run, owner approvals

What ``--live`` does: fixtures made the way ``tools/demo_seed.py`` makes them
(``IdentityService.register``, a role flip, a merchant row with the three R2
attestations -- never the PayPal-first HTTP signup); two pools through
``POST /api/v1/admin/pools``; buyers joining through the browser routes with
signed receipts (four, because IT-7's offer expiry plus refill needs one
waitlisted entry behind the three seats); one merchant through the console
(quote, bid, confirm) and one through a merchant API key; both lots awarded from
real confirmed bids; the agent API and the FairPool MCP server joining, listing
and withdrawing; the merchant search and its ``LOW_SIMILARITY`` advisory; the
ops reads; and -- with Sandbox credentials -- redirect approvals, lot 1 funded by
a completed capture, and lot 2 failing at its fund deadline with one
authorization voided and one capture refunded, net zero. The script prints a
short loopback path per buyer (``http://127.0.0.1:<port>/go/<8>``); the full
approval URL never leaves memory.

The second pool (one lot of a different product, never bid on) exists only so
the advisory retrieval check has another product that can rank first: with one
product in the catalog the similarity check is skipped by its own rule, and
``LOW_SIMILARITY`` could never be proven on a live database.

The harness is its own job worker: it claims the app's registered handlers and
runs them in order. That is what lets it keep one ``order.capture`` queued past
the fund deadline (the genuine LS-09 path, no mock and no database edit) instead
of racing a background worker. ``--worker`` only waits for a worker that is
already running and is accepted for ``--dry-run``; a live run needs the
harness's own scheduling, because a worker would capture both lot-2 seats and
fund the lot.

Preflight refuses to run unless ``DATABASE_URL``, ``APP_ENV``,
``PAYMENT_ROUTER``, ``PAYMENT_MODE`` and ``PUBLIC_BASE_URL`` are set, the
database host is loopback, and the router is not ``fake`` (unless
``--dry-run``). ``--live`` additionally requires ``single_seller`` +
``authorize_capture`` and ``IT6_BUYER_PASSWORD`` in ``.env`` (used for the fresh
local fixture accounts, never printed). No token, password, client secret,
approval URL or delivery address reaches stdout or the JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

#: The fixture delivery address. It is sent to PayPal only at payload level 3 and
#: is never written to the report.
SHIPPING: dict[str, str] = {
    "name": "IT7 Buyer",
    "line1": "12 Example Street",
    "city": "Albany",
    "region": "NY",
    "postal_code": "12207",
    "country_code": "US",
}

MAIN_TEMPLATE: dict[str, Any] = {
    "product_key": "monitor-27-4k",
    "variant": "black",
    "title": "Desk 27-inch 4K monitor",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "delivery_sla_days": 7,
    "fund_by": "2026-12-10",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
}

#: A second, different product kept in BIDDING only so the advisory similarity
#: check has something other than the bid's own product to rank first (INT-1).
COMPANION_TEMPLATE: dict[str, Any] = {
    "product_key": "headphones-over-ear",
    "variant": "black",
    "title": "Wireless over-ear headphones",
    "condition": "NEW",
    "quantity": 1,
    "currency": "USD",
    "bundle_contents": ["headphones", "carrying case", "usb-c cable"],
    "delivery_sla_days": 7,
    "fund_by": "2026-12-10",
    "min_return_days": 14,
    "zones": [{"zone_id": "US-EAST", "label": "US East", "regions": ["NY", "NJ", "PA"]}],
}

MAIN_LOT_PLAN = [
    {"zone_id": "US-EAST", "lots": [{"seats": 1, "min_seats": 1}, {"seats": 2, "min_seats": 2}]}
]
COMPANION_LOT_PLAN = [{"zone_id": "US-EAST", "lots": [{"seats": 1, "min_seats": 1}]}]

MONITOR_QUOTE = (
    "27 inch 4K monitor, black, new, bundle monitor stand and power cable, "
    "delivered in 7 days, USD 470.00 per unit, 14 day returns."
)
OFF_PRODUCT_TEXT = (
    "Offering noise-cancelling headphones, wireless over-ear, 40-hour battery, "
    "USB-C charging, carrying case included."
)


class StepFailure(RuntimeError):
    """A named step failed; the top level prints its name and exits non-zero."""

    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step}: {message}")
        self.step = step
        self.message = message


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def load_env() -> None:
    """The repository ``.env`` fills only variables the shell did not set."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def must(
    response: httpx.Response,
    path: str | None = None,
    expect: tuple[int, ...] = (200, 201, 202, 204),
) -> httpx.Response:
    """An unexpected status is a failed assertion naming the route, never a retry."""
    if response.status_code not in expect:
        route = path or response.request.url.path
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"{route} -> {response.status_code} {detail}")
    return response


def login(api: str, email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=api, headers={"Origin": api}, timeout=60)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if response.status_code != 200:
        raise RuntimeError(f"login failed: {response.status_code}")
    client.headers["X-CSRF-Token"] = str(response.json()["csrf_token"])
    return client


class Redirector:
    """Loopback approval redirector: short paths in, the real URL only in memory."""

    def __init__(self) -> None:
        self._targets: dict[str, str] = {}
        self._server: ThreadingHTTPServer | None = None
        self.port = 0

    def start(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - http.server API
                key = self.path.strip("/")
                target = outer._targets.get(key)
                if target is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()

            def log_message(self, *args: object) -> None:
                del args  # a token-bearing path never enters a log

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self._server.server_address[1])
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def short_path(self, key: str, approve_url: str) -> str:
        short = key.replace("-", "")[:8]
        self._targets[f"go/{short}"] = approve_url
        return f"http://127.0.0.1:{self.port}/go/{short}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()


class Report:
    """The JSON report: named steps, provider references, no secrets."""

    def __init__(self, mode: str, out: Path) -> None:
        self.out = out
        self.data: dict[str, Any] = {
            "test": "IT-7",
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


class Drainer:
    """Runs the app's own job handlers; the harness's worker for this run."""

    def __init__(self, factory: Any, handlers: dict[str, Any]) -> None:
        from fairpool.infra.jobs import PostgresJobQueue

        self.factory = factory
        self.handlers = handlers
        self.queue = PostgresJobQueue()
        self.worker_id = f"it7-{uuid.uuid4().hex[:8]}"
        self.ran = 0

    async def _execute(self, job: Any) -> None:
        from sqlalchemy import text

        async with self.factory.begin() as session:
            owned = await session.scalar(
                text(
                    "SELECT id FROM jobs WHERE id=:id AND status='RUNNING' "
                    "AND locked_by=:worker AND attempts=:attempt "
                    "AND locked_until > now() FOR UPDATE"
                ),
                {"id": job.id, "worker": self.worker_id, "attempt": job.attempts},
            )
            if owned is None:
                return
            await self.handlers[job.kind](session, job.payload)
            await self.queue.complete(
                session, job.id, worker_id=self.worker_id, attempt=job.attempts
            )

    async def run_due(
        self,
        *,
        kinds: tuple[str, ...] | None = None,
        exclude: tuple[str, ...] = (),
        limit: int = 200,
    ) -> int:
        allowed = tuple(k for k in self.handlers if k not in exclude)
        if kinds is not None:
            allowed = tuple(k for k in kinds if k in self.handlers)
        if not allowed:
            return 0
        count = 0
        while count < limit:
            async with self.factory.begin() as session:
                jobs = await self.queue.claim(
                    session, worker_id=self.worker_id, limit=1, kinds=allowed
                )
            if not jobs:
                break
            await self._execute(jobs[0])
            count += 1
        self.ran += count
        return count

    async def run_capture(self, buyer_order_id: UUID) -> None:
        """Run exactly one queued ``order.capture`` job, leaving the other seats queued."""
        from fairpool.infra.jobs import ClaimedJob
        from sqlalchemy import text

        async with self.factory.begin() as session:
            row = (
                await session.execute(
                    text(
                        "WITH picked AS ("
                        " SELECT id FROM jobs WHERE status='PENDING' AND run_at <= now() "
                        " AND kind='order.capture' "
                        " AND payload->>'buyer_order_id' = :bo "
                        " ORDER BY run_at, created_at LIMIT 1 FOR UPDATE SKIP LOCKED) "
                        "UPDATE jobs j SET status='RUNNING', locked_by=:worker, "
                        " locked_until=now() + interval '300 seconds', attempts=attempts+1 "
                        "FROM picked WHERE j.id = picked.id "
                        "RETURNING j.id, j.kind, j.payload, j.attempts"
                    ),
                    {"bo": str(buyer_order_id), "worker": self.worker_id},
                )
            ).first()
        if row is None:
            raise RuntimeError("no queued order.capture for the chosen lot-2 seat")
        await self._execute(
            ClaimedJob(id=row[0], kind=row[1], payload=row[2], attempts=row[3], max_attempts=0)
        )


async def drain_until(
    drainer: Drainer | None,
    predicate: Callable[[], Awaitable[bool]],
    *,
    deadline: float,
    exclude: tuple[str, ...] = (),
    what: str,
    interval: float = 2.0,
) -> None:
    """Drive due jobs until ``predicate`` holds, or fail naming the waiting condition."""
    while True:
        if drainer is not None:
            await drainer.run_due(exclude=exclude)
        if await predicate():
            return
        if time.monotonic() > deadline:
            raise RuntimeError(f"timed out waiting for {what}")
        await asyncio.sleep(interval)


def preflight(args: argparse.Namespace) -> dict[str, str]:
    """Every required switch, the loopback database guard and the router guard."""
    missing = [
        key
        for key in ("DATABASE_URL", "APP_ENV", "PAYMENT_ROUTER", "PAYMENT_MODE", "PUBLIC_BASE_URL")
        if not os.environ.get(key)
    ]
    if not os.environ.get("IT6_BUYER_PASSWORD"):
        missing.append("IT6_BUYER_PASSWORD")
    if missing:
        raise SystemExit(
            "IT-7 preflight: missing environment: "
            + ", ".join(missing)
            + ". Set them (PAYMENT_ROUTER=single_seller, PAYMENT_MODE=authorize_capture, "
            "IT6_BUYER_PASSWORD in .env) and retry."
        )

    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    host = (url.host or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1", ""}:
        raise SystemExit(
            f"IT-7 preflight: DATABASE_URL host {host!r} is not loopback; "
            "this harness never writes the hosted demo database."
        )
    router = os.environ["PAYMENT_ROUTER"]
    mode = os.environ["PAYMENT_MODE"]
    if router == "fake" and not args.dry_run:
        raise SystemExit("IT-7 preflight: PAYMENT_ROUTER=fake is only accepted with --dry-run.")
    if args.live:
        if router != "single_seller":
            raise SystemExit(
                f"IT-7 preflight: --live needs PAYMENT_ROUTER=single_seller, got {router!r}."
            )
        if mode != "authorize_capture":
            raise SystemExit(
                f"IT-7 preflight: --live needs PAYMENT_MODE=authorize_capture, got {mode!r}."
            )
        if args.worker:
            raise SystemExit(
                "IT-7 preflight: --live cannot use --worker. The failure leg needs one lot-2 "
                "capture held past the fund deadline; a running worker would capture both "
                "seats and fund the lot."
            )
    if os.environ["APP_ENV"] not in {"local", "test"}:
        raise SystemExit("IT-7 preflight: APP_ENV must be local or test.")
    if os.environ.get("SEARCH_BACKEND", "postgres") != "postgres":
        # The harness runs search.index itself, and the advisory check is measured on
        # the Postgres trigram path. Elastic would reach the network and disagree with
        # the API process unless both share a cluster; neither belongs in a local run.
        raise SystemExit(
            "IT-7 preflight: SEARCH_BACKEND must be postgres for this local harness "
            f"(got {os.environ.get('SEARCH_BACKEND')!r}). Start the API with the same value."
        )

    try:
        with httpx.Client(base_url=args.api_base, timeout=15) as probe:
            health = probe.get("/health")
            ready = probe.get("/ready")
    except httpx.HTTPError as exc:
        raise SystemExit(
            f"IT-7 preflight: no API at {args.api_base} ({type(exc).__name__}). "
            "Start it with `make api` and the same PAYMENT_ROUTER/PAYMENT_MODE."
        ) from exc
    if health.status_code != 200:
        raise SystemExit(f"IT-7 preflight: /health answered {health.status_code}.")
    if ready.status_code != 200:
        raise SystemExit(f"IT-7 preflight: /ready answered {ready.status_code}: {ready.text[:200]}")
    return {
        "api": args.api_base,
        "router": router,
        "mode": mode,
        "app_env": os.environ["APP_ENV"],
    }


def timeline(now: datetime, *, open_s: int, close_s: int, **overrides: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        "open_at": (now + timedelta(seconds=open_s)).isoformat(),
        "close_at": (now + timedelta(seconds=close_s)).isoformat(),
        "beacon_delay_s": 5,
        # Long enough for a live quote call plus the console and API-key bids.
        "bid_window_s": 240,
        # A refused/slow approval expires an offer, which is the refill trigger;
        # the fund deadline then leaves ~5 minutes for the refilled seat.
        "offer_window_s": 360,
        "fund_deadline_s": 720,
        "capture_grace_s": 120,
        "pending_wait_s": 60,
        "max_refill_waves": 1,
        "authorization_age_guard_s": 216000,
    }
    base.update(overrides)
    return base


def create_pool(
    admin: httpx.Client,
    *,
    title: str,
    template: dict[str, Any],
    lot_plan: list[dict[str, Any]],
    pool_timeline: dict[str, Any],
) -> str:
    body = {
        "title": title,
        "template": template,
        "lot_plan": lot_plan,
        "timeline": pool_timeline,
        "require_paypal_link": False,
        "rule_version": "allocation_v1",
    }
    created = must(admin.post("/api/v1/admin/pools", json=body)).json()
    published = must(admin.post(f"/api/v1/admin/pools/{created['pool_id']}/publish", json={}))
    if published.json()["status"] != "PUBLISHED":
        raise RuntimeError(f"publish answered {published.json()['status']}")
    return str(created["pool_id"])


async def make_fixtures(
    factory: Any, settings: Any, password: str, stamp: str
) -> dict[str, dict[str, str]]:
    """The demo_seed fixture pattern: in-process register, role flip, merchant row."""
    from fairpool.domain.errors import ApplicationError
    from fairpool.infra.clock import DbClock
    from fairpool.modules.identity.service import IdentityService
    from sqlalchemy import text

    identity = IdentityService(settings.secret_key.get_secret_value(), DbClock())
    attestations = json.dumps(
        {
            key: {"at": "2026-11-01T00:00:00Z", "accepted": True}
            for key in ("inventory_reserved", "map_compliance", "delivery_terms_accurate")
        }
    )
    roles = {
        "admin": "admin",
        "merchant1": "merchant",
        "merchant2": "merchant",
        "buyer1": "buyer",
        "buyer2": "buyer",
        "buyer3": "buyer",
        "buyer4": "buyer",
        "agent": "buyer",
        "mcp": "buyer",
    }
    accounts: dict[str, dict[str, str]] = {}
    async with factory() as session:
        for key, role in roles.items():
            email = f"it7.{key}.{stamp}@example.test"
            try:
                created = await identity.register(
                    session, email=email, password=password, display_name=f"IT7 {key}"
                )
                user_id = UUID(str(created["user_id"]))
            except ApplicationError:
                found = await session.scalar(
                    text("SELECT id FROM users WHERE email = :email"), {"email": email}
                )
                if found is None:
                    raise
                user_id = UUID(str(found))
            if role != "buyer":
                await session.execute(
                    text("UPDATE users SET role = :role WHERE id = :id"),
                    {"role": role, "id": user_id},
                )
            if role == "merchant":
                await session.execute(
                    text(
                        "INSERT INTO merchants (id, user_id, display_name, onboarding_status, "
                        "attestations) VALUES (:id, :user, :name, 'DEMO', CAST(:at AS jsonb))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "user": user_id,
                        "name": f"IT7 Seller {key} {stamp[:4]}",
                        "at": attestations,
                    },
                )
            accounts[key] = {"email": email, "user_id": str(user_id)}
        await session.commit()
    return accounts


async def read_lots(factory: Any, pool_id: str) -> list[dict[str, Any]]:
    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, lot_order, seats, min_seats, status::text, refill_waves, "
                    "fund_deadline_at "
                    "FROM lots WHERE pool_id = :pool ORDER BY lot_order"
                ),
                {"pool": UUID(pool_id)},
            )
        ).all()
    return [
        {
            "lot_id": str(row[0]),
            "lot_order": int(row[1]),
            "seats": int(row[2]),
            "min_seats": int(row[3]),
            "status": str(row[4]),
            "refill_waves": int(row[5]),
            "fund_deadline_at": None if row[6] is None else str(row[6].isoformat()),
        }
        for row in rows
    ]


async def read_lot_status(factory: Any, lot_id: str) -> str:
    from sqlalchemy import text

    async with factory() as session:
        value = await session.scalar(
            text("SELECT status::text FROM lots WHERE id = :id"), {"id": UUID(lot_id)}
        )
    return str(value)


async def read_orders(factory: Any, pool_id: str) -> list[dict[str, Any]]:
    """Buyer orders and their provider references for one pool (report input only)."""
    from sqlalchemy import text

    pool = UUID(pool_id)
    async with factory() as session:
        orders = (
            await session.execute(
                text(
                    "SELECT bo.id, bo.lot_id, bo.status::text, bo.total_cents, pe.user_id, "
                    "bo.offer_expires_at "
                    "FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
                    "WHERE bo.lot_id IN (SELECT id FROM lots WHERE pool_id = :pool) "
                    "ORDER BY bo.created_at, bo.id"
                ),
                {"pool": pool},
            )
        ).all()
        rows: list[dict[str, Any]] = [
            {
                "buyer_order_id": str(row[0]),
                "lot_id": str(row[1]),
                "status": str(row[2]),
                "total_cents": int(row[3]),
                "user_id": str(row[4]),
                "offer_expires_at": None if row[5] is None else str(row[5].isoformat()),
            }
            for row in orders
        ]
        for table, key in (
            ("paypal_orders", "paypal_order_id"),
            ("paypal_authorizations", "paypal_auth_id"),
            ("paypal_captures", "paypal_capture_id"),
            ("paypal_refunds", "paypal_refund_id"),
        ):
            mapping = {
                str(row[0]): str(row[1])
                for row in (
                    await session.execute(
                        text(
                            f"SELECT buyer_order_id, {key} FROM {table} WHERE buyer_order_id IN "
                            "(SELECT bo.id FROM buyer_orders bo JOIN lots l ON l.id = bo.lot_id "
                            "WHERE l.pool_id = :pool)"
                        ),
                        {"pool": pool},
                    )
                ).all()
            }
            for order in rows:
                order[key] = mapping.get(order["buyer_order_id"])
    return rows


async def read_allocations(factory: Any, pool_id: str) -> dict[str, str]:
    """user id -> allocation status for one pool (verification read)."""
    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT pe.user_id, a.status::text FROM allocations a "
                    "JOIN pool_entries pe ON pe.id = a.entry_id WHERE a.pool_id = :pool"
                ),
                {"pool": UUID(pool_id)},
            )
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


async def read_ledger(factory: Any, lot_id: str) -> dict[str, Any]:
    from sqlalchemy import text

    async with factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT kind::text, amount_cents FROM ledger_entries "
                    "WHERE lot_id = :lot ORDER BY created_at, id"
                ),
                {"lot": UUID(lot_id)},
            )
        ).all()
    net = sum(
        int(amount) if kind == "CAPTURE_COMPLETED" else -int(amount)
        for kind, amount in rows
        if kind in {"CAPTURE_COMPLETED", "REFUND_COMPLETED"}
    )
    return {
        "entries": [{"kind": str(kind), "amount_cents": int(amount)} for kind, amount in rows],
        "net_paid_cents": net,
    }


def run_plan() -> list[str]:
    return [
        "4. Join buyers through POST /api/v1/intake/manual + "
        "POST /api/v1/pools/{id}/entries (signed receipts). Four browser buyers are "
        "needed: three seats plus one waitlist candidate for the refill leg.",
        "5. Merchant 1 through the console: POST /api/v1/merchant/lots/{id}/quote, "
        "PUT .../bid, POST /api/v1/merchant/bids/{id}/confirm. Merchant 2 through an "
        "API key: PUT /merchant-api/v1/lots/{id}/bid with Idempotency-Key and "
        "confirmed: true.",
        "6. Wait for bid close, drain lot.bid_close/lot.award/lot.open_checkout. "
        "Owner approves the printed loopback paths. Lot 1 funds on one completed "
        "capture; one lot-2 offer expires and lot.refill offers the seat to the "
        "waitlist; at the fund deadline lot 2 voids the remaining authorization and "
        "refunds the completed capture, net zero.",
        "7. Agent API: POST /api/v1/me/delegations, POST /agent/v1/entries, "
        "GET /agent/v1/entries, POST /agent/v1/entries/withdraw.",
        "8. MCP: initialize, tools/list, tools/call list_pools, enter_pool, "
        "list_entries, withdraw_entry at /mcp.",
        "9. Merchant search: GET /api/v1/merchant/lots?q=... and the bid view carry "
        "the LOW_SIMILARITY WARNING from a confirmed off-product bid against the "
        "companion pool's other product.",
        "10. Ops reads: GET /api/v1/admin/lots/{id}, /admin/alerts, "
        "/admin/webhooks/dead-letter, /admin/audit/export.",
    ]


async def main(args: argparse.Namespace) -> int:
    load_env()
    pre = preflight(args)
    report = Report("live" if args.live else "dry_run", Path(args.out))
    report.data["environment"] = {
        **pre,
        "database_host": "loopback",
        "public_base_url_set": bool(os.environ.get("PUBLIC_BASE_URL")),
    }
    print(
        f"IT-7 {report.data['mode']}: api={pre['api']} router={pre['router']} "
        f"mode={pre['mode']} env={pre['app_env']} db=loopback"
    )

    try:
        await _run(args, pre, report)
    except StepFailure as exc:
        report.write("failed")
        print(f"\nIT-7 FAILED at step '{exc.step}': {exc.message}")
        print(f"report: {report.out}")
        return 1
    except SystemExit:
        raise
    return 0


async def _run(args: argparse.Namespace, pre: dict[str, str], report: Report) -> None:
    from fairpool.config import Settings
    from fairpool.db.session import create_engine
    from fairpool.wiring import checkout_services, worker_handlers
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    api = pre["api"]
    password = os.environ["IT6_BUYER_PASSWORD"]
    settings = Settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    surface = checkout_services(settings)
    handlers = worker_handlers(settings, surface)
    drainer = None if args.worker else Drainer(factory, handlers)
    redirector = Redirector() if args.live else None
    sessions: dict[str, httpx.Client] = {}
    try:
        async with report.step("fixtures") as record:
            stamp = uuid.uuid4().hex[:8]
            accounts = await make_fixtures(factory, settings, password, stamp)
            sessions = {}
            for key in accounts:
                sessions[key] = login(api, accounts[key]["email"], password)
            record["accounts"] = sorted(accounts)
            record["note"] = "fixtures made in-process like tools/demo_seed.py"

        admin = sessions["admin"]
        merchant1 = sessions["merchant1"]
        merchant2 = sessions["merchant2"]
        now = datetime.now(UTC)
        if args.live:
            pool_timeline = timeline(now, open_s=25, close_s=150)
        else:
            pool_timeline = timeline(
                now,
                open_s=10,
                close_s=35,
                bid_window_s=30,
                offer_window_s=60,
                fund_deadline_s=120,
            )

        async with report.step("pools_created") as record:
            main_pool = create_pool(
                admin,
                title=f"IT7 monitors {stamp}",
                template=MAIN_TEMPLATE,
                lot_plan=MAIN_LOT_PLAN,
                pool_timeline=pool_timeline,
            )
            companion_pool = create_pool(
                admin,
                title=f"IT7 headphones {stamp}",
                template=COMPANION_TEMPLATE,
                lot_plan=COMPANION_LOT_PLAN,
                pool_timeline=pool_timeline,
            )
            record["main_pool_id"] = main_pool
            record["companion_pool_id"] = companion_pool
            report.data["main_pool_id"] = main_pool
            report.data["companion_pool_id"] = companion_pool
            if redirector is not None:
                redirector.start()

        async def open_status() -> bool:
            body = must(admin.get(f"/api/v1/pools/{main_pool}")).json()
            other = must(admin.get(f"/api/v1/pools/{companion_pool}")).json()
            return body.get("status") == "OPEN" and other.get("status") == "OPEN"

        async with report.step("pool_open") as record:
            deadline = time.monotonic() + 120
            await drain_until(drainer, open_status, deadline=deadline, what="both pools OPEN")
            record["status"] = "OPEN"

        if args.dry_run:
            async with report.step("closed_seeded_allocated") as record:
                # Step 3's whole lifecycle on an empty pool: close, seed and allocate
                # run as jobs. With no entries every lot is undersized and cancelled,
                # which is the contracted LS-12 outcome; no buyer or PayPal leg exists.
                async def allocated() -> bool:
                    current = must(admin.get(f"/api/v1/pools/{main_pool}")).json()
                    other = must(admin.get(f"/api/v1/pools/{companion_pool}")).json()
                    return current.get("status") in {"ALLOCATED", "COMPLETED"} and other.get(
                        "status"
                    ) in {"ALLOCATED", "COMPLETED"}

                close_at = datetime.fromisoformat(str(pool_timeline["close_at"]))
                deadline = time.monotonic() + max(
                    45.0, (close_at - datetime.now(UTC)).total_seconds() + 90
                )
                await drain_until(
                    drainer,
                    allocated,
                    deadline=deadline,
                    what="pool.close, pool.seed and pool.allocate",
                    interval=1.0,
                )
                record["main_status"] = must(admin.get(f"/api/v1/pools/{main_pool}")).json()[
                    "status"
                ]
                record["companion_status"] = must(
                    admin.get(f"/api/v1/pools/{companion_pool}")
                ).json()["status"]
            async with report.step("plan") as record:
                record["plan"] = run_plan()
                record["timeline"] = pool_timeline
            for line in run_plan():
                print(line)
            report.write("dry_run")
            print(f"\nIT-7 dry run passed; report: {report.out}")
            return

        buyer_keys = ("buyer1", "buyer2", "buyer3", "buyer4")

        async with report.step("buyers_joined") as record:
            entries: dict[str, dict[str, Any]] = {}
            for key in buyer_keys:
                client = sessions[key]
                confirmed = must(
                    client.post(
                        "/api/v1/intake/manual",
                        json={
                            "pool_id": main_pool,
                            "delivery": {"region": "NY"},
                            "required_by": "2026-12-20",
                            "max_total_cents": 60000,
                            "firm": [],
                            "preferences": [],
                        },
                    )
                ).json()
                joined = must(
                    client.post(
                        f"/api/v1/pools/{main_pool}/entries",
                        json={"confirmed_request_id": confirmed["confirmed_request_id"]},
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    )
                ).json()
                receipt = joined.get("receipt") or {}
                if not receipt.get("signature"):
                    raise RuntimeError(f"{key} join returned no signed receipt")
                entries[key] = {
                    "entry_id": str(joined["entry_id"]),
                    "receipt_commitment": str(receipt["payload"]["commitment"]),
                }
                print(f"  joined {key}: entry {str(joined['entry_id'])[:8]} receipt signed")
            # The fourth buyer also enters the companion pool so its lot can form.
            confirmed = must(
                sessions["buyer1"].post(
                    "/api/v1/intake/manual",
                    json={
                        "pool_id": companion_pool,
                        "delivery": {"region": "NY"},
                        "required_by": "2026-12-20",
                        "max_total_cents": 60000,
                        "firm": [],
                        "preferences": [],
                    },
                )
            ).json()
            must(
                sessions["buyer1"].post(
                    f"/api/v1/pools/{companion_pool}/entries",
                    json={"confirmed_request_id": confirmed["confirmed_request_id"]},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            )
            record["entries"] = {key: value["entry_id"] for key, value in entries.items()}
            report.data["entries"] = entries

        async with report.step("agent_lane") as record:
            delegation = must(
                sessions["agent"].post(
                    "/api/v1/me/delegations",
                    json={
                        "scope": {"pool_ids": [main_pool]},
                        "max_cap_cents": 60000,
                        "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                    },
                ),
                expect=(201,),
            ).json()
            token = str(delegation["token"])
            agent = {"Authorization": f"Bearer {token}"}
            joined = must(
                sessions["agent"].post(
                    "/agent/v1/entries",
                    json={
                        "pool_id": main_pool,
                        "request": {
                            "delivery": {"region": "NY"},
                            "required_by": "2026-12-20",
                            "max_total_cents": 60000,
                            "firm": [],
                            "preferences": [],
                        },
                    },
                    headers={**agent, "Idempotency-Key": str(uuid.uuid4())},
                ),
                expect=(200, 201),
            ).json()
            entry_id = str(joined["entry_id"])
            listed = must(sessions["agent"].get("/agent/v1/entries", headers=agent)).json()
            if entry_id not in {str(item["entry_id"]) for item in listed["items"]}:
                raise RuntimeError("GET /agent/v1/entries did not list the new entry")
            withdrawn = must(
                sessions["agent"].post(
                    "/agent/v1/entries/withdraw",
                    json={"entry_id": entry_id},
                    headers=agent,
                )
            ).json()
            if str(withdrawn["entry_status"]) != "WITHDRAWN":
                raise RuntimeError(f"withdraw answered {withdrawn['entry_status']}")
            record["entry_id"] = entry_id
            record["checkout_hint"] = joined.get("checkout_hint")
            del token

        async with report.step("mcp_lane") as record:
            delegation = must(
                sessions["mcp"].post(
                    "/api/v1/me/delegations",
                    json={
                        "scope": {"pool_ids": [main_pool]},
                        "max_cap_cents": 60000,
                        "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                    },
                ),
                expect=(201,),
            ).json()
            token = str(delegation["token"])
            headers = {"Authorization": f"Bearer {token}"}
            call = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            initialized = must(sessions["mcp"].post("/mcp", json=call, headers=headers)).json()
            if "result" not in initialized:
                raise RuntimeError("MCP initialize returned no result")
            tools = must(
                sessions["mcp"].post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    headers=headers,
                )
            ).json()["result"]["tools"]
            names = sorted(str(tool["name"]) for tool in tools)
            if names != ["enter_pool", "list_entries", "list_pools", "withdraw_entry"]:
                raise RuntimeError(f"tools/list answered {names}")

            def tool_call(name: str, arguments: dict[str, Any], rid: int) -> dict[str, Any]:
                result = must(
                    sessions["mcp"].post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": rid,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": arguments},
                        },
                        headers=headers,
                    )
                ).json()["result"]
                if result.get("isError"):
                    raise RuntimeError(f"MCP tool {name} failed")
                return json.loads(result["content"][0]["text"])

            pools = tool_call("list_pools", {"limit": 20}, 3)
            if main_pool not in {str(item["pool_id"]) for item in pools}:
                raise RuntimeError("MCP list_pools did not list the main pool")
            entered = tool_call(
                "enter_pool",
                {
                    "pool_id": main_pool,
                    "delivery_region": "NY",
                    "max_total_usd": "600.00",
                    "required_by": "2026-12-20",
                    "idempotency_key": str(uuid.uuid4()),
                },
                4,
            )
            entry_id = str(entered["entry_id"])
            listed = tool_call("list_entries", {"pool_id": main_pool}, 5)
            items = listed.get("items", listed if isinstance(listed, list) else [])
            if entry_id not in {str(item["entry_id"]) for item in items}:
                raise RuntimeError("MCP list_entries did not list the new entry")
            withdrawn = tool_call("withdraw_entry", {"entry_id": entry_id}, 6)
            if str(withdrawn["entry_status"]) != "WITHDRAWN":
                raise RuntimeError(f"MCP withdraw_entry answered {withdrawn['entry_status']}")
            record["entry_id"] = entry_id
            record["tools"] = names
            del token

        async def lots_bidding() -> bool:
            lots = await read_lots(factory, main_pool)
            other = await read_lots(factory, companion_pool)
            return (
                len(lots) == 2
                and all(lot["status"] == "BIDDING" for lot in lots)
                and len(other) == 1
                and other[0]["status"] == "BIDDING"
            )

        async with report.step("closed_seeded_allocated") as record:
            close_at = datetime.fromisoformat(str(pool_timeline["close_at"]))
            deadline = time.monotonic() + max(
                30.0, (close_at - datetime.now(UTC)).total_seconds() + 90
            )
            await drain_until(
                drainer,
                lots_bidding,
                deadline=deadline,
                what="pool.close, pool.seed, pool.allocate and lot.bid_open",
                interval=1.0,
            )
            lots = await read_lots(factory, main_pool)
            allocations = await read_allocations(factory, main_pool)
            record["lots"] = lots
            record["allocations"] = allocations
            report.data["lots"] = lots
            report.data["allocations"] = allocations

        lot1 = next(lot for lot in lots if lot["lot_order"] == 1)
        lot2 = next(lot for lot in lots if lot["lot_order"] == 2)

        def structured(price_cents: int) -> dict[str, Any]:
            return {
                "v": 1,
                "product_key": "monitor-27-4k",
                "condition": "NEW",
                "bundle_contents": ["monitor", "stand", "power cable"],
                "capacity": 2,
                "target_quantity": 2,
                "moq": 1,
                "tiers": [{"min_qty": 1, "item_price_cents": price_cents}],
                "shipping_cents_by_zone": {},
                "tax": {"mode": "INCLUDED"},
                "delivery": {"sla_days": 7},
                "returns": {"days": 30},
                "valid_until": "2026-12-31T00:00:00Z",
                "total_capacity": 2,
                "evidence": {"note": "units reserved in the warehouse", "url": None},
            }

        async with report.step("merchants_bid") as record:
            quote = merchant1.post(
                f"/api/v1/merchant/lots/{lot1['lot_id']}/quote",
                json={"quote_text": MONITOR_QUOTE},
            )
            record["quote_status"] = quote.status_code
            if quote.status_code == 200:
                record["quote_bid_id"] = quote.json()["bid_id"]
            elif quote.status_code != 403:
                must(quote, "quote")
            else:
                record["quote_note"] = "FEATURE_DISABLED; structured fallback (FR-IN-08)"

            saved = must(
                merchant1.put(
                    f"/api/v1/merchant/lots/{lot1['lot_id']}/bid",
                    json={"structured": structured(47_000)},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            must(
                merchant1.post(
                    f"/api/v1/merchant/bids/{saved['bid_id']}/confirm",
                    json={"revision": saved["revision"]},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            )
            record["merchant1_lot1_bid"] = saved["bid_id"]

            key = must(
                merchant2.post(
                    "/api/v1/merchant/api-keys",
                    json={"name": "it7-bot", "scopes": ["lots:read", "bids:write", "bids:read"]},
                ),
                expect=(201,),
            ).json()
            key_headers = {"Authorization": f"Bearer {key['key']}"}
            for lot in (lot1, lot2):
                must(
                    merchant2.put(
                        f"/merchant-api/v1/lots/{lot['lot_id']}/bid",
                        json={"structured": structured(49_000), "notes": None, "confirmed": True},
                        headers={**key_headers, "Idempotency-Key": str(uuid.uuid4())},
                    )
                )
            record["merchant2_api_key_bids"] = True

            # The deliberate off-product bid: monitor lot, headphone words, confirmed
            # through the console. The companion lot is the only other BIDDING product,
            # so the retrieval check must warn (INT-1) without changing the bid status.
            off = must(
                merchant1.put(
                    f"/api/v1/merchant/lots/{lot2['lot_id']}/bid",
                    json={"structured": structured(47_000), "notes": OFF_PRODUCT_TEXT},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            must(
                merchant1.post(
                    f"/api/v1/merchant/bids/{off['bid_id']}/confirm",
                    json={"revision": off["revision"]},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            )
            record["off_product_bid"] = off["bid_id"]
            report.data["off_product_bid_id"] = off["bid_id"]
            del key_headers

        async with report.step("merchant_search_flag") as record:
            found = must(
                merchant1.get("/api/v1/merchant/lots", params={"q": "wireless over-ear headphones"})
            ).json()
            if companion_pool not in {str(item["pool_id"]) for item in found}:
                raise RuntimeError("merchant lot search did not return the companion lot")
            view = must(
                merchant1.get(f"/api/v1/merchant/bids/{report.data['off_product_bid_id']}")
            ).json()
            flags = [
                {"code": str(flag["code"]), "severity": str(flag["severity"])}
                for flag in view.get("flags", [])
            ]
            if not any(
                flag["code"] == "LOW_SIMILARITY" and flag["severity"] == "WARNING" for flag in flags
            ):
                raise RuntimeError(f"bid view carried no LOW_SIMILARITY WARNING: {flags}")
            record["search_hits"] = len(found)
            record["bid_flags"] = flags
            record["bid_status"] = view["status"]
            report.data["low_similarity_flags"] = flags

        async def lots_awarded() -> bool:
            current = {
                lot["lot_order"]: lot["status"] for lot in await read_lots(factory, main_pool)
            }
            return current.get(1) == "CHECKOUT_OPEN" and current.get(2) == "CHECKOUT_OPEN"

        async with report.step("awarded_checkout_open") as record:
            bid_close = datetime.fromisoformat(str(pool_timeline["close_at"])) + timedelta(
                seconds=int(pool_timeline["bid_window_s"])
            )
            deadline = time.monotonic() + max(
                30.0, (bid_close - datetime.now(UTC)).total_seconds() + 120
            )
            await drain_until(
                drainer,
                lots_awarded,
                deadline=deadline,
                what="lot.bid_close, lot.award and lot.open_checkout",
                interval=1.0,
            )
            audit = must(admin.get(f"/api/v1/public/pools/{main_pool}/audit")).json()
            awards = {
                int(lot["lot_order"]): {
                    "merchant_display_name": (lot.get("award") or {}).get("merchant_display_name"),
                    "item_cents": (lot.get("award") or {}).get("item_cents"),
                }
                for lot in audit.get("lots", [])
            }
            if "merchant1" not in str(awards.get(1, {}).get("merchant_display_name")):
                raise RuntimeError(f"lot 1 was not awarded to the console merchant: {awards}")
            if "merchant2" not in str(awards.get(2, {}).get("merchant_display_name")):
                raise RuntimeError(f"lot 2 was not awarded to the API-key merchant: {awards}")
            record["awards"] = awards
            record["payment_mode_stamped"] = None
            view1 = must(admin.get(f"/api/v1/admin/lots/{lot1['lot_id']}")).json()
            must(admin.get(f"/api/v1/admin/lots/{lot2['lot_id']}"))
            if str(view1["payment_mode"]) != pre["mode"]:
                raise RuntimeError(
                    f"lot stamped {view1['payment_mode']}; start the API with "
                    f"PAYMENT_MODE={pre['mode']}"
                )
            record["payment_mode_stamped"] = str(view1["payment_mode"])
            report.data["awards"] = awards

        if drainer is None:
            raise RuntimeError("a live run needs the harness's own job drain (drop --worker)")

        def buyer_of(order: dict[str, Any]) -> str:
            for key in buyer_keys:
                if accounts[key]["user_id"] == order["user_id"]:
                    return key
            raise RuntimeError("a buyer order belongs to an account outside the fixtures")

        def continue_offer(order: dict[str, Any], key: str) -> dict[str, Any]:
            body = must(
                sessions[key].post(
                    f"/api/v1/offers/{order['buyer_order_id']}/continue",
                    json={"shipping": SHIPPING},
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            ).json()
            path = redirector.short_path(order["buyer_order_id"], str(body["approve_url"]))
            print(
                f"  APPROVE as {key} (lot {order['lot_id'][:8]}, "
                f"{order['total_cents']} cents): {path}"
            )
            return {
                "buyer_order_id": order["buyer_order_id"],
                "buyer_key": key,
                "paypal_order_id": str(body["paypal_order_id"]),
                "offer_expires_at": order["offer_expires_at"],
                "total_cents": order["total_cents"],
                "approve_path": path,
                "approval_ui": body.get("approval_ui"),
            }

        async def order_status(buyer_order_id: str) -> str:
            async with factory() as session:
                value = await session.scalar(
                    text("SELECT status::text FROM buyer_orders WHERE id = :id"),
                    {"id": UUID(buyer_order_id)},
                )
            return str(value)

        async def lot_status(lot_id: str) -> str:
            return await read_lot_status(factory, lot_id)

        async def wait_for_approvals(
            targets: list[dict[str, Any]], *, timeout_at: float, what: str
        ) -> None:
            """Poll PayPal read-only, then send the server-side approval callback."""
            pending = list(targets)
            while pending:
                await drainer.run_due(exclude=("order.capture",))
                for target in list(pending):
                    try:
                        seen = await surface.router.gateway.get_order(
                            str(target["paypal_order_id"])
                        )
                        status = str(seen.status)
                    except Exception:  # noqa: BLE001 - a transient GET is retried
                        status = None
                    # A return-URL flow may already have authorized the order, in
                    # which case PayPal reads COMPLETED; the POST is idempotent and
                    # the server's own GET is still the check that counts (I4).
                    if status not in {"APPROVED", "COMPLETED"}:
                        continue
                    answer = must(
                        sessions[target["buyer_key"]].post(
                            f"/api/v1/offers/{target['buyer_order_id']}/approved",
                            json={"paypal_order_id": target["paypal_order_id"]},
                        )
                    ).json()
                    if str(answer["status"]) != "APPROVED":
                        raise RuntimeError(f"POST .../approved answered {answer['status']}")
                    pending.remove(target)
                if pending and time.monotonic() > timeout_at:
                    raise RuntimeError(f"timed out waiting for {what}")
                if pending:
                    await asyncio.sleep(5)

        async with report.step("checkout_orders") as record:
            orders = await read_orders(factory, main_pool)
            lot1_orders = [order for order in orders if order["lot_id"] == lot1["lot_id"]]
            lot2_orders = [order for order in orders if order["lot_id"] == lot2["lot_id"]]
            if len(lot1_orders) != 1 or len(lot2_orders) != 2:
                raise RuntimeError(
                    f"expected one lot-1 and two lot-2 offers, saw "
                    f"{len(lot1_orders)} and {len(lot2_orders)}"
                )
            waitlisted = {
                str(key)
                for key in buyer_keys
                if report.data.get("allocations", {}).get(accounts[key]["user_id"]) == "WAITLISTED"
            }
            if len(waitlisted) != 1:
                raise RuntimeError(f"expected one waitlisted fixture, saw {sorted(waitlisted)}")
            lot1_target = continue_offer(lot1_orders[0], buyer_of(lot1_orders[0]))
            lot2_target = continue_offer(lot2_orders[0], buyer_of(lot2_orders[0]))
            expiring = lot2_orders[1]
            record["lot1_order"] = lot1_target
            record["lot2_order"] = lot2_target
            record["expiring_order"] = expiring["buyer_order_id"]
            record["waitlist_buyer"] = sorted(waitlisted)[0]
            report.data["approval_paths"] = [
                lot1_target["approve_path"],
                lot2_target["approve_path"],
            ]
            report.data["checkout"] = {
                "lot1": {k: lot1_target[k] for k in ("buyer_order_id", "paypal_order_id")},
                "lot2": {k: lot2_target[k] for k in ("buyer_order_id", "paypal_order_id")},
                "expiring_buyer_order_id": expiring["buyer_order_id"],
            }

        def is_order(buyer_order_id: str, wanted: set[str]) -> Callable[[], Awaitable[bool]]:
            async def check() -> bool:
                return await order_status(buyer_order_id) in wanted

            return check

        def is_lot(lot_id: str, wanted: set[str]) -> Callable[[], Awaitable[bool]]:
            async def check() -> bool:
                return await lot_status(lot_id) in wanted

            return check

        async with report.step("lot1_funded") as record:
            lot1_expiry = datetime.fromisoformat(str(lot1_target["offer_expires_at"]))
            lot2_expiry = datetime.fromisoformat(str(lot2_target["offer_expires_at"]))
            # Both decisions are collected in one loop so a buyer who approves second
            # still gets the server-side callback inside their own offer window.
            await wait_for_approvals(
                [lot1_target, lot2_target],
                timeout_at=time.monotonic()
                + max(
                    30.0, (min(lot1_expiry, lot2_expiry) - datetime.now(UTC)).total_seconds() - 10
                ),
                what="the lot 1 and lot 2 buyer approvals",
            )
            await drain_until(
                drainer,
                is_order(lot1_target["buyer_order_id"], {"AUTHORIZED"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="the lot 1 authorization",
            )
            await drain_until(
                drainer,
                is_lot(lot1["lot_id"], {"FUNDING"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="lot 1 FUNDING",
            )
            await drainer.run_capture(UUID(lot1_target["buyer_order_id"]))
            await drain_until(
                drainer,
                is_lot(lot1["lot_id"], {"FUNDED", "CLOSED"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="lot 1 FUNDED",
            )
            record["lot1_status"] = await lot_status(lot1["lot_id"])
            record["capture_status"] = await order_status(lot1_target["buyer_order_id"])
            print(f"  lot 1 is {record['lot1_status']} on one completed capture")

        async with report.step("lot2_authorized") as record:
            await drain_until(
                drainer,
                is_order(lot2_target["buyer_order_id"], {"AUTHORIZED"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="the lot 2 authorization",
            )
            record["order_status"] = await order_status(lot2_target["buyer_order_id"])
            record["lot_status"] = await lot_status(lot2["lot_id"])

        async with report.step("offer_expired_refilled") as record:
            known = {
                lot1_target["buyer_order_id"],
                lot2_target["buyer_order_id"],
                expiring["buyer_order_id"],
            }

            async def refill_offered() -> bool:
                current = await read_orders(factory, main_pool)
                return any(
                    order["lot_id"] == lot2["lot_id"]
                    and order["buyer_order_id"] not in known
                    and order["status"] == "OFFERED"
                    for order in current
                )

            await drain_until(
                drainer,
                refill_offered,
                deadline=time.monotonic() + 480,
                exclude=("order.capture",),
                what="the untaken offer to expire and lot.refill to fill the seat",
            )
            current = await read_orders(factory, main_pool)
            expired = next(
                order for order in current if order["buyer_order_id"] == expiring["buyer_order_id"]
            )
            if expired["status"] != "EXPIRED":
                raise RuntimeError(f"the untaken offer is {expired['status']}, not EXPIRED")
            refill_order = next(
                order
                for order in current
                if order["lot_id"] == lot2["lot_id"] and order["buyer_order_id"] not in known
            )
            refill_key = buyer_of(refill_order)
            if refill_key != sorted(waitlisted)[0]:
                raise RuntimeError("lot.refill offered the seat to the wrong entry")
            refill_target = continue_offer(refill_order, refill_key)
            lots_now = await read_lots(factory, main_pool)
            record["expired_order"] = expiring["buyer_order_id"]
            record["refill_order"] = refill_order["buyer_order_id"]
            record["refill_wave"] = next(lot for lot in lots_now if lot["lot_order"] == 2)[
                "refill_waves"
            ]
            report.data.setdefault("approval_paths", []).append(refill_target["approve_path"])
            print(f"  lot.refill wave {record['refill_wave']}: seat offered to the waitlist")

        async with report.step("lot2_failure_prepared") as record:
            lots_now = await read_lots(factory, main_pool)
            lot2_now = next(lot for lot in lots_now if lot["lot_order"] == 2)
            fund_deadline = datetime.fromisoformat(str(lot2_now["fund_deadline_at"]))
            await wait_for_approvals(
                [refill_target],
                timeout_at=time.monotonic()
                + max(30.0, (fund_deadline - datetime.now(UTC)).total_seconds() - 25),
                what="the refilled seat approval before the fund deadline",
            )
            await drain_until(
                drainer,
                is_order(refill_target["buyer_order_id"], {"AUTHORIZED"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="the refilled authorization",
            )
            await drain_until(
                drainer,
                is_lot(lot2["lot_id"], {"FUNDING"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="lot 2 FUNDING on two authorizations",
            )
            # One capture runs; the other stays queued past the fund deadline, which is
            # what a slow sweep looks like. LS-09 then has a completed capture to refund
            # and a live authorization to void, both proven by the failure handler.
            await drainer.run_capture(UUID(lot2_target["buyer_order_id"]))
            await drain_until(
                drainer,
                is_order(lot2_target["buyer_order_id"], {"CAPTURED"}),
                deadline=time.monotonic() + 120,
                exclude=("order.capture",),
                what="the completed lot 2 capture",
            )
            record["captured_order"] = lot2_target["buyer_order_id"]
            record["held_order"] = refill_target["buyer_order_id"]
            record["held_status"] = await order_status(refill_target["buyer_order_id"])

        async with report.step("lot2_failed_net_zero") as record:
            lots_now = await read_lots(factory, main_pool)
            fund_deadline = datetime.fromisoformat(
                str(next(lot for lot in lots_now if lot["lot_order"] == 2)["fund_deadline_at"])
            )
            await drain_until(
                drainer,
                is_lot(lot2["lot_id"], {"FAILED_CLOSED"}),
                deadline=time.monotonic()
                + max(30.0, (fund_deadline - datetime.now(UTC)).total_seconds() + 240),
                exclude=("order.capture",),
                what="LS-09 at the fund deadline, the void and refund, and LS-10",
            )
            # The withheld capture job is now stale; running it proves it ignores a
            # seat that already left AUTHORIZED (I15). It also lets lot 1 close.
            await drainer.run_due()
            record["lot2_status"] = await lot_status(lot2["lot_id"])
            record["lot1_status"] = await lot_status(lot1["lot_id"])
            record["refunded_order"] = await order_status(lot2_target["buyer_order_id"])
            record["voided_order"] = await order_status(refill_target["buyer_order_id"])
            if record["refunded_order"] != "REFUNDED":
                raise RuntimeError(f"the captured seat is {record['refunded_order']}")
            if record["voided_order"] != "VOIDED":
                raise RuntimeError(f"the held seat is {record['voided_order']}")
            print(
                f"  lot 2 {record['lot2_status']}: one authorization VOIDED, "
                "one capture REFUNDED, net zero"
            )

        async with report.step("verification") as record:
            lots_now = await read_lots(factory, main_pool)
            orders_now = await read_orders(factory, main_pool)
            ledger1 = await read_ledger(factory, lot1["lot_id"])
            ledger2 = await read_ledger(factory, lot2["lot_id"])
            lot1_row = next(lot for lot in lots_now if lot["lot_order"] == 1)
            lot2_row = next(lot for lot in lots_now if lot["lot_order"] == 2)
            if lot1_row["status"] not in {"FUNDED", "CLOSED"}:
                raise RuntimeError(f"lot 1 ended {lot1_row['status']}")
            if lot2_row["status"] != "FAILED_CLOSED":
                raise RuntimeError(f"lot 2 ended {lot2_row['status']}")
            if ledger2["net_paid_cents"] != 0:
                raise RuntimeError(f"lot 2 net paid is {ledger2['net_paid_cents']}")
            kinds2 = {entry["kind"] for entry in ledger2["entries"]}
            if not {"CAPTURE_COMPLETED", "REFUND_COMPLETED", "AUTH_VOIDED"} <= kinds2:
                raise RuntimeError(f"lot 2 ledger kinds are {sorted(kinds2)}")
            captured = next(
                order
                for order in orders_now
                if order["buyer_order_id"] == lot2_target["buyer_order_id"]
            )
            if not captured["paypal_refund_id"]:
                raise RuntimeError("the lot 2 refund has no provider reference")
            record["lots"] = lots_now
            record["ledger"] = {"lot1": ledger1, "lot2": ledger2}
            record["captured_order"] = {
                key: captured.get(key)
                for key in (
                    "buyer_order_id",
                    "status",
                    "total_cents",
                    "paypal_order_id",
                    "paypal_auth_id",
                    "paypal_capture_id",
                    "paypal_refund_id",
                )
            }
            report.data["final_lots"] = lots_now
            report.data["ledger"] = {"lot1": ledger1, "lot2": ledger2}
            report.data["orders"] = [
                {
                    "buyer": buyer_of(order),
                    "lot_order": 1 if order["lot_id"] == lot1["lot_id"] else 2,
                    "buyer_order_id": order["buyer_order_id"],
                    "status": order["status"],
                    "total_cents": order["total_cents"],
                    "paypal_order_id": order.get("paypal_order_id"),
                    "paypal_auth_id": order.get("paypal_auth_id"),
                    "paypal_capture_id": order.get("paypal_capture_id"),
                    "paypal_refund_id": order.get("paypal_refund_id"),
                }
                for order in orders_now
            ]

        async with report.step("ops_reads") as record:
            view1 = must(admin.get(f"/api/v1/admin/lots/{lot1['lot_id']}")).json()
            view2 = must(admin.get(f"/api/v1/admin/lots/{lot2['lot_id']}")).json()
            alerts = must(admin.get("/api/v1/admin/alerts")).json()
            dead = must(admin.get("/api/v1/admin/webhooks/dead-letter")).json()
            export = must(admin.get("/api/v1/admin/audit/export")).json()
            if not export.get("checkpoints"):
                raise RuntimeError("the audit export returned no checkpoints")
            record["lot1"] = {key: view1[key] for key in ("status", "seats", "min_seats")}
            record["lot2"] = {key: view2[key] for key in ("status", "seats", "min_seats")}
            record["alerts"] = int(alerts.get("count", 0))
            record["dead_letters"] = len(dead.get("events", []))
            record["audit_checkpoints"] = len(export["checkpoints"])

        async with report.step("evidence_written") as record:
            record["orders"] = len(report.data.get("orders", []))
        report.write("passed")
        print(f"\nIT-7 passed; report: {report.out}")

    finally:
        closer = getattr(getattr(surface.router, "gateway", None), "close", None)
        if closer is not None:
            await closer()
        for client in sessions.values():
            client.close()
        if redirector is not None:
            redirector.stop()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run the whole IT-7 flow")
    parser.add_argument("--dry-run", action="store_true", help="stop after the open half")
    parser.add_argument(
        "--worker", action="store_true", help="wait on a running worker; never drain"
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=".tmp/it7_report.json")
    arguments = parser.parse_args()
    if arguments.live == arguments.dry_run:
        parser.error("choose exactly one of --live or --dry-run")
    raise SystemExit(asyncio.run(main(arguments)))
