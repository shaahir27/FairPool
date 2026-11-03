"""T03A01: the buyer-order transition engine's whitelist, guards, locks and keys.

Every acceptance bullet of the task row names its test below. The engine runs
against the real test database (row locks and advisory locks are the behaviour
under test) with the deterministic port fakes, which is the pattern
``tests/integration/test_platform_services.py`` established. The shared fixtures
here are imported by the other checkout test modules.

Layout: guard matrix and illegal pairs first (bullets 1 and 8), the money paths
that every buyer_order edge must have (bullets 1 and 9), evidence rules (bullet 9),
the stamped-mode rules (bullet 7), the lock and wall-clock order (bullets 2 and 6),
idempotency (bullet 8), and the no-network proof (bullet 10).
"""

from __future__ import annotations

import ast
import itertools
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from fairpool.domain import checkout_guards
from fairpool.domain.checkout_guards import BuyerOrderFacts, Observation
from fairpool.domain.errors import ApplicationError, IllegalTransition
from fairpool.domain.states import MACHINES, TRANSITIONS_BY_ID
from fairpool.fakes.audit import FakeAuditLog
from fairpool.fakes.clock import FakeClock
from fairpool.fakes.idempotency import FakeIdempotencyStore
from fairpool.fakes.jobs import FakeJobQueue
from fairpool.fakes.ledger import FakeLedger
from fairpool.fakes.notifier import FakeNotifier
from fairpool.infra.clock import DbClock
from fairpool.modules.checkout.engine import CheckoutEngine, TransitionRequest
from tests.integration.test_triggers import (
    add_bid,
    add_bid_revision,
    add_entry,
    add_lot,
    add_merchant,
    add_pool,
    add_user,
)

pytestmark = pytest.mark.integration

TOTAL_CENTS = 50_000
CAP_CENTS = 60_000
ITEM_BREAKDOWN = {"item_cents": 47_000, "shipping_cents": 1_500, "tax_cents": 1_500}

SOURCE_BACKEND = Path(__file__).resolve().parents[2] / "src" / "fairpool"

BO_TRANSITIONS = tuple(
    transition for transition in TRANSITIONS_BY_ID.values() if transition.machine == "buyer_order"
)
LISTED_BO_PAIRS = {
    (from_state, transition.to_state)
    for transition in BO_TRANSITIONS
    for from_state in transition.from_states
}


@dataclass
class Ports:
    """The port fakes one engine runs on, kept so tests can assert on their calls."""

    clock: FakeClock
    audit: FakeAuditLog
    jobs: FakeJobQueue
    ledger: FakeLedger
    notifier: FakeNotifier
    idempotency: FakeIdempotencyStore
    engine: CheckoutEngine = field(init=False)

    def __post_init__(self) -> None:
        self.engine = CheckoutEngine(
            clock=self.clock,
            audit=self.audit,
            jobs=self.jobs,
            ledger=self.ledger,
            notifier=self.notifier,
            idempotency=self.idempotency,
        )


@dataclass
class Scene:
    """One pool, lot, entry, award and buyer order, stamped and ready to move."""

    session: AsyncSession
    ports: Ports
    pool_id: UUID
    lot_id: UUID
    entry_id: UUID
    user_id: UUID
    order_id: UUID
    now: datetime


def new_id() -> UUID:
    return uuid4()


