"""Read-only proof that the demo database tells the story ``demo_seed.py`` promises.

    .venv/Scripts/python.exe tools/demo_seed_check.py

Connects to the loopback ``fairpool`` database only (the same derivation as the
seeder), reads rows, and prints one PASS/FAIL line per requirement. It writes
nothing, prints no password, no address and no full provider id, and exits 1 when
any check fails.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import demo_seed  # noqa: E402


class Result:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        print(f"{'PASS' if condition else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")
        if not condition:
            self.failures += 1


async def pool_id(conn: Any, title: str) -> Any:
    return await conn.fetchval(
        "SELECT p.id FROM pools p JOIN users u ON u.id = p.created_by "
        "WHERE p.title = $1 AND u.email = $2 AND p.mode = 'LIVE_SANDBOX'::pool_mode "
        "ORDER BY p.created_at",
        title,
        demo_seed.ADMIN_EMAIL,
    )


async def lot(conn: Any, pool: Any) -> Any:
    return await conn.fetchrow(
        "SELECT id, status::text AS status, bid_close_at, seats FROM lots "
        "WHERE pool_id = $1 ORDER BY lot_order LIMIT 1",
        pool,
    )


async def main() -> int:
    demo_seed.load_env()
    import asyncpg

    dsn = demo_seed.loopback_database_url().replace("postgresql+asyncpg://", "postgresql://")
    result = Result()
    conn = await asyncpg.connect(dsn)
    try:
        # ---------------------------------------------------------- accounts
        for email in demo_seed.BUYER_EMAILS:
            role = await conn.fetchval("SELECT role::text FROM users WHERE email = $1", email)
            result.check(f"account {email} role buyer", role == "buyer")
        for email in demo_seed.MERCHANT_EMAILS:
            role = await conn.fetchval("SELECT role::text FROM users WHERE email = $1", email)
            result.check(f"account {email} role merchant", role == "merchant")
        admin_role = await conn.fetchval(
            "SELECT role::text FROM users WHERE email = $1", demo_seed.ADMIN_EMAIL
        )
        result.check("account admin role admin", admin_role == "admin")

        for email, name in (
            (demo_seed.MERCHANT_EMAILS[0], "Demo Merchant Alpha"),
            (demo_seed.MERCHANT_EMAILS[1], "Demo Merchant Beta"),
        ):
            row = await conn.fetchrow(
                "SELECT m.display_name, m.attestations FROM merchants m "
                "JOIN users u ON u.id = m.user_id WHERE u.email = $1",
                email,
            )
            attestations = row["attestations"] if row is not None else None
            if isinstance(attestations, str):
                attestations = json.loads(attestations)
            accepted = isinstance(attestations, dict) and all(
                isinstance(attestations.get(key), dict)
                and attestations[key].get("accepted") is True
                for key in ("inventory_reserved", "map_compliance", "delivery_terms_accurate")
            )
            result.check(
                f"{name} profile and three attestations",
                row is not None and row["display_name"] == name and accepted,
            )

        # ------------------------------------------------------ no duplicates
        for title in (spec["title"] for spec in demo_seed.POOL_SPECS):
            count = await conn.fetchval(
                "SELECT count(*) FROM pools p JOIN users u ON u.id = p.created_by "
                "WHERE p.title = $1 AND u.email = $2 AND p.mode = 'LIVE_SANDBOX'::pool_mode",
                title,
                demo_seed.ADMIN_EMAIL,
            )
            result.check(f"one demo pool titled {title!r}", count == 1, f"count={count}")

        monitor = await pool_id(conn, "27-inch 4K monitor")
        headphones = await pool_id(conn, "Wireless over-ear headphones")
        desk = await pool_id(conn, "Walnut standing desk")
        chair = await pool_id(conn, "Ergonomic chair")

        # ------------------------------------------------- demand board (pool 1)
        monitor_lots = await conn.fetch(
            "SELECT id, status::text AS status, bid_close_at, seats FROM lots "
            "WHERE pool_id = $1 ORDER BY lot_order",
            monitor,
        )
        result.check(
            "pool 1 has two BIDDING lots",
            [row["status"] for row in monitor_lots] == ["BIDDING", "BIDDING"],
        )
        five_hours = await conn.fetchval("SELECT now() + interval '5 hours'")
        result.check(
            "pool 1 bidding closes about six hours ahead",
            len(monitor_lots) == 2
            and all(row["bid_close_at"] > five_hours for row in monitor_lots),
        )
        result.check(
            "pool 1 seats are 3+2 with min 1+2",
            [int(row["seats"]) for row in monitor_lots] == [3, 2]
            and await conn.fetchval(
                "SELECT array_agg(min_seats ORDER BY lot_order)::text FROM lots WHERE pool_id = $1",
                monitor,
            )
            == "{1,2}",
        )
        waitlisted = await conn.fetchval(
            "SELECT count(*) FROM allocations WHERE pool_id = $1 AND status = 'WAITLISTED'",
            monitor,
        )
        entries = await conn.fetchval(
            "SELECT count(*) FROM pool_entries WHERE pool_id = $1", monitor
        )
        receipts = await conn.fetchval(
            "SELECT count(*) FROM entry_receipts er JOIN pool_entries pe ON pe.id = er.entry_id "
            "WHERE pe.pool_id = $1",
            monitor,
        )
        result.check("pool 1 has one WAITLISTED entry", waitlisted == 1, f"waitlisted={waitlisted}")
        result.check(
            "pool 1 entries all carry signed receipts",
            entries == 6 and receipts == 6,
            f"entries={entries} receipts={receipts}",
        )

        # ------------------------------------------- active bids (pool 2)
        headphones_lot = await lot(conn, headphones)
        result.check("pool 2 lot is CHECKOUT_OPEN", headphones_lot["status"] == "CHECKOUT_OPEN")
        offered = await conn.fetch(
            "SELECT bo.id, bo.offer_expires_at FROM buyer_orders bo WHERE bo.lot_id = $1 "
            "AND bo.status = 'OFFERED'",
            headphones_lot["id"],
        )
        result.check("pool 2 has two OFFERED orders", len(offered) == 2, f"orders={len(offered)}")
        ninety_minutes = await conn.fetchval("SELECT now() + interval '90 minutes'")
        result.check(
            "pool 2 offers expire about two hours ahead",
            len(offered) == 2 and all(row["offer_expires_at"] > ninety_minutes for row in offered),
        )
        lost = await conn.fetchval(
            "SELECT count(*) FROM bids b JOIN merchants m ON m.id = b.merchant_id "
            "JOIN users u ON u.id = m.user_id WHERE b.lot_id = $1 AND b.status = 'LOST' "
            "AND u.email = $2",
            headphones_lot["id"],
            demo_seed.MERCHANT_EMAILS[1],
        )
        result.check("pool 2 has a LOST bid by Demo Merchant Beta", lost == 1)

        # ------------------------------------------------ funded (pool 3)
        desk_lot = await lot(conn, desk)
        result.check(
            "pool 3 lot is FUNDED or CLOSED",
            desk_lot["status"] in {"FUNDED", "CLOSED"},
            f"status={desk_lot['status']}",
        )
        captured = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders WHERE lot_id = $1 AND status = 'CAPTURED'",
            desk_lot["id"],
        )
        result.check("pool 3 has two CAPTURED orders", captured == 2, f"captured={captured}")
        net = await conn.fetchval(
            "SELECT COALESCE(sum(CASE WHEN kind = 'CAPTURE_COMPLETED' THEN amount_cents "
            "WHEN kind = 'REFUND_COMPLETED' THEN -amount_cents ELSE 0 END), 0) "
            "FROM ledger_entries WHERE lot_id = $1",
            desk_lot["id"],
        )
        result.check("pool 3 ledger net is 94000", int(net) == 94_000, f"net={int(net)}")
        desk_captures = await conn.fetch(
            "SELECT pc.paypal_capture_id FROM paypal_captures pc JOIN buyer_orders bo "
            "ON bo.id = pc.buyer_order_id WHERE bo.lot_id = $1 AND pc.status = 'COMPLETED'",
            desk_lot["id"],
        )
        result.check(
            "pool 3 captures are demo-shaped",
            len(desk_captures) == 2
            and all(str(row["paypal_capture_id"]).startswith("DEMO-") for row in desk_captures),
        )
        sealed = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders WHERE lot_id = $1 AND shipping_enc IS NOT NULL",
            desk_lot["id"],
        )
        result.check("pool 3 shipping addresses are sealed", sealed == 2, f"sealed={sealed}")
        shipments = await conn.fetch(
            "SELECT paypal_tracker_status FROM shipments WHERE lot_id = $1", desk_lot["id"]
        )
        # The demo rows never call PayPal, so no tracker status is claimed.
        unsubmitted = sum(1 for row in shipments if row["paypal_tracker_status"] is None)
        result.check(
            "pool 3 has two shipments with no tracker claim",
            len(shipments) == 2 and unsubmitted == 2,
            f"rows={len(shipments)} unsubmitted={unsubmitted}",
        )
        unmatched = await conn.fetchval(
            "SELECT count(*) FROM paypal_captures pc "
            "JOIN buyer_orders bo ON bo.id = pc.buyer_order_id "
            "LEFT JOIN ledger_entries le ON le.buyer_order_id = bo.id "
            "AND le.paypal_ref = pc.paypal_capture_id AND le.kind = 'CAPTURE_COMPLETED' "
            "WHERE bo.lot_id = $1 AND le.id IS NULL",
            desk_lot["id"],
        )
        result.check("every pool 3 capture has a ledger fact", unmatched == 0)

        # ------------------------------------------------- failed (pool 4)
        chair_lot = await lot(conn, chair)
        result.check("pool 4 lot is FAILED_CLOSED", chair_lot["status"] == "FAILED_CLOSED")
        chair_states = await conn.fetch(
            "SELECT bo.status::text AS status, pa.status AS auth_status, "
            "pr.status AS refund_status FROM buyer_orders bo "
            "LEFT JOIN paypal_authorizations pa ON pa.buyer_order_id = bo.id "
            "LEFT JOIN paypal_captures pc ON pc.buyer_order_id = bo.id "
            "LEFT JOIN paypal_refunds pr ON pr.paypal_capture_id = pc.paypal_capture_id "
            "WHERE bo.lot_id = $1 ORDER BY bo.status::text",
            chair_lot["id"],
        )
        states = {row["status"]: row for row in chair_states}
        result.check(
            "pool 4 has one VOIDED and one REFUNDED order",
            set(states) == {"VOIDED", "REFUNDED"},
            f"states={sorted(states)}",
        )
        result.check(
            "pool 4 authorization reads VOIDED",
            states.get("VOIDED") is not None and states["VOIDED"]["auth_status"] == "VOIDED",
        )
        result.check(
            "pool 4 refund reads COMPLETED",
            states.get("REFUNDED") is not None
            and states["REFUNDED"]["refund_status"] == "COMPLETED",
        )
        chair_net = await conn.fetchval(
            "SELECT COALESCE(sum(CASE WHEN kind = 'CAPTURE_COMPLETED' THEN amount_cents "
            "WHEN kind = 'REFUND_COMPLETED' THEN -amount_cents ELSE 0 END), 0) "
            "FROM ledger_entries WHERE lot_id = $1",
            chair_lot["id"],
        )
        result.check("pool 4 ledger net is zero", int(chair_net) == 0, f"net={int(chair_net)}")

        # -------------------------------------------- buyer consistency
        buyer_one = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
            "JOIN users u ON u.id = pe.user_id JOIN lots l ON l.id = bo.lot_id "
            "WHERE u.email = $1 AND l.pool_id = $2 AND bo.status = 'OFFERED'",
            demo_seed.BUYER_EMAILS[0],
            headphones,
        )
        buyer_one_captured = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
            "JOIN users u ON u.id = pe.user_id JOIN lots l ON l.id = bo.lot_id "
            "WHERE u.email = $1 AND l.pool_id = $2 AND bo.status = 'CAPTURED'",
            demo_seed.BUYER_EMAILS[0],
            desk,
        )
        buyer_two_offer = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
            "JOIN users u ON u.id = pe.user_id JOIN lots l ON l.id = bo.lot_id "
            "WHERE u.email = $1 AND l.pool_id = $2 AND bo.status = 'OFFERED'",
            demo_seed.BUYER_EMAILS[1],
            headphones,
        )
        buyer_two_refunded = await conn.fetchval(
            "SELECT count(*) FROM buyer_orders bo JOIN pool_entries pe ON pe.id = bo.entry_id "
            "JOIN users u ON u.id = pe.user_id JOIN lots l ON l.id = bo.lot_id "
            "WHERE u.email = $1 AND l.pool_id = $2 AND bo.status = 'REFUNDED'",
            demo_seed.BUYER_EMAILS[1],
            chair,
        )
        result.check(
            "buyer 1 has an offer and a captured order",
            buyer_one == 1 and buyer_one_captured == 1,
        )
        result.check(
            "buyer 2 has an offer and a refunded order",
            buyer_two_offer == 1 and buyer_two_refunded == 1,
        )

        # ------------------------------------------------ simulation pool
        sim = await conn.fetchrow(
            "SELECT id, mode::text AS mode, entries_count FROM pools WHERE id = $1",
            demo_seed.demo_id("pool:simulation-4k-monitor"),
        )
        result.check(
            "simulation pool is SIMULATION with 10,000 entries",
            sim is not None and sim["mode"] == "SIMULATION" and int(sim["entries_count"]) == 10_000,
        )
        sim_allocations = await conn.fetchval(
            "SELECT count(*) FROM allocations a JOIN pools p ON p.id = a.pool_id "
            "WHERE p.id = $1 AND p.mode = 'SIMULATION'::pool_mode",
            demo_seed.demo_id("pool:simulation-4k-monitor"),
        )
        result.check("simulation pool has 10,000 allocations", int(sim_allocations) == 10_000)
        listed = await conn.fetchval(
            "SELECT count(*) FROM pools WHERE id = $1 AND mode = 'LIVE_SANDBOX'::pool_mode",
            demo_seed.demo_id("pool:simulation-4k-monitor"),
        )
        result.check("simulation pool is not a public list entry", int(listed) == 0)
    finally:
        await conn.close()

    verdict = "ALL CHECKS PASSED" if result.failures == 0 else f"{result.failures} FAILED"
    print(f"\n{verdict}")
    return 0 if result.failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
