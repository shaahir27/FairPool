"""CR-11 / T06A06: the bid set is committed at the deadline, and the chain head is signed.

Two halves, deliberately separated. The handler tests prove FairPool *writes* the
commitment while bidding is sealed; the audit-page tests prove a reader can *check* it
and check the signature over the chain head without trusting the payload's own text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.domain import hashing
from fairpool.infra.audit import PostgresAuditLog
from fairpool.modules.auction.handlers import LotAuctionHandlers
from tests.integration.test_bid_sealing import (
    bidding_world,
    lot_with_deadline,
    service,
    structured,
)
from tests.integration.test_join_receipts import settings_for
from tests.integration.test_open_checkout import World, build_world
from tests.integration.test_public_audit_no_pii import close_pool

pytestmark = pytest.mark.integration


def auction(world: World) -> LotAuctionHandlers:
    ports = world.ports
    return LotAuctionHandlers(
        clock=ports.clock,
        audit=ports.audit,
        jobs=ports.jobs,
        notifier=ports.notifier,
        payment_router="single_seller",
        payment_mode="authorize_capture",
        flat_delivered=True,
    )


async def close_bidding(session: AsyncSession, world: World) -> dict[str, Any]:
    """Run ``lot.bid_close`` past its deadline and return the LS-02 audit payload."""
    await lot_with_deadline(session, world, offset_s=-5)
    await auction(world).bid_close(session, {"lot_id": str(world.lot_id)})
    rows = [
        row["row"]
        for row in world.ports.audit.rows
        if str(row["row"]["action"]) == "lot.bid_closed"
    ]
    assert len(rows) == 1, [row["action"] for row in world.ports.audit.rows]
    return dict(rows[0]["payload"])


async def receipt_hashes(session: AsyncSession, lot_id: UUID) -> list[str]:
    rows = (
        await session.execute(
            text(
                "SELECT r.receipt_hash FROM bid_revisions r "
                "JOIN bids b ON b.id = r.bid_id "
                "WHERE b.lot_id = :lot AND r.revision = b.current_revision "
                "ORDER BY r.receipt_hash"
            ),
            {"lot": str(lot_id)},
        )
    ).all()
    return [str(row[0]) for row in rows]


async def test_bid_close_commits_to_the_bid_set(db_session: AsyncSession) -> None:
    # T06A06 acceptance (CR-11): the root equals merkle_root over the recorded
    # receipt hashes, so the set of bids is fixed before any award exists.
    world = await bidding_world(db_session)
    await lot_with_deadline(db_session, world, offset_s=600)
    bid, _ = await service().save(
        db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
    )
    assert bid is not None

    payload = await close_bidding(db_session, world)

    leaves = await receipt_hashes(db_session, world.lot_id)
    assert len(leaves) == 1
    assert payload["bids_root"] == hashing.merkle_root(leaves)
    assert payload["bids_count"] == 1


async def test_the_root_follows_the_highest_revision_of_each_bid(
    db_session: AsyncSession,
) -> None:
    """A revise replaces the leaf; it does not add one (fairness §6)."""
    world = await bidding_world(db_session)
    await lot_with_deadline(db_session, world, offset_s=600)
    bids = service()
    await bids.save(
        db_session, merchant_id=world.merchant_id, lot_id=world.lot_id, structured=structured()
    )
    await bids.save(
        db_session,
        merchant_id=world.merchant_id,
        lot_id=world.lot_id,
        structured=structured(capacity=20),
    )

    payload = await close_bidding(db_session, world)

    leaves = await receipt_hashes(db_session, world.lot_id)
    assert payload["bids_count"] == 1, "two revisions of one bid are one leaf"
    assert payload["bids_root"] == hashing.merkle_root(leaves)
    # Committing to the highest revision only is what makes the root a commitment to
    # contents: the root over the superseded first revision must differ.
    first = (
        await db_session.execute(
            text("SELECT receipt_hash FROM bid_revisions ORDER BY revision LIMIT 1")
        )
    ).scalar_one()
    assert payload["bids_root"] != hashing.merkle_root([str(first)])


async def test_an_empty_bid_set_is_a_root_and_not_an_absence(db_session: AsyncSession) -> None:
    world = await bidding_world(db_session)

    payload = await close_bidding(db_session, world)

    assert payload["bids_root"] == hashing.EMPTY_MERKLE_ROOT
    assert payload["bids_count"] == 0


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


async def seed_bid_closed_row(db_session: AsyncSession, lot_id: UUID, root: str) -> None:
    """Write the LS-02 audit row through the real chained writer, not by hand."""
    await PostgresAuditLog().append(
        db_session,
        actor="worker",
        action="lot.bid_closed",
        subject_type="lot",
        subject_id=str(lot_id),
        payload={"pool_id": "", "from": "BIDDING", "to": "BID_CLOSED", "bids_root": root},
    )


async def audit(client: httpx.AsyncClient, pool_id: UUID) -> dict[str, Any]:
    response = await client.get(f"/api/v1/public/pools/{pool_id}/audit")
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_the_published_checkpoint_verifies_with_the_served_key(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    # CR-11: the signature is what makes "the chain is self-consistent" checkable by
    # someone who does not trust the page's own text.
    root = hashing.merkle_root(["ab" * 32])
    world = await build_world(db_session, seats=3, min_seats=2, seated=2, waitlisted=1)
    await seed_bid_closed_row(db_session, world.lot_id, root)
    await close_pool(db_session, world.pool_id)

    payload = await audit(client, world.pool_id)
    keys = await client.get("/api/v1/public/keys")
    public_key = keys.json()["public_key"]

    checkpoint = payload["checkpoint"]
    assert checkpoint["bids_roots"][str(world.lot_id)] == root
    signature = str(checkpoint["signature"])
    signed = {key: value for key, value in checkpoint.items() if key != "signature"}
    assert hashing.verify_ed25519(signed, signature, public_key)
    tampered = {**signed, "head_hash": "00" * 32}
    assert not hashing.verify_ed25519(tampered, signature, public_key)
    assert payload["lots"][0]["bids_root"] == root
    assert payload["lots"][0]["bids_count"] is None  # no bids_count in this LS-02 row


async def test_the_seed_is_withheld_while_any_lot_is_still_bidding(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """CR-11 reveal gate: tiebreak_hash(seed, lot, merchant) is pure arithmetic."""
    world = await build_world(db_session, seats=3, min_seats=2, seated=2, waitlisted=1)
    await db_session.execute(
        text("UPDATE lots SET status = 'BIDDING' WHERE id = :lot"), {"lot": str(world.lot_id)}
    )
    await close_pool(db_session, world.pool_id)

    payload = await audit(client, world.pool_id)

    assert payload["seed_hex"] is None
    assert payload["beacon"] is None
    assert payload["audit_checkpoints"] == []
    assert payload["checkpoint"] is None
    # The close-time snapshot is NOT gated by the reveal rule: buyers keep being able
    # to check that their own entry is in the list they committed to, and the lot list
    # carries no bid or crowd information.
    assert payload["entries_root"] is not None
    assert [lot["lot_id"] for lot in payload["lots"]] == [str(world.lot_id)]
    assert payload["lots"][0]["status"] == "BIDDING"