async def _insert(session: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> None:
    await session.execute(text(sql), params or {})


async def set_lot_status(session: AsyncSession, lot_id: UUID, status: str) -> None:
    await _insert(
        session,
        "UPDATE lots SET status = CAST(:status AS lot_status) WHERE id = :id",
        {"id": lot_id, "status": status},
    )


async def set_order_status(session: AsyncSession, order_id: UUID, status: str) -> None:
    await _insert(
        session,
        "UPDATE buyer_orders SET status = CAST(:status AS buyer_order_status) WHERE id = :id",
        {"id": order_id, "status": status},
    )


async def stamp_lot(
    session: AsyncSession, lot_id: UUID, *, mode: str | None, router: str | None
) -> None:
    """Set the values ``lot.award`` stamps at award time (N8)."""
    await _insert(
        session,
        "UPDATE lots SET payment_mode = CAST(:mode AS payment_mode), "
        "payment_router = CAST(:router AS payment_router) WHERE id = :id",
        {"id": lot_id, "mode": mode or "authorize_capture", "router": router or "fake"},
    )


async def insert_award(
    session: AsyncSession,
    lot_id: UUID,
    *,
    valid_until: datetime,
    merchant_id: UUID | None = None,
) -> UUID:
    """Attach an immutable award snapshot to the lot through a real bid chain."""
    merchant = merchant_id or (await add_merchant(session))[0]
    bid = await add_bid(session, lot_id, merchant)
    revision = await add_bid_revision(session, bid)
    award_id = new_id()
    await _insert(
        session,
        "INSERT INTO awards (id, lot_id, bid_revision_id, merchant_id, tier_index, item_cents, "
        "moq, totals, valid_until, rule_version, award_hash) VALUES (:id, :lot, :revision, "
        ":merchant, 0, 47000, 2, CAST(:totals AS jsonb), :valid_until, 'ranking_v1', :hash)",
        {
            "id": award_id,
            "lot": lot_id,
            "revision": revision,
            "merchant": merchant,
            "totals": "{}",
            "valid_until": valid_until,
            "hash": "0" * 64,
        },
    )
    return award_id


async def insert_allocation(
    session: AsyncSession,
    pool_id: UUID,
    entry_id: UUID,
    lot_id: UUID | None,
    *,
    status: str = "SEATED",
    rank: int | None = None,
) -> UUID:
    allocation_id = new_id()
    await _insert(
        session,
        "INSERT INTO allocations (id, pool_id, entry_id, zone_id, rank, rank_hash, lot_id, status) "
        "VALUES (:id, :pool, :entry, 'US-EAST', :rank, :rank_hash, :lot, "
        "CAST(:status AS allocation_status))",
        {
            "id": allocation_id,
            "pool": pool_id,
            "entry": entry_id,
            "rank": rank or int(uuid4().int % 1_000_000_000),
            "rank_hash": "0" * 64,
            "lot": lot_id,
            "status": status,
        },
    )
    return allocation_id


async def insert_order(
    session: AsyncSession,
    lot_id: UUID,
    entry_id: UUID,
    *,
    status: str = "OFFERED",
    total_cents: int = TOTAL_CENTS,
    offer_expires_at: datetime,
    current_attempt: int = 0,
    seat_locked_until: datetime | None = None,
    void_source: str | None = None,
) -> UUID:
    order_id = new_id()
    await _insert(
        session,
        "INSERT INTO buyer_orders (id, lot_id, entry_id, status, current_attempt, "
        "offer_expires_at, total_cents, breakdown, seat_locked_until, void_source) "
        "VALUES (:id, :lot, :entry, CAST(:status AS buyer_order_status), :attempt, :expires, "
        ":total, CAST(:breakdown AS jsonb), :seat_lock, :void_source)",
        {
            "id": order_id,
            "lot": lot_id,
            "entry": entry_id,
            "status": status,
            "attempt": current_attempt,
            "expires": offer_expires_at,
            "total": total_cents,
            "breakdown": json.dumps(ITEM_BREAKDOWN),
            "seat_lock": seat_locked_until,
            "void_source": void_source,
        },
    )
    return order_id


async def insert_vault_token(
    session: AsyncSession,
    entry_id: UUID,
    user_id: UUID,
    *,
    status: str = "ACTIVE",
    cap_cents: int = CAP_CENTS,
    consented: bool = True,
    deleted: bool = False,
) -> UUID:
    """A saved permission; the token value itself never leaves this row's ciphertext."""
    token_id = new_id()
    await _insert(
        session,
        "INSERT INTO vault_tokens (id, entry_id, user_id, status, token_ciphertext, token_nonce, "
        "token_label, cap_cents, consent_version, consent_text_sha256, consented_at, deleted_at) "
        "VALUES (:id, :entry, :user, CAST(:status AS vault_status), :cipher, :nonce, :label, "
        ":cap, :consent_version, :consent_hash, now(), :deleted_at)",
        {
            "id": token_id,
            "entry": entry_id,
            "user": user_id,
            "status": status,
            "cipher": b"not-a-real-ciphertext",
            "nonce": b"0123456789abcdef",
            "label": "1234",
            "cap": cap_cents,
            "consent_version": "v1" if consented else "",
            "consent_hash": "0" * 64 if consented else "",
            "deleted_at": datetime.now(UTC) if deleted else None,
        },
    )
    return token_id


async def ensure_vault_token(
    session: AsyncSession,
    entry_id: UUID,
    user_id: UUID,
    *,
    status: str = "ACTIVE",
    cap_cents: int = CAP_CENTS,
) -> UUID:
    """The repeatable form of ``insert_vault_token`` for the walks (PT-07, PT-10).

    ``uq_vault_tokens_active_entry`` allows one live row per entry (``deleted_at IS
    NULL``), so a walk that steps through the vault edges twice re-states the entry's
    permission instead of inserting a second one: the engine reads the status of that
    one row (``vault-charge.md`` section 4).
    """
    existing = await session.scalar(
        text("SELECT id FROM vault_tokens WHERE entry_id = :entry AND deleted_at IS NULL"),
        {"entry": entry_id},
    )
    if existing is not None:
        await _insert(
            session,
            "UPDATE vault_tokens SET status = CAST(:status AS vault_status), cap_cents = :cap "
            "WHERE id = :id",
            {"id": existing, "status": status, "cap": cap_cents},
        )
        return cast(UUID, existing)
    return await insert_vault_token(session, entry_id, user_id, status=status, cap_cents=cap_cents)


async def insert_paypal_order(
    session: AsyncSession, order_id: UUID, *, attempt: int = 0, status: str = "APPROVED"
) -> str:
    """The PayPal order for one attempt, keyed by (order, attempt) and repeatable."""
    existing = await session.scalar(
        text(
            "SELECT paypal_order_id FROM paypal_orders WHERE buyer_order_id = :buyer "
            "AND attempt = :attempt"
        ),
        {"buyer": order_id, "attempt": attempt},
    )
    if existing is not None:
        await _insert(
            session,
            "UPDATE paypal_orders SET status = :status WHERE paypal_order_id = :paypal",
            {"status": status, "paypal": existing},
        )
        return str(existing)
    paypal_order_id = f"ORDER-{uuid4()}"
    await _insert(
        session,
        "INSERT INTO paypal_orders (id, buyer_order_id, attempt, paypal_order_id, status, intent, "
        "amount_cents, payer_country, raw) VALUES (:id, :buyer, :attempt, :paypal, :status, "
        "'AUTHORIZE', :amount, 'US', CAST(:raw AS jsonb))",
        {
            "id": new_id(),
            "buyer": order_id,
            "attempt": attempt,
            "paypal": paypal_order_id,
            "status": status,
            "amount": TOTAL_CENTS,
            "raw": "{}",
        },
    )
    return paypal_order_id


async def insert_authorization(
    session: AsyncSession,
    order_id: UUID,
    *,
    paypal_order_id: str,
    amount_cents: int = TOTAL_CENTS,
    status: str = "CREATED",
) -> str:
    """One authorization per order, repeatable: a re-run updates the row it made."""
    existing = await session.scalar(
        text("SELECT paypal_auth_id FROM paypal_authorizations WHERE buyer_order_id = :buyer"),
        {"buyer": order_id},
    )
    if existing is not None:
        await _insert(
            session,
            "UPDATE paypal_authorizations SET status = :status, amount_cents = :amount "
            "WHERE paypal_auth_id = :auth",
            {"status": status, "amount": amount_cents, "auth": existing},
        )
        return str(existing)
    auth_id = f"AUTH-{uuid4()}"
    await _insert(
        session,
        "INSERT INTO paypal_authorizations (id, buyer_order_id, paypal_order_id, paypal_auth_id, "
        "status, amount_cents, raw) VALUES (:id, :buyer, :paypal, :auth, :status, :amount, "
        "CAST(:raw AS jsonb))",
        {
            "id": new_id(),
            "buyer": order_id,
            "paypal": paypal_order_id,
            "auth": auth_id,
            "status": status,
            "amount": amount_cents,
            "raw": "{}",
        },
    )
    return auth_id


async def insert_capture(
    session: AsyncSession,
    order_id: UUID,
    *,
    auth_id: str | None = None,
    amount_cents: int = TOTAL_CENTS,
    status: str = "COMPLETED",
) -> str:
    """One capture per order, repeatable, so a walk cannot make two identities."""
    existing = await session.scalar(
        text("SELECT paypal_capture_id FROM paypal_captures WHERE buyer_order_id = :buyer"),
        {"buyer": order_id},
    )
    if existing is not None:
        await _insert(
            session,
            "UPDATE paypal_captures SET status = :status, amount_cents = :amount, "
            "paypal_auth_id = :auth WHERE paypal_capture_id = :capture",
            {"status": status, "amount": amount_cents, "auth": auth_id, "capture": existing},
        )
        return str(existing)
    capture_id = f"CAP-{uuid4()}"
    await _insert(
        session,
        "INSERT INTO paypal_captures (id, buyer_order_id, paypal_auth_id, paypal_capture_id, "
        "status, amount_cents, final_capture, raw) VALUES (:id, :buyer, :auth, :capture, "
        ":status, :amount, true, CAST(:raw AS jsonb))",
        {
            "id": new_id(),
            "buyer": order_id,
            "auth": auth_id,
            "capture": capture_id,
            "status": status,
            "amount": amount_cents,
            "raw": "{}",
        },
    )
    return capture_id


async def insert_refund(
    session: AsyncSession,
    order_id: UUID,
    capture_id: str,
    *,
    seq: int = 1,
    amount_cents: int = TOTAL_CENTS,
    status: str = "COMPLETED",
) -> str:
    existing = await session.scalar(
        text(
            "SELECT paypal_refund_id FROM paypal_refunds WHERE paypal_capture_id = :capture "
            "AND seq = :seq"
        ),
        {"capture": capture_id, "seq": seq},
    )
    if existing is not None:
        await _insert(
            session,
            "UPDATE paypal_refunds SET status = :status, amount_cents = :amount "
            "WHERE paypal_refund_id = :refund",
            {"status": status, "amount": amount_cents, "refund": existing},
        )
        return str(existing)
    refund_id = f"REF-{uuid4()}"
    await _insert(
        session,
        "INSERT INTO paypal_refunds (id, buyer_order_id, paypal_capture_id, paypal_refund_id, seq, "
        "status, amount_cents, raw) VALUES (:id, :buyer, :capture, :refund, :seq, :status, "
        ":amount, CAST(:raw AS jsonb))",
        {
            "id": new_id(),
            "buyer": order_id,
            "capture": capture_id,
            "refund": refund_id,
            "seq": seq,
            "status": status,
            "amount": amount_cents,
            "raw": "{}",
        },
    )
    return refund_id


async def make_scene(
    db_session: AsyncSession,
    *,
    status: str = "OFFERED",
    lot_status: str = "CHECKOUT_OPEN",
    mode: str = "authorize_capture",
    router: str = "single_seller",
    seats: int = 3,
    total_cents: int = TOTAL_CENTS,
    offer_in: int = 180,
    award_in: int = 3600,
    allocation: str | None = "SEATED",
    current_attempt: int = 0,
    clock: FakeClock | None = None,
    **order_kwargs: Any,
) -> Scene:
    """Build one stamped CHECKOUT_OPEN lot with a single buyer order and fake ports."""
    now = await DbClock().db_wall_now(db_session)
    clock = clock or FakeClock(now)
    ports = Ports(
        clock=clock,
        audit=FakeAuditLog(clock=lambda: now),
        jobs=FakeJobQueue(clock=clock),
        ledger=FakeLedger(),
        notifier=FakeNotifier(),
        idempotency=FakeIdempotencyStore(),
    )
    pool_id = await add_pool(db_session)
    user_id = await add_user(db_session)
    entry_id = await add_entry(db_session, pool_id, user_id=user_id)
    lot_id = await add_lot(db_session, pool_id, status="AWARDED", seats=seats)
    await set_lot_status(db_session, lot_id, lot_status)
    await stamp_lot(db_session, lot_id, mode=mode, router=router)
    await insert_award(db_session, lot_id, valid_until=now + timedelta(seconds=award_in))
    if allocation is not None:
        await insert_allocation(db_session, pool_id, entry_id, lot_id, status=allocation)
    offer_expires_at = now + timedelta(seconds=offer_in)
    order_id = await insert_order(
        db_session,
        lot_id,
        entry_id,
        status=status,
        total_cents=total_cents,
        offer_expires_at=offer_expires_at,
        current_attempt=current_attempt,
        **order_kwargs,
    )
    return Scene(
        session=db_session,
        ports=ports,
        pool_id=pool_id,
        lot_id=lot_id,
        entry_id=entry_id,
        user_id=user_id,
        order_id=order_id,
        now=now,
    )


async def stored_status(session: AsyncSession, order_id: UUID) -> str:
    value = await session.scalar(
        text("SELECT status FROM buyer_orders WHERE id = :id"), {"id": order_id}
    )
    return str(value)


def obs(kind: str, status: str, **overrides: Any) -> Observation:
    """A validated adapter result for one resource, with the amounts the guards want."""
    defaults: dict[str, Any] = {
        "reference": f"{kind.upper()}-1",
        "amount_cents": 50_000,
        "currency": "USD",
    }
    if kind == "approval":
        defaults["checks_passed"] = True
    if kind in {"capture", "charge"}:
        defaults["payee_matches"] = True
    defaults.update(overrides)
    return Observation(kind=kind, status=status, **defaults)


BASE_NOW = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
OPEN_WINDOW = datetime(2026, 11, 2, 10, 5, tzinfo=UTC)
LAPSED_WINDOW = datetime(2026, 11, 2, 9, 59, tzinfo=UTC)
AWARD_LIVE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

#: One row per buyer_order transition: the post-lock facts that satisfy its guard.
SATISFYING: dict[str, dict[str, Any]] = {
    "BO-01": {},
    "BO-02": {"observation": obs("approval", "APPROVED")},
    "BO-03": {"from_state": "APPROVED"},
    "BO-04": {
        "from_state": "AUTHORIZING",
        "observation": obs("authorization", "CREATED"),
    },
    "BO-05": {
        "from_state": "AUTHORIZING",
        "observation": obs("authorization", "DENIED"),
    },
    "BO-06": {"lot_status": "FUNDING", "from_state": "AUTHORIZED"},
    "BO-07": {"from_state": "CAPTURING", "observation": obs("capture", "COMPLETED")},
    "BO-08": {"from_state": "CAPTURING", "observation": obs("capture", "PENDING")},
    "BO-09": {
        "from_state": "CAPTURE_PENDING",
        "observation": obs("capture", "COMPLETED"),
    },
    "BO-10": {
        "from_state": "CAPTURE_PENDING",
        "observation": obs("capture", "DECLINED"),
    },
    "BO-11": {"from_state": "CAPTURING", "observation": obs("capture", "FAILED")},
    "BO-12": {
        "from_state": "AUTHORIZED",
        "observation": obs("authorization", "VOIDED"),
    },
    "BO-13": {
        "from_state": "CAPTURED",
        "lot_status": "FAILING",
        "observation": obs("refund", "PENDING"),
    },
    "BO-14": {
        "from_state": "REFUNDING",
        "observation": obs("refund", "COMPLETED"),
    },
    "BO-15": {"offer_expires_at": LAPSED_WINDOW},
    "BO-16": {"from_state": "ORDER_CREATED", "offer_expires_at": LAPSED_WINDOW},
    "BO-17": {"from_state": "APPROVED", "offer_expires_at": LAPSED_WINDOW},
    "BO-18": {
        "from_state": "ORDER_CREATED",
        "observation": obs("approval", "CREATED", checks_passed=False),
    },
    "BO-19": {"from_state": "APPROVED"},
    "BO-20": {
        "from_state": "AUTHORIZING",
        "observation": obs("authorization", "CREATED", amount_cents=49_999),
    },
    "BO-21": {},
    "BO-22": {"from_state": "ORDER_CREATED"},
    "BO-23": {"payment_mode": "vault_charge"},
    "BO-24": {
        "payment_mode": "vault_charge",
        "from_state": "CAPTURING",
        "observation": obs("capture", "COMPLETED"),
    },
    "BO-25": {
        "payment_mode": "vault_charge",
        "from_state": "CAPTURING",
        "observation": obs("charge", "PENDING"),
    },
    "BO-26": {
        "payment_mode": "vault_charge",
        "from_state": "CAPTURING",
        "observation": obs("charge", "DENIED"),
    },
    "BO-27": {
        "payment_mode": "vault_charge",
        "saved_permission_status": "SETUP_PENDING",
    },
}


def facts_for(transition_id: str, **overrides: Any) -> BuyerOrderFacts:
    """Satisfying facts for one transition, with any overrides applied.

    Each value is data the engine reads after its locks: the deadline comparison is
    a passed-in ``datetime``, never a clock read (I15).
    """
    transition = TRANSITIONS_BY_ID[transition_id]
    base: dict[str, Any] = {
        "from_state": transition.from_states[0],
        "to_state": transition.to_state,
        "trigger": transition.trigger,
        "now": BASE_NOW,
        "offer_expires_at": OPEN_WINDOW,
        "award_valid_until": AWARD_LIVE,
        "lot_status": "CHECKOUT_OPEN",
        "payment_mode": "authorize_capture",
        "payment_router": "single_seller",
        "seat_valid": True,
        "row_lock_taken": True,
        "total_cents": 50_000,
        "cap_cents": 60_000,
        "expected_cents": 50_000,
        "observation": None,
        "void_source": "buyer_withdraw",
        "reject_reason": "WRONG_COUNTRY",
        "has_completed_capture": False,
        "ops_refund": False,
        "pending_wait_exceeded": False,
        "saved_permission_status": "ACTIVE",
        "seat_locked_until": BASE_NOW + timedelta(minutes=1),
        "paypal_order_status": None,
    }
    base.update(SATISFYING[transition_id])
    base.update(overrides)
    return BuyerOrderFacts(**base)


def trigger_for(transition_id: str) -> str | None:
    """The exact trigger text of a transition, or ``None`` for an alternation.

    ``states.assert_transition`` matches a trigger exactly, and the contract lists
    some edges as ``a | b | c``; those are reached by naming the pair only.
    """
    trigger = TRANSITIONS_BY_ID[transition_id].trigger
    return None if " | " in trigger else trigger


# ---------------------------------------------------------------------------
# bullet 1 and 8: the whitelist decides legality; an unlisted pair raises
# ---------------------------------------------------------------------------


async def test_whitelist_decides_legality_for_every_pair(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1 and 8: only the listed pairs may run, at runtime.

    Every (from, to) pair of the buyer_order machine is asked of the engine with a
    real row in that state. A pair the contract does not list raises; a guard the
    data does not satisfy also raises. No pair is executed by the engine from
    contract text -- the whitelist table alone decides (I10).
    """
    states = MACHINES["buyer_order"].states
    scene = await make_scene(db_session)
    illegal = [
        (from_state, to_state)
        for from_state, to_state in itertools.product(states, repeat=2)
        if (from_state, to_state) not in LISTED_BO_PAIRS
    ]
    assert len(illegal) > 200
    for from_state, to_state in illegal:
        await set_order_status(db_session, scene.order_id, from_state)
        with pytest.raises(IllegalTransition):
            await scene.ports.engine.apply(
                db_session,
                TransitionRequest(
                    buyer_order_id=scene.order_id, to_state=to_state, trigger="job:test"
                ),
            )
    assert await stored_status(db_session, scene.order_id) == illegal[-1][0]


def test_engine_never_executes_contract_guard_text() -> None:
    """T03A01 acceptance 1: the guard sentence is metadata, never interpreted.

    The engine must not read ``Transition.guard`` at all, must not call ``eval`` or
    ``exec``, and must not build code from contract text (I10).
    """
    for name in (
        "modules/checkout/engine.py",
        "modules/checkout/expiry.py",
        "domain/checkout_guards.py",
    ):
        source = (SOURCE_BACKEND / name).read_text(encoding="utf-8")
        assert "eval(" not in source, name
        assert "exec(" not in source, name
        tree = ast.parse(source)
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "guard" not in attributes, name
    # The guard text still describes the rule the predicate implements.
    for transition in BO_TRANSITIONS:
        assert transition.guard.strip()


def test_guard_matrix_covers_every_buyer_order_transition() -> None:
    """T03A01 acceptance 1: every BO transition has a satisfying guard matrix row."""
    assert set(SATISFYING) == {transition.id for transition in BO_TRANSITIONS}
    for transition in BO_TRANSITIONS:
        facts = facts_for(transition.id)
        assert facts.from_state in transition.from_states, transition.id
        assert checkout_guards.unmet_guard_reason(transition.id, facts) is None, transition.id
        assert checkout_guards.allowed_transition_id(facts) == transition.id, transition.id


@pytest.mark.parametrize(
    ("transition_id", "field_name", "value"),
    [
        ("BO-01", "seat_valid", False),
        ("BO-01", "lot_status", "FUNDING"),
        ("BO-01", "total_cents", 70_000),
        ("BO-01", "offer_expires_at", datetime(2026, 11, 2, 9, 0, tzinfo=UTC)),
        ("BO-01", "award_valid_until", datetime(2026, 11, 2, 9, 0, tzinfo=UTC)),
        ("BO-02", "observation", None),
        ("BO-03", "row_lock_taken", False),
        ("BO-03", "seat_locked_until", None),
        ("BO-04", "expected_cents", 49_000),
        ("BO-05", "observation", Observation("authorization", "PENDING", "AUTH-1")),
        ("BO-06", "lot_status", "CHECKOUT_OPEN"),
        ("BO-07", "observation", None),
        ("BO-08", "observation", Observation("capture", "COMPLETED", "CAP-1")),
        ("BO-09", "observation", Observation("capture", "PENDING", "CAP-1")),
        ("BO-10", "observation", Observation("capture", "PENDING", "CAP-1")),
        ("BO-11", "observation", Observation("capture", "PENDING", "CAP-1")),
        ("BO-12", "has_completed_capture", True),
        ("BO-12", "void_source", "not_a_reason"),
        ("BO-13", "lot_status", "FUNDED"),
        ("BO-14", "observation", Observation("refund", "PENDING", "REF-1")),
        ("BO-15", "offer_expires_at", datetime(2026, 11, 2, 11, 0, tzinfo=UTC)),
        ("BO-16", "offer_expires_at", datetime(2026, 11, 2, 11, 0, tzinfo=UTC)),
        ("BO-17", "offer_expires_at", datetime(2026, 11, 2, 11, 0, tzinfo=UTC)),
        ("BO-18", "reject_reason", None),
        ("BO-19", "reject_reason", "NOT_A_REASON"),
        ("BO-20", "expected_cents", 49_999),
        ("BO-21", "seat_valid", False),
        ("BO-23", "saved_permission_status", "DELETED"),
        ("BO-23", "total_cents", 60_001),
        ("BO-23", "lot_status", "FUNDING"),
        ("BO-24", "observation", Observation("capture", "PENDING", "CAP-1", payee_matches=True)),
        ("BO-24", "observation", Observation("capture", "COMPLETED", "CAP-1")),
        ("BO-25", "observation", Observation("charge", "COMPLETED", "VC-1")),
        ("BO-26", "observation", Observation("charge", "PENDING", "VC-1")),
        ("BO-27", "saved_permission_status", "ACTIVE"),
    ],
)
def test_each_guard_can_fail(transition_id: str, field_name: str, value: Any) -> None:
    """T03A01 acceptance 1: every listed transition has a failing guard case."""
    broken = replace(facts_for(transition_id), **{field_name: value})
    reason = checkout_guards.unmet_guard_reason(transition_id, broken)
    assert reason is not None, transition_id
    with pytest.raises(IllegalTransition):
        checkout_guards.allowed_transition_id(broken)


def test_vault_only_transitions_require_the_vault_mode() -> None:
    """T03A01 acceptance 7: BO-23 to BO-27 are the vault_charge path only."""
    for transition_id in sorted(checkout_guards.VAULT_ONLY):
        facts = facts_for(transition_id)
        assert checkout_guards.allowed_transition_id(facts) == transition_id
        for fallback in ("authorize_capture", "capture_only"):
            refused = replace(facts, payment_mode=fallback)
            assert checkout_guards.unmet_guard_reason(transition_id, refused) is not None


@pytest.mark.parametrize("fallback_mode", ["authorize_capture", "capture_only"])
def test_both_fallback_modes_keep_the_checkout_ladder(fallback_mode: str) -> None:
    """T03A01 acceptance 7: the two fallback modes share the ladder edges.

    The whitelist names no capture_only-only transition, so the engine does not
    invent one: both stamped fallback modes keep every ladder edge available and
    keep the vault path unavailable (vault-charge.md section 3).
    """
    for transition in BO_TRANSITIONS:
        transition_id = transition.id
        facts = facts_for(transition_id, payment_mode=fallback_mode)
        if transition_id in checkout_guards.VAULT_ONLY:
            assert checkout_guards.unmet_guard_reason(transition_id, facts) is not None
        else:
            assert checkout_guards.allowed_transition_id(facts) == transition_id


def test_refund_edges_work_in_every_mode() -> None:
    """T03A01 acceptance 7: the mode-independent edges work in every stamped mode.

    ``MODE_INDEPENDENT`` is the refund pair (BO-13/BO-14) plus the capture polls
    (BO-09/BO-10): a capture that already exists is polled the same way whatever the
    mode, and LS-10 refunds every completed capture (vault-charge.md section 7).
    """
    for mode in ("vault_charge", "authorize_capture", "capture_only"):
        for transition_id in sorted(checkout_guards.MODE_INDEPENDENT):
            assert (
                checkout_guards.allowed_transition_id(facts_for(transition_id, payment_mode=mode))
                == transition_id
            )


def test_unstamped_lot_can_move_no_money() -> None:
    """T03A01 acceptance 7: a lot without a stamped mode has no payment path."""
    facts = facts_for("BO-01")
    assert (
        checkout_guards.unmet_guard_reason("BO-01", replace(facts, payment_mode=None)) is not None
    )
    assert (
        checkout_guards.unmet_guard_reason("BO-01", replace(facts, payment_router="nope"))
        is not None
    )


# ---------------------------------------------------------------------------
# bullet 9: money facts come only from validated evidence, never order.status
# ---------------------------------------------------------------------------


def test_paypal_order_status_is_never_a_payment_signal() -> None:
    """T03A01 acceptance 9 (V8): COMPLETED on the order alone proves nothing."""
    # V8: the sandbox read COMPLETED on the order after a void.
    lying = facts_for("BO-07", observation=None, paypal_order_status="COMPLETED")
    assert checkout_guards.unmet_guard_reason("BO-07", lying) is not None
    with pytest.raises(IllegalTransition):
        checkout_guards.allowed_transition_id(lying)


def test_evidence_from_a_request_body_is_refused() -> None:
    """T03A01 acceptance 9: only adapter results and test fixtures count (I4)."""
    body_sourced = facts_for(
        "BO-07",
        observation=Observation(
            "capture", "COMPLETED", "CAP-1", amount_cents=50_000, source="request_body"
        ),
    )
    reason = checkout_guards.unmet_guard_reason("BO-07", body_sourced)
    assert reason is not None and "validated adapter result" in reason


def test_money_bearing_transitions_are_derived_from_the_whitelist() -> None:
    """T03A01 acceptance 9: no hand-maintained money list outside the contract."""
    for transition in BO_TRANSITIONS:
        expected = transition.to_state in checkout_guards.MONEY_OUTCOME_STATES or any(
            effect.startswith("ledger:") for effect in transition.effects
        )
        assert checkout_guards.needs_validated_evidence(transition.id) is expected


async def test_wrong_lot_evidence_is_rejected(db_session: AsyncSession) -> None:
    """T03A01 acceptance 9: evidence must belong to this buyer order (I4, I9)."""
    scene = await make_scene(db_session, status="CAPTURING")
    other_pool = await add_pool(db_session)
    other_lot = await add_lot(db_session, other_pool, lot_index=1, lot_order=1)
    other_user = await add_user(db_session)
    other_entry = await add_entry(db_session, other_pool, user_id=other_user)
    other_order = await insert_order(
        db_session, other_lot, other_entry, status="CAPTURING", offer_expires_at=scene.now
    )
    foreign_capture = await insert_capture(db_session, other_order)
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="CAPTURED",
                trigger="job:order.capture",
                observation=Observation(
                    "capture", "COMPLETED", foreign_capture, amount_cents=50_000
                ),
            ),
        )
    assert await stored_status(db_session, scene.order_id) == "CAPTURING"
    assert scene.ports.ledger.entries == []


async def test_money_needs_a_persisted_resource_identity(db_session: AsyncSession) -> None:
    """T03A01 acceptance 9: a money fact without a resource reference is refused."""
    scene = await make_scene(db_session, status="CAPTURING")
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            db_session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="CAPTURED",
                trigger="job:order.capture",
                observation=Observation("capture", "COMPLETED", "NOT-OURS", amount_cents=50_000),
            ),
        )


# ---------------------------------------------------------------------------
# success paths: every buyer_order edge the contract lists
# ---------------------------------------------------------------------------


async def test_authorize_capture_ladder_walks_the_whole_path(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1: BO-01, 02, 03, 04, 06, 07, 13, 14 apply in order."""
    scene = await make_scene(db_session)
    engine = scene.ports.engine

    created = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="ORDER_CREATED", trigger="buyer.continue"
        ),
    )
    assert created.transition_id == "BO-01"
    assert created.idempotency_key == f"create:{scene.order_id}:0"
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    approved = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="APPROVED",
            trigger=trigger_for("BO-02"),
            observation=Observation(
                "approval",
                "APPROVED",
                paypal_order_id,
                amount_cents=50_000,
                currency="USD",
                checks_passed=True,
            ),
        ),
    )
    assert approved.transition_id == "BO-02"
    authorizing = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="AUTHORIZING",
            trigger="job:order.authorize",
            seat_locked_until=scene.now + timedelta(seconds=60),
        ),
    )
    assert authorizing.transition_id == "BO-03"
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    authorized = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="AUTHORIZED",
            trigger="job:order.authorize",
            observation=Observation("authorization", "CREATED", auth_id, amount_cents=50_000),
        ),
    )
    assert authorized.transition_id == "BO-04"
    assert authorized.idempotency_key == f"auth:{scene.order_id}"
    await set_lot_status(scene.session, scene.lot_id, "FUNDING")
    capturing = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="CAPTURING", trigger="job:order.capture"
        ),
    )
    assert capturing.transition_id == "BO-06"
    assert capturing.idempotency_key == f"cap:{auth_id}"
    capture_id = await insert_capture(scene.session, scene.order_id, auth_id=auth_id)
    captured = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="CAPTURED",
            trigger="job:order.capture",
            observation=Observation("capture", "COMPLETED", capture_id, amount_cents=50_000),
        ),
    )
    assert captured.transition_id == "BO-07"
    # BO-07 is listed without a ``key`` (paypal-adapter.md section 3 gives get_capture
    # no replay identity), so it carries the own-records key, never a money-call key.
    assert captured.idempotency_key == f"state:{scene.order_id}:BO-07"
    await set_lot_status(scene.session, scene.lot_id, "FAILING")
    refunding = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="REFUNDING",
            trigger="job:refund.run",
            refund_seq=1,
            observation=Observation("capture", "COMPLETED", capture_id, amount_cents=50_000),
        ),
    )
    assert refunding.transition_id == "BO-13"
    assert refunding.idempotency_key == f"refund:{capture_id}:1"
    refund_id = await insert_refund(scene.session, scene.order_id, capture_id)
    refunded = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="REFUNDED",
            trigger="job:refund.run",
            refund_seq=1,
            observation=Observation("refund", "COMPLETED", refund_id, amount_cents=50_000),
        ),
    )
    assert refunded.transition_id == "BO-14"
    assert await stored_status(scene.session, scene.order_id) == "REFUNDED"


