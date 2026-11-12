"""Append a two-month demo calendar without resetting data or creating payments.

Defaults to the loopback demo database. DEMO_SEED_HOSTED=1 explicitly selects
DATABASE_URL. --dry-run validates the complete plan against the database clock.
Existing accounts and published rules are preserved; Buyer 6 stays free to join
the regular calendar pools through the UI or MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import UUID

from demo_seed import (
    ADMIN_EMAIL,
    BUYER_EMAILS,
    calendar_plans,
    load_env,
    loopback_database_url,
    seed_calendar_pool,
)
from fairpool.config import Settings
from fairpool.db.session import create_engine
from fairpool.infra.audit import PostgresAuditLog
from fairpool.infra.clock import DbClock
from fairpool.infra.idempotency import PostgresIdempotencyStore
from fairpool.modules.pools.join import JoinService
from fairpool.modules.pools.receipts import signing_seed
from fairpool.wiring import pool_service
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


async def run(*, dry_run: bool) -> None:
    load_env()
    hosted = os.environ.get("DEMO_SEED_HOSTED") == "1"
    if not hosted:
        os.environ["DATABASE_URL"] = loopback_database_url()
    config = Settings()
    if config.beacon_mode != "demo":
        raise SystemExit("calendar seed requires the explicitly labelled demo beacon")
    engine = create_engine(config)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock, audit = DbClock(), PostgresAuditLog()
    pools = pool_service(config)
    joins = JoinService(
        clock,
        audit,
        PostgresIdempotencyStore(),
        signing_seed=signing_seed(config.receipt_signing_key.get_secret_value()),
        dedupe_mode=config.dedupe_mode,
    )
    try:
        async with factory() as session:
            now = await clock.db_now(session)
            plans = calendar_plans(now)
            identities = dict(
                (
                    await session.execute(
                        text("SELECT email,id FROM users WHERE email = ANY(:emails)"),
                        {"emails": [ADMIN_EMAIL, *BUYER_EMAILS]},
                    )
                ).all()
            )
            if set(identities) != {ADMIN_EMAIL, *BUYER_EMAILS}:
                raise SystemExit("seed the base demo accounts before the calendar")
            admin = UUID(str(identities[ADMIN_EMAIL]))
            buyers = [UUID(str(identities[email])) for email in BUYER_EMAILS]
        print(
            json.dumps(
                {
                    "target": "configured hosted database" if hosted else "loopback demo database",
                    "dry_run": dry_run,
                    "calendar_pools": 24,
                    "merchant_examples": 4,
                    "products": 12,
                    "last_entry_close": plans[23].payload.timeline.close_at.isoformat(),
                    "planned_entries": sum(len(p.buyer_indexes) for p in plans),
                }
            ),
            flush=True,
        )
        if dry_run:
            for plan in plans:
                print(
                    json.dumps(
                        {
                            "title": plan.payload.title,
                            "close_at": plan.payload.timeline.close_at.isoformat(),
                            "entries": len(plan.buyer_indexes),
                        }
                    )
                )
            return
        ids: list[UUID] = []
        for plan in plans:
            async with factory.begin() as session:
                pool = await seed_calendar_pool(
                    session, plan=plan, pools=pools, joins=joins, admin_id=admin, buyers=buyers
                )
                if pool is None:
                    raise SystemExit("calendar pool missing")
                ids.append(pool.id)
                print(
                    json.dumps(
                        {"pool_id": str(pool.id), "title": pool.title, "status": str(pool.status)}
                    ),
                    flush=True,
                )
        async with factory() as session:
            assert await audit.verify_chain(session), "audit chain failed verification"
            orders = await session.scalar(
                text(
                    "SELECT count(*) FROM buyer_orders o JOIN lots l ON l.id=o.lot_id "
                    "WHERE l.pool_id = ANY(:ids)"
                ),
                {"ids": ids},
            )
            assert orders == 0, "calendar seeding must not create payment orders"
            print(
                json.dumps(
                    {
                        "verified_pools": len(ids),
                        "payment_orders_created": 0,
                        "audit_chain": "valid",
                    }
                ),
                flush=True,
            )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(dry_run=args.dry_run))
    except Exception as error:  # noqa: BLE001 - credentials and addresses never enter console errors
        print(f"calendar seed failed ({type(error).__name__}); committed pools remain reusable")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
