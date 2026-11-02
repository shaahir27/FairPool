"""Create one demo pool with real buyers, offers and buyer orders.

Run against the *development* database (``.env``), not the test one:

    python tools/demo_seed.py                 # six buyers, authorize_capture
    python tools/demo_seed.py --buyers 8

``DEMO_SEED_PASSWORD`` in ``.env`` is the shared demo password. The script has no
default, does not read it from the command line, and never prints it.

It reuses the IT-4 harness so the demo data is produced by the same services the
app uses: pool create/publish, intake, join with signed receipts, close, seed,
allocate, force-award and checkout opening. Prints the offer and order URLs plus
the buyer login. It makes **no** PayPal call: every offer is created OFFERED and
waits for the buyer to press Continue.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "src"))


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        raise SystemExit("missing .env at the repository root")
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


async def sync_demo_password(identity: Any, session: Any, email: str, secret: str) -> None:
    """Give a demo account this run's password.

    An earlier run created the same address with the value that environment had then;
    its rows and seats stay and only the login secret moves. Demo addresses only: the
    seeder owns these names.
    """
    hashed = await asyncio.to_thread(identity.hasher.hash, secret)
    await session.execute(
        text("UPDATE users SET password_hash = :hash WHERE email = :email"),
        {"hash": hashed, "email": email},
    )
    await session.flush()


async def main(buyers: int, moq_override: int) -> int:
    load_env()
    os.environ["PAYMENT_MODE"] = "authorize_capture"
    # I14: a credential comes from the environment only, never from a repo default
    # and never from a command line that ends up in a shell history.
    secret = os.environ.get("DEMO_SEED_PASSWORD")
    if not secret:
        raise SystemExit("no demo password: set DEMO_SEED_PASSWORD in .env")

    from fairpool.api.app import create_app
    from fairpool.api.deps import database_session
    from fairpool.config import Settings
    from fairpool.db.session import create_engine as build_engine
    from fairpool.domain.errors import ApplicationError
    from fairpool.fakes.ai import FakeAI
    from fairpool.infra.audit import PostgresAuditLog
    from fairpool.infra.clock import DbClock
    from fairpool.infra.idempotency import PostgresIdempotencyStore
    from fairpool.modules.identity.service import IdentityService
    from fairpool.modules.intake.pipeline import IntakeService
    from fairpool.modules.intake.run_log import PostgresAiRunLogger
    from fairpool.modules.pools.join import JoinService
    from fairpool.modules.pools.receipts import signing_seed
    from fairpool.modules.search.service import build_search_service
    from fairpool.wiring import checkout_services, worker_handlers
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from tests.integration.test_pipeline_fakes import (
        EAST_MESSAGE,
        PROPOSALS,
        add_user,
        drain,
        force_award,
        move_timeline,
        seed_pool,
    )
    from tests.integration.test_pipeline_fakes import (
        settings as harness_settings,
    )

    config: Settings = Settings()  # reads the real .env: dev DB, real router
    # The app's own engine builder, so the driver scheme and the SSL arguments are
    # normalised the same way: this tool must reach a hosted database too.
    engine = build_engine(config)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        identity = IdentityService(config.secret_key.get_secret_value(), DbClock())
        admin_email = "demo-admin@fairpool.test"
        try:
            created = await identity.register(
                session, email=admin_email, password=secret, display_name="Demo Admin"
            )
            admin_id = UUID(str(created["user_id"]))
        except ApplicationError:
            found = await session.scalar(
                text("SELECT id FROM users WHERE email = :email"), {"email": admin_email}
            )
            if found is None:
                raise
            await sync_demo_password(identity, session, admin_email, secret)
            admin_id = UUID(str(found))
        await session.execute(
            text("UPDATE users SET role = 'admin' WHERE email = :email"), {"email": admin_email}
        )
        merchant_user = await add_user(session, "demo-merchant")
        merchant_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO merchants (id, user_id, display_name, onboarding_status) "
                "VALUES (:id, :user, 'Demo Merchant Alpha', 'DEMO')"
            ),
            {"id": merchant_id, "user": merchant_user},
        )

        surface = checkout_services(config)
        handlers = worker_handlers(config, surface)
        app = create_app(config)
        app.state.checkout_services = surface

        async def session_override() -> Any:
            yield session

        app.dependency_overrides[database_session] = session_override

        import httpx

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
        ) as client:
            pool_id = await seed_pool(session, harness_settings(), admin_id)
            await session.execute(
                text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": admin_id}
            )
            await move_timeline(session, pool_id, key="open_at", seconds=-60)
            await handlers["pool.open"](session, {"pool_id": str(pool_id)})

            ai = FakeAI()
            intake = IntakeService(
                search=build_search_service(config),
                ai=ai,
                audit=PostgresAuditLog(),
                clock=DbClock(),
                run_logger=PostgresAiRunLogger(),
                model="fake-model",
            )
            joins = JoinService(
                DbClock(),
                PostgresAuditLog(),
                PostgresIdempotencyStore(),
                signing_seed=signing_seed(config.receipt_signing_key.get_secret_value()),
                dedupe_mode=config.dedupe_mode,
            )

            # One scripted proposal pair, then real buyers who can sign in.
            from fairpool.domain.errors import ApplicationError

            throwaway = await add_user(session, "demo-script")
            for message, region in ((EAST_MESSAGE, "NY"),):
                await intake.propose(
                    session, user_id=throwaway, message=message, pool_id_override=pool_id
                )
                ai.register_hash(
                    ai.calls[-1].input_hash,
                    {
                        "pool_id": str(pool_id),
                        "match_confidence": "high",
                        "ambiguities": [],
                        "clarifying_question": None,
                        **PROPOSALS[region],
                    },
                )

            entry_ids: list[UUID] = []
            emails: list[str] = []
            for index in range(buyers):
                email = f"demo-buyer-{index + 1}@fairpool.test"
                try:
                    await identity.register(
                        session,
                        email=email,
                        password=secret,
                        display_name=f"Demo Buyer {index + 1}",
                    )
                except ApplicationError:
                    pass
                # An earlier run may own this address: its rows and seats stay and
                # only the login secret moves to this run's value.
                await sync_demo_password(identity, session, email, secret)
                user_id = await session.scalar(
                    text("SELECT id FROM users WHERE email = :email"), {"email": email}
                )
                answer = await intake.propose(
                    session, user_id=user_id, message=EAST_MESSAGE, pool_id_override=pool_id
                )
                if answer["status"] != "READY_TO_CONFIRM":
                    ai.register_hash(
                        ai.calls[-1].input_hash,
                        {
                            "pool_id": str(pool_id),
                            "match_confidence": "high",
                            "ambiguities": [],
                            "clarifying_question": None,
                            **PROPOSALS["NY"],
                        },
                    )
                    answer = await intake.propose(
                        session, user_id=user_id, message=EAST_MESSAGE, pool_id_override=pool_id
                    )
                card = answer["confirmation_card"]
                record = await intake.confirm(
                    session, user_id=user_id, proposal_id=UUID(card["proposal_id"])
                )
                outcome = await joins.join(
                    session,
                    pool_id=pool_id,
                    user_id=user_id,
                    confirmed_request_id=record.id,
                    idempotency_key=f"demo-{email}",
                )
                if outcome.status_code != 201:
                    raise SystemExit(f"join failed for {email}: {outcome.body}")
                entry_ids.append(UUID(str(outcome.body["entry_id"])))
                emails.append(email)

            await move_timeline(session, pool_id, key="close_at", seconds=-60)
            await handlers["pool.close"](session, {"pool_id": str(pool_id)})
            await drain(session, handlers)

            lot = (
                await session.execute(
                    text(
                        "SELECT id, seats FROM lots WHERE pool_id = :pool "
                        "ORDER BY lot_order LIMIT 1"
                    ),
                    {"pool": pool_id},
                )
            ).first()
            if lot is None:
                raise SystemExit("no lot was formed; the pool is too small for its plan")
            moq = moq_override or min(int(lot.seats), 2)
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": admin_email, "password": secret},
            )
            if response.status_code != 200:
                raise SystemExit(f"admin login failed: {response.status_code} {response.text}")
            csrf = str(response.json()["csrf_token"])
            await force_award(
                client,
                csrf,
                lot_id=lot.id,
                merchant_id=merchant_id,
                moq=moq,
            )
            await drain(session, handlers)

            offers = (
                await session.execute(
                    text(
                        "SELECT b.id, b.status, e.user_id, u.email FROM buyer_orders b "
                        "JOIN pool_entries e ON e.id = b.entry_id JOIN users u ON u.id = e.user_id "
                        "WHERE b.lot_id = :lot ORDER BY b.created_at"
                    ),
                    {"lot": lot.id},
                )
            ).all()
            await session.commit()

    await engine.dispose()

    print(f"\npool        {pool_id}")
    print(f"lot         {lot.id}  ({lot.seats} seats, moq {moq})")
    print(f"login       {emails[0]}  (the DEMO_SEED_PASSWORD from .env)")
    print("\nopen these:")
    for row in offers[:3]:
        print(f"  offer   http://localhost:5173/offers/{row.id}")
        print(f"  order   http://localhost:5173/orders/{row.id}")
    print(f"\n{len(offers)} offers created, all OFFERED.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--buyers", type=int, default=6)
    parser.add_argument("--moq", type=int, default=0)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(main(arguments.buyers, arguments.moq)))