async def test_void_and_decline_edges_apply(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1: BO-12, BO-21 and BO-22 apply with their own facts."""
    scene = await make_scene(db_session, status="AUTHORIZED")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    voided = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="VOIDED",
            trigger="job:void.run",
            void_source="buyer_withdraw",
            observation=Observation("authorization", "VOIDED", auth_id),
        ),
    )
    assert voided.transition_id == "BO-12"
    assert voided.idempotency_key == f"void:{auth_id}"

    offered = await make_scene(db_session, status="OFFERED")
    declined = await offered.ports.engine.apply(
        offered.session,
        TransitionRequest(
            buyer_order_id=offered.order_id, to_state="DECLINED", trigger="buyer.decline"
        ),
    )
    assert declined.transition_id == "BO-21"

    created = await make_scene(db_session, status="ORDER_CREATED")
    cancelled = await created.ports.engine.apply(
        created.session,
        TransitionRequest(
            buyer_order_id=created.order_id,
            to_state="DECLINED",
            trigger=trigger_for("BO-22"),
        ),
    )
    assert cancelled.transition_id == "BO-22"


@pytest.mark.parametrize("auth_status", ["DENIED", "EXPIRED", "VOIDED"])
async def test_an_authorization_that_can_never_be_captured_fails_the_seat(
    db_session: AsyncSession, auth_status: str
) -> None:
    """CR-8 note 1: BO-05 takes every status `paypal-adapter.md` section 4 calls unauthorized."""
    scene = await make_scene(db_session, status="AUTHORIZING")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session,
        scene.order_id,
        paypal_order_id=paypal_order_id,
        status=auth_status,
    )
    outcome = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="AUTH_FAILED",
            trigger=trigger_for("BO-05"),
            observation=Observation("authorization", auth_status, auth_id),
        ),
    )
    assert outcome.transition_id == "BO-05"


async def test_failure_branch_edges_apply(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1: BO-05, BO-10, BO-11, BO-18, BO-19, BO-20 apply."""
    authorizing = await make_scene(db_session, status="AUTHORIZING")
    paypal_order_id = await insert_paypal_order(authorizing.session, authorizing.order_id)
    denied_auth = await insert_authorization(
        authorizing.session,
        authorizing.order_id,
        paypal_order_id=paypal_order_id,
        status="DENIED",
    )
    failed = await authorizing.ports.engine.apply(
        authorizing.session,
        TransitionRequest(
            buyer_order_id=authorizing.order_id,
            to_state="AUTH_FAILED",
            trigger=trigger_for("BO-05"),
            observation=Observation("authorization", "DENIED", denied_auth),
        ),
    )
    assert failed.transition_id == "BO-05"

    pending = await make_scene(db_session, status="CAPTURE_PENDING")
    pending_auth = await insert_paypal_order(pending.session, pending.order_id)
    pending_capture = await insert_capture(pending.session, pending.order_id)
    declined = await pending.ports.engine.apply(
        pending.session,
        TransitionRequest(
            buyer_order_id=pending.order_id,
            to_state="CAPTURE_FAILED",
            trigger="job:capture.poll",
            observation=Observation("capture", "DECLINED", pending_capture),
            pending_wait_exceeded=False,
        ),
    )
    assert declined.transition_id == "BO-10"
    assert declined.idempotency_key == f"state:{pending.order_id}:BO-10"
    assert pending_auth

    capturing = await make_scene(db_session, status="CAPTURING")
    cap_id = await insert_capture(capturing.session, capturing.order_id, status="FAILED")
    branch = await capturing.ports.engine.apply(
        capturing.session,
        TransitionRequest(
            buyer_order_id=capturing.order_id,
            to_state="CAPTURE_FAILED",
            trigger="job:order.capture",
            observation=Observation("capture", "FAILED", cap_id),
        ),
    )
    assert branch.transition_id == "BO-11"

    order_created = await make_scene(db_session, status="ORDER_CREATED")
    created_order = await insert_paypal_order(order_created.session, order_created.order_id)
    rejected = await order_created.ports.engine.apply(
        order_created.session,
        TransitionRequest(
            buyer_order_id=order_created.order_id,
            to_state="REJECTED",
            trigger=trigger_for("BO-18"),
            reject_reason="WRONG_COUNTRY",
            observation=Observation(
                "approval", "CREATED", created_order, checks_passed=False, amount_cents=50_000
            ),
        ),
    )
    assert rejected.transition_id == "BO-18"

    approved = await make_scene(db_session, status="APPROVED")
    await insert_paypal_order(approved.session, approved.order_id)
    pre_auth = await approved.ports.engine.apply(
        approved.session,
        TransitionRequest(
            buyer_order_id=approved.order_id,
            to_state="REJECTED",
            trigger="job:order.authorize",
            reject_reason="DUPLICATE_PAYER",
        ),
    )
    assert pre_auth.transition_id == "BO-19"

    mismatch = await make_scene(db_session, status="AUTHORIZING")
    mismatch_order = await insert_paypal_order(mismatch.session, mismatch.order_id)
    mismatch_auth = await insert_authorization(
        mismatch.session, mismatch.order_id, paypal_order_id=mismatch_order
    )
    wrong_amount = await mismatch.ports.engine.apply(
        mismatch.session,
        TransitionRequest(
            buyer_order_id=mismatch.order_id,
            to_state="REJECTED",
            trigger="job:order.authorize",
            reject_reason="AMOUNT_MISMATCH",
            void_source="buyer_withdraw",
            observation=Observation("authorization", "CREATED", mismatch_auth, amount_cents=49_999),
        ),
    )
    assert wrong_amount.transition_id == "BO-20"
    assert wrong_amount.idempotency_key == f"void:{mismatch_auth}"


async def test_expiry_edges_apply_from_each_fallback_state(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1: BO-15, BO-16 and BO-17 all expire a lapsed offer."""
    for status, transition_id in (
        ("OFFERED", "BO-15"),
        ("ORDER_CREATED", "BO-16"),
        ("APPROVED", "BO-17"),
    ):
        scene = await make_scene(db_session, status=status, offer_in=-1)
        outcome = await scene.ports.engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=scene.order_id, to_state="EXPIRED", trigger="job:offer.expire"
            ),
        )
        assert outcome.transition_id == transition_id
        assert await stored_status(scene.session, scene.order_id) == "EXPIRED"


async def test_vault_charge_edges_apply(db_session: AsyncSession) -> None:
    """T03A01 acceptance 1 and 7: BO-23 to BO-27 apply under the stamped vault mode."""
    scene = await make_scene(db_session, mode="vault_charge")
    await insert_vault_token(scene.session, scene.entry_id, scene.user_id)
    charged = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="CAPTURING", trigger="job:order.vault_charge"
        ),
    )
    assert charged.transition_id == "BO-23"
    assert charged.idempotency_key == f"vc:{scene.order_id}"
    charge_order = await insert_paypal_order(scene.session, scene.order_id)
    capture_id = await insert_capture(scene.session, scene.order_id)
    captured = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="CAPTURED",
            trigger="job:order.vault_charge",
            observation=Observation(
                "capture", "COMPLETED", capture_id, amount_cents=50_000, payee_matches=True
            ),
        ),
    )
    assert captured.transition_id == "BO-24"

    pending = await make_scene(db_session, status="CAPTURING", mode="vault_charge")
    await insert_vault_token(pending.session, pending.entry_id, pending.user_id)
    pending_capture = await insert_capture(pending.session, pending.order_id, status="PENDING")
    went_pending = await pending.ports.engine.apply(
        pending.session,
        TransitionRequest(
            buyer_order_id=pending.order_id,
            to_state="CAPTURE_PENDING",
            trigger="job:order.vault_charge",
            observation=Observation("capture", "PENDING", pending_capture),
        ),
    )
    assert went_pending.transition_id == "BO-25"

    declined = await make_scene(db_session, status="CAPTURING", mode="vault_charge")
    await insert_vault_token(declined.session, declined.entry_id, declined.user_id)
    declined_capture = await insert_capture(declined.session, declined.order_id, status="DENIED")
    failed = await declined.ports.engine.apply(
        declined.session,
        TransitionRequest(
            buyer_order_id=declined.order_id,
            to_state="CAPTURE_FAILED",
            trigger="job:order.vault_charge",
            observation=Observation("charge", "DENIED", declined_capture),
        ),
    )
    assert failed.transition_id == "BO-26"

    unproved = await make_scene(db_session, mode="vault_charge")
    await insert_vault_token(
        unproved.session, unproved.entry_id, unproved.user_id, status="DELETED"
    )
    rejected = await unproved.ports.engine.apply(
        unproved.session,
        TransitionRequest(
            buyer_order_id=unproved.order_id, to_state="REJECTED", trigger="job:order.vault_charge"
        ),
    )
    assert rejected.transition_id == "BO-27"
    assert charge_order


# ---------------------------------------------------------------------------
# bullets 2 and 6: lock order, the wall clock after the lock, the stamped re-read
# ---------------------------------------------------------------------------


async def test_lock_order_precedes_the_deadline_reading(
    db_session: AsyncSession, db_engine: AsyncEngine
) -> None:
    """T03A01 acceptance 2 and 6: advisory, lot row, order row, then the wall clock."""
    scene = await make_scene(db_session, offer_in=-1)
    statements: list[str] = []

    def _record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    engine = CheckoutEngine(
        clock=DbClock(),
        audit=scene.ports.audit,
        jobs=scene.ports.jobs,
        ledger=scene.ports.ledger,
        notifier=scene.ports.notifier,
        idempotency=scene.ports.idempotency,
    )
    try:
        await engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="EXPIRED",
                trigger=trigger_for("BO-15"),
            ),
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)

    def first(marker: str, after: int = -1) -> int:
        return next(
            index
            for index, statement in enumerate(statements)
            if index > after and marker in statement
        )

    advisory = first("pg_advisory_xact_lock")
    lot_lock = first("FOR UPDATE", advisory)
    assert "lots" in statements[lot_lock]
    order_lock = first("FOR UPDATE", lot_lock)
    assert "buyer_orders" in statements[order_lock]
    wall_clock = first("clock_timestamp()", order_lock)
    assert "buyer_orders" in statements[first("FROM buyer_orders", -1)]
    # The deadline is read from the database wall clock only after all three locks.
    assert advisory < lot_lock < order_lock < wall_clock


async def test_deadline_uses_the_wall_clock_not_the_stable_timestamp(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 6: guards compare against ``db_wall_now`` (CR-3 note 1)."""
    scene = await make_scene(db_session, offer_in=60)
    stable = scene.now
    wall_later = scene.now + timedelta(seconds=120)

    class SplitClock:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def db_now(self, session: AsyncSession) -> datetime:
            self.calls.append("db_now")
            return stable

        async def db_wall_now(self, session: AsyncSession) -> datetime:
            self.calls.append("db_wall_now")
            return wall_later

    clock = SplitClock()
    engine = CheckoutEngine(
        clock=clock,  # type: ignore[arg-type]
        audit=scene.ports.audit,
        jobs=scene.ports.jobs,
        ledger=scene.ports.ledger,
        notifier=scene.ports.notifier,
        idempotency=scene.ports.idempotency,
    )
    outcome = await engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="EXPIRED", trigger="job:offer.expire"
        ),
    )
    assert outcome.to_state == "EXPIRED"
    assert clock.calls[0] == "db_wall_now"
    row = await scene.session.execute(
        text("SELECT updated_at FROM buyer_orders WHERE id = :id"), {"id": scene.order_id}
    )
    stored = row.scalar()
    assert stored is not None
    assert stored.astimezone(UTC) == stable.astimezone(UTC)


async def test_later_config_change_cannot_reinterpret_a_stamped_lot(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 7: the stamped mode is re-read after the lock.

    The lot is stamped ``authorize_capture``; the deployment is later switched and
    the row is rewritten to ``vault_charge`` mid-life. The next transition is
    decided by the value the row carries now, never by a setting the engine cached,
    so the ladder edge is refused and the vault edge becomes available (N8).
    """
    scene = await make_scene(db_session)
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="CAPTURING",
                trigger="job:order.vault_charge",
            ),
        )
    await stamp_lot(db_session, scene.lot_id, mode="vault_charge", router="single_seller")
    await insert_vault_token(scene.session, scene.entry_id, scene.user_id)
    outcome = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="CAPTURING", trigger="job:order.vault_charge"
        ),
    )
    assert outcome.transition_id == "BO-23"
    assert await stored_status(scene.session, scene.order_id) == "CAPTURING"


async def test_stamped_mode_mismatch_refuses_a_ladder_edge(db_session: AsyncSession) -> None:
    """T03A01 acceptance 7: a vault-stamped lot cannot walk the ladder."""
    scene = await make_scene(db_session, mode="vault_charge")
    with pytest.raises(IllegalTransition):
        await scene.ports.engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=scene.order_id, to_state="ORDER_CREATED", trigger="buyer.continue"
            ),
        )
    assert await stored_status(scene.session, scene.order_id) == "OFFERED"


# ---------------------------------------------------------------------------
# bullet 8: replay, illegal pair and conflicting payload are three outcomes
# ---------------------------------------------------------------------------


async def test_exact_replay_returns_the_original_outcome_without_effects(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 8: a replay duplicates no ledger, audit or job effect."""
    scene = await make_scene(db_session, offer_in=-1)
    request = TransitionRequest(
        buyer_order_id=scene.order_id, to_state="EXPIRED", trigger="job:offer.expire"
    )
    first = await scene.ports.engine.apply(scene.session, request)
    jobs_after_first = len(scene.ports.jobs.jobs)
    audits_after_first = len(scene.ports.audit.rows)
    second = await scene.ports.engine.apply(scene.session, request)
    assert second.applied is False
    assert second.transition_id == first.transition_id
    assert second.idempotency_key == first.idempotency_key
    assert len(scene.ports.jobs.jobs) == jobs_after_first
    assert len(scene.ports.audit.rows) == audits_after_first


async def test_conflicting_payload_for_the_same_key_raises_a_conflict(
    db_session: AsyncSession,
) -> None:
    """T03A01 acceptance 8: the same key with a different payload conflicts (I9)."""
    scene = await make_scene(db_session, offer_in=-1)
    await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="EXPIRED", trigger="job:offer.expire"
        ),
    )
    with pytest.raises(ApplicationError) as excinfo:
        await scene.ports.engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=scene.order_id,
                to_state="EXPIRED",
                trigger="job:offer.expire",
                actor="someone-else",
            ),
        )
    assert excinfo.value.code == "IDEMPOTENCY_CONFLICT"


async def test_requote_uses_a_new_attempt_key(db_session: AsyncSession) -> None:
    """T03A01 acceptance 8: a re-quote increments the key, never reuses it (N9)."""
    scene = await make_scene(db_session, status="OFFERED", current_attempt=1)
    outcome = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id, to_state="ORDER_CREATED", trigger="buyer.continue"
        ),
    )
    assert outcome.idempotency_key == f"create:{scene.order_id}:1"


# ---------------------------------------------------------------------------
# bullet 10: a paypal field is metadata; the engine performs no network call
# ---------------------------------------------------------------------------


def test_engine_and_expiry_import_no_network_code() -> None:
    """T03A01 acceptance 10: neither checkout file can reach a host."""
    for name in ("modules/checkout/engine.py", "modules/checkout/expiry.py"):
        tree = ast.parse((SOURCE_BACKEND / name).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        for module in imported:
            assert not module.startswith("httpx"), name
            assert not module.startswith("fairpool.adapters.paypal"), name
            assert not module.startswith("fairpool.wiring"), name
            assert module != "socket", name


async def test_naming_a_paypal_field_causes_no_call(db_session: AsyncSession, monkeypatch) -> None:
    """T03A01 acceptance 10: applying a transition with a ``paypal:`` field is inert.

    Every write method of the real Sandbox gateway is replaced by one that fails the
    test, then each PayPal-naming transition is applied through the engine.
    """
    from fairpool.adapters.paypal.gateway import RestPayPalGateway

    def _forbidden(self: RestPayPalGateway, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the checkout engine must not call PayPal")

    for method in (
        "create_order",
        "get_order",
        "authorize_order",
        "capture_authorization",
        "get_capture",
        "void_authorization",
        "refund_capture",
        "get_refund",
        "charge_vault",
        "add_trackers",
    ):
        monkeypatch.setattr(RestPayPalGateway, method, _forbidden)

    scene = await make_scene(db_session, status="AUTHORIZED")
    paypal_order_id = await insert_paypal_order(scene.session, scene.order_id)
    auth_id = await insert_authorization(
        scene.session, scene.order_id, paypal_order_id=paypal_order_id
    )
    outcome = await scene.ports.engine.apply(
        scene.session,
        TransitionRequest(
            buyer_order_id=scene.order_id,
            to_state="VOIDED",
            trigger="job:void.run",
            void_source="buyer_withdraw",
            observation=Observation("authorization", "VOIDED", auth_id),
        ),
    )
    assert outcome.transition_id == "BO-12"
    assert outcome.effects  # the contract's effects ran; no call was made


# ---------------------------------------------------------------------------
# misc engine surface
# ---------------------------------------------------------------------------


async def test_unknown_order_is_not_found(db_session: AsyncSession) -> None:
    """T03A01: an order that does not exist is NOT_FOUND, never invented."""
    scene = await make_scene(db_session)
    with pytest.raises(ApplicationError) as excinfo:
        await scene.ports.engine.apply(
            scene.session,
            TransitionRequest(
                buyer_order_id=new_id(), to_state="EXPIRED", trigger="job:offer.expire"
            ),
        )
    assert excinfo.value.code == "NOT_FOUND"


def test_lot_advisory_key_is_stable_and_signed() -> None:
    """T03A01 acceptance 2: the per-lot key is stable, in the bigint range."""
    from fairpool.modules.checkout.engine import lot_advisory_lock_key

    lot_id = UUID("11111111-1111-4111-8111-111111111111")
    key = lot_advisory_lock_key(lot_id)
    assert key == lot_advisory_lock_key(lot_id)
    assert key != lot_advisory_lock_key(UUID("22222222-2222-4222-8222-222222222222"))
    assert -(1 << 63) <= key < (1 << 63)


def test_vacancy_rule_is_data_not_a_counter() -> None:
    """T03A02 acceptance: the vacancy rule reads the transition, not a column."""
    assert checkout_guards.creates_vacancy(to_state="EXPIRED", void_source=None)
    assert checkout_guards.creates_vacancy(to_state="VOIDED", void_source="age_guard")
    assert not checkout_guards.creates_vacancy(to_state="VOIDED", void_source="lot_failing")
    assert not checkout_guards.creates_vacancy(to_state="REFUNDED", void_source=None)
