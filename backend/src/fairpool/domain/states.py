"""Whitelisted state machines (I10).

Pure data: no file I/O. The tables below transcribe every transition in
``docs/contracts/state-machines.md``; ``tests/unit/test_state_machines_contract.py``
parses the YAML blocks and fails if the two ever differ, and also compares the
state lists with the ``db-schema.md`` enums.

Guards are stored as contract text; guard predicates are implemented by the
modules that run the transition, never here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .errors import IllegalTransition, UnknownMachine


@dataclass(frozen=True)
class Transition:
    id: str
    from_states: tuple[str, ...]
    to_state: str
    trigger: str
    guard: str
    effects: tuple[str, ...] = ()
    paypal: str | None = None
    key: str | None = None
    machine: str = ""


@dataclass(frozen=True)
class Machine:
    name: str
    initial: str
    states: tuple[str, ...]
    terminal: tuple[str, ...]
    transitions: tuple[Transition, ...]
    active: tuple[str, ...] = ()


def _machine(
    name: str,
    initial: str,
    states: tuple[str, ...],
    terminal: tuple[str, ...],
    transitions: tuple[Transition, ...],
    active: tuple[str, ...] = (),
) -> Machine:
    # Tag every transition with its machine name so TRANSITIONS_BY_ID is self-describing.
    return Machine(
        name=name,
        initial=initial,
        states=states,
        terminal=terminal,
        transitions=tuple(replace(transition, machine=name) for transition in transitions),
        active=active,
    )


POOL = _machine(
    "pool",
    "DRAFT",
    (
        "DRAFT",
        "PUBLISHED",
        "OPEN",
        "CLOSED",
        "SEEDED",
        "ALLOCATED",
        "RUNNING",
        "COMPLETED",
        "CANCELLED",
    ),
    ("COMPLETED", "CANCELLED"),
    (
        Transition(
            "PS-01",
            ("DRAFT",),
            "PUBLISHED",
            "admin.publish",
            "rules valid; lot_plan present; beacon round announced; timeline frozen",
            ("audit", "job:pool.open", "job:pool.close"),
        ),
        Transition(
            "PS-02",
            ("PUBLISHED",),
            "OPEN",
            "job:pool.open",
            "now >= open_at",
            ("audit",),
        ),
        Transition(
            "PS-03",
            ("OPEN",),
            "CLOSED",
            "job:pool.close",
            "now >= close_at",
            ("audit", "job:pool.seed"),
        ),
        Transition(
            "PS-04",
            ("CLOSED",),
            "SEEDED",
            "job:pool.seed",
            "beacon round value available, or demo seed",
            ("audit", "job:pool.allocate"),
        ),
        Transition(
            "PS-05",
            ("SEEDED",),
            "ALLOCATED",
            "job:pool.allocate",
            "ordering computed; lots created",
            ("audit", "job:lot.bid_open"),
        ),
        Transition(
            "PS-06",
            ("ALLOCATED",),
            "RUNNING",
            "job:lot.bid_open",
            "first lot enters BIDDING",
            ("audit",),
        ),
        Transition(
            "PS-07",
            ("RUNNING",),
            "COMPLETED",
            "system.lots_terminal",
            "every lot is CLOSED, FAILED_CLOSED or CANCELLED",
            ("audit",),
        ),
        Transition(
            "PS-08",
            ("DRAFT", "PUBLISHED", "OPEN", "CLOSED", "SEEDED", "ALLOCATED"),
            "CANCELLED",
            "admin.cancel",
            "no buyer_orders exist for the pool",
            ("audit", "notify"),
        ),
        Transition(
            "PS-09",
            ("ALLOCATED",),
            "COMPLETED",
            "job:pool.allocate",
            "no lot is PLANNED (all lots CANCELLED or no entries)",
            ("audit",),
        ),
    ),
)

ENTRY = _machine(
    "entry",
    "SUBMITTED",
    ("SUBMITTED", "ELIGIBLE", "REJECTED", "WITHDRAWN"),
    ("REJECTED", "WITHDRAWN"),
    (
        Transition(
            "ES-01",
            ("SUBMITTED",),
            "ELIGIBLE",
            "job:pool.close",
            "link still active when required; request still valid",
            ("audit",),
        ),
        Transition(
            "ES-02",
            ("SUBMITTED",),
            "REJECTED",
            "job:pool.close",
            "link inactive or request invalid; reject_reason set",
            ("audit", "notify"),
        ),
        Transition(
            "ES-03",
            ("SUBMITTED",),
            "WITHDRAWN",
            "buyer.withdraw",
            "pool status OPEN and now < close_at",
            ("audit",),
        ),
    ),
)

LOT = _machine(
    "lot",
    "PLANNED",
    (
        "PLANNED",
        "BIDDING",
        "BID_CLOSED",
        "AWARDED",
        "CHECKOUT_OPEN",
        "FUNDING",
        "FUNDED",
        "CLOSED",
        "FAILING",
        "FAILED_CLOSED",
        "CANCELLED",
    ),
    ("CLOSED", "FAILED_CLOSED", "CANCELLED"),
    (
        Transition(
            "LS-01",
            ("PLANNED",),
            "BIDDING",
            "job:lot.bid_open",
            "now >= bid_open_at",
            ("audit", "job:lot.bid_close"),
        ),
        Transition(
            "LS-02",
            ("BIDDING",),
            "BID_CLOSED",
            "job:lot.bid_close",
            "now >= bid_close_at; late bids already rejected",
            ("audit", "job:lot.award"),
        ),
        Transition(
            "LS-03",
            ("BID_CLOSED",),
            "AWARDED",
            "job:lot.award",
            "all lower lot_order lots are past BID_CLOSED; a bid passes R1 to R9; "
            "award snapshot written; router and mode stamped (N8)",
            ("audit", "job:lot.open_checkout", "notify"),
        ),
        Transition(
            "LS-04",
            ("BID_CLOSED",),
            "CANCELLED",
            "job:lot.award",
            "no feasible bid; no money exists",
            ("audit", "notify"),
        ),
        Transition(
            "LS-05",
            ("AWARDED",),
            "CHECKOUT_OPEN",
            "job:lot.open_checkout",
            "award exists; priced-out seats released; offers created within seats (I8)",
            ("audit", "job:offer.expire", "job:lot.try_fund", "notify"),
        ),
        Transition(
            "LS-06",
            ("CHECKOUT_OPEN",),
            "FUNDING",
            "job:lot.try_fund",
            "authorized count A >= min(seats, moq + CAPTURE_BUFFER), or "
            "fund_deadline_at passed and A >= moq",
            ("audit", "job:order.capture"),
        ),
        Transition(
            "LS-07",
            ("FUNDING",),
            "FUNDED",
            "job:lot.try_fund",
            "completed captures from distinct buyers >= moq, read from the ledger (I5)",
            ("audit", "notify", "job:lot.finalize_close"),
        ),
        Transition(
            "LS-08",
            ("CHECKOUT_OPEN",),
            "FAILING",
            "job:lot.try_fund",
            "fund_deadline_at passed with A < moq, or winning offer expired, or ops abort",
            ("audit", "job:lot.finalize_fail", "notify"),
        ),
        Transition(
            "LS-09",
            ("FUNDING",),
            "FAILING",
            "job:lot.try_fund",
            "sweep resolved with completed < moq and no refill possible, or "
            "winning offer expired, or ops abort",
            ("audit", "job:lot.finalize_fail", "notify"),
        ),
        Transition(
            "LS-10",
            ("FAILING",),
            "FAILED_CLOSED",
            "job:lot.finalize_fail",
            "every authorization VOIDED or expired; every completed capture has a "
            "COMPLETED refund; no capture PENDING; net paid is zero",
            ("audit", "notify"),
        ),
        Transition(
            "LS-11",
            ("FUNDED",),
            "CLOSED",
            "job:lot.finalize_close",
            "capture window over; ledger balanced; merchant notified",
            ("audit",),
        ),
        Transition(
            "LS-12",
            ("PLANNED",),
            "CANCELLED",
            "job:pool.allocate",
            "entries available below min_seats (N2)",
            ("audit",),
        ),
        Transition(
            "LS-13",
            ("AWARDED",),
            "CANCELLED",
            "admin.abort",
            "checkout not yet open; no money exists (N3)",
            ("audit", "notify"),
        ),
    ),
)

BUYER_ORDER = _machine(
    "buyer_order",
    "OFFERED",
    (
        "OFFERED",
        "ORDER_CREATED",
        "APPROVED",
        "AUTHORIZING",
        "AUTHORIZED",
        "CAPTURING",
        "CAPTURE_PENDING",
        "CAPTURED",
        "REFUNDING",
        "EXPIRED",
        "REJECTED",
        "AUTH_FAILED",
        "CAPTURE_FAILED",
        "VOIDED",
        "REFUNDED",
        "DECLINED",
    ),
    (
        "EXPIRED",
        "REJECTED",
        "AUTH_FAILED",
        "CAPTURE_FAILED",
        "VOIDED",
        "REFUNDED",
        "DECLINED",
    ),
    (
        Transition(
            "BO-01",
            ("OFFERED",),
            "ORDER_CREATED",
            "buyer.continue",
            "seat valid; now < offer_expires_at; lot CHECKOUT_OPEN; award valid; total <= cap",
            ("audit",),
            paypal="create_order",
            key="create:{buyer_order_id}:{attempt}",
        ),
        Transition(
            "BO-02",
            ("ORDER_CREATED",),
            "APPROVED",
            "buyer.return | buyer.approved_callback | webhook | poll",
            "GET order shows APPROVED; amount, currency, payee, country and payer-key "
            "checks pass (FR-CK-05)",
            ("audit", "job:order.authorize"),
            paypal="get_order",
        ),
        Transition(
            "BO-03",
            ("APPROVED",),
            "AUTHORIZING",
            "job:order.authorize",
            "row lock taken; seat still valid; lot CHECKOUT_OPEN; sets seat_locked_until (I7)",
            ("audit",),
        ),
        Transition(
            "BO-04",
            ("AUTHORIZING",),
            "AUTHORIZED",
            "job:order.authorize",
            "authorization status CREATED; amount equals expected (I3)",
            ("audit", "ledger:AUTH_CREATED", "job:lot.try_fund"),
            paypal="authorize_order",
            key="auth:{buyer_order_id}",
        ),
        Transition(
            "BO-05",
            ("AUTHORIZING",),
            "AUTH_FAILED",
            "job:order.authorize",
            "definitive denial (status DENIED or definitive 4xx other than ORDER_NOT_APPROVED)",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-06",
            ("AUTHORIZED",),
            "CAPTURING",
            "job:order.capture",
            "lot FUNDING or FUNDED",
            ("audit",),
            paypal="capture_authorization",
            key="cap:{paypal_auth_id}",
        ),
        Transition(
            "BO-07",
            ("CAPTURING",),
            "CAPTURED",
            "job:order.capture",
            "capture status COMPLETED",
            ("audit", "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"),
            paypal="get_capture",
        ),
        Transition(
            "BO-08",
            ("CAPTURING",),
            "CAPTURE_PENDING",
            "job:order.capture",
            "capture status PENDING (P3)",
            ("audit", "ledger:CAPTURE_PENDING", "job:capture.poll"),
        ),
        Transition(
            "BO-09",
            ("CAPTURE_PENDING",),
            "CAPTURED",
            "job:capture.poll",
            "capture status COMPLETED",
            ("audit", "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"),
        ),
        Transition(
            "BO-10",
            ("CAPTURE_PENDING",),
            "CAPTURE_FAILED",
            "job:capture.poll",
            "capture DECLINED or FAILED, or pending_wait exceeded",
            ("audit", "ledger:CAPTURE_DECLINED", "job:lot.refill"),
        ),
        Transition(
            "BO-11",
            ("CAPTURING",),
            "CAPTURE_FAILED",
            "job:order.capture",
            "capture DECLINED or FAILED",
            ("audit", "ledger:CAPTURE_DECLINED", "job:lot.refill"),
        ),
        Transition(
            "BO-12",
            ("AUTHORIZED",),
            "VOIDED",
            "job:void.run",
            "not yet captured; reason in void_source",
            ("audit", "ledger:AUTH_VOIDED", "job:lot.refill"),
            paypal="void_authorization",
            key="void:{paypal_auth_id}",
        ),
        Transition(
            "BO-13",
            ("CAPTURED",),
            "REFUNDING",
            "job:refund.run",
            "lot FAILING or ops refund",
            ("audit", "ledger:REFUND_PENDING"),
            paypal="refund_capture",
            key="refund:{paypal_capture_id}:{seq}",
        ),
        Transition(
            "BO-14",
            ("REFUNDING",),
            "REFUNDED",
            "job:refund.run",
            "refund status COMPLETED",
            ("audit", "ledger:REFUND_COMPLETED"),
            paypal="get_refund",
        ),
        Transition(
            "BO-15",
            ("OFFERED",),
            "EXPIRED",
            "job:offer.expire",
            "now >= offer_expires_at; not AUTHORIZING (I7, I15)",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-16",
            ("ORDER_CREATED",),
            "EXPIRED",
            "job:offer.expire",
            "now >= offer_expires_at; not AUTHORIZING (I7, I15)",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-17",
            ("APPROVED",),
            "EXPIRED",
            "job:offer.expire",
            "now >= offer_expires_at; not AUTHORIZING (N4, F5)",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-18",
            ("ORDER_CREATED",),
            "REJECTED",
            "buyer.return | buyer.approved_callback | poll",
            "policy failure: duplicate payer, wrong country, amount or payee "
            "mismatch; never authorize",
            ("audit", "job:lot.refill", "notify"),
        ),
        Transition(
            "BO-19",
            ("APPROVED",),
            "REJECTED",
            "job:order.authorize",
            "policy failure found before authorizing",
            ("audit", "job:lot.refill", "notify"),
        ),
        Transition(
            "BO-20",
            ("AUTHORIZING",),
            "REJECTED",
            "job:order.authorize",
            "authorization amount differs from expected; authorization voided at once (N5)",
            ("audit", "ledger:AUTH_VOIDED", "job:lot.refill", "notify"),
            paypal="void_authorization",
            key="void:{paypal_auth_id}",
        ),
        Transition(
            "BO-21",
            ("OFFERED",),
            "DECLINED",
            "buyer.decline",
            "seat valid",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-22",
            ("ORDER_CREATED",),
            "DECLINED",
            "buyer.cancel | buyer.cancelled_callback | buyer.decline",
            "not AUTHORIZING",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-23",
            ("OFFERED",),
            "CAPTURING",
            "job:order.vault_charge",
            "payment_mode vault_charge; seat valid; lot CHECKOUT_OPEN; award valid; "
            "vault token ACTIVE; total <= cap by integer compare; row lock taken",
            ("audit",),
            paypal="charge_vault",
            key="vc:{buyer_order_id}",
        ),
        Transition(
            "BO-24",
            ("CAPTURING",),
            "CAPTURED",
            "job:order.vault_charge",
            "capture status COMPLETED; amount equals the award total; payee equals the seller (I3)",
            ("audit", "ledger:CAPTURE_COMPLETED", "job:lot.try_fund"),
            paypal="get_capture",
        ),
        Transition(
            "BO-25",
            ("CAPTURING",),
            "CAPTURE_PENDING",
            "job:order.vault_charge",
            "capture status PENDING (P3)",
            ("audit", "ledger:CAPTURE_PENDING", "job:capture.poll"),
        ),
        Transition(
            "BO-26",
            ("CAPTURING",),
            "CAPTURE_FAILED",
            "job:order.vault_charge",
            "definitive decline: INSTRUMENT_DECLINED, status DENIED or 403 "
            "PERMISSION_DENIED (token then marked DELETED); unknown outcomes stay "
            "CAPTURING",
            ("audit", "job:lot.refill"),
        ),
        Transition(
            "BO-27",
            ("OFFERED",),
            "REJECTED",
            "job:order.vault_charge",
            "vault precheck failed: token missing or not ACTIVE, total above cap, "
            "lot no longer CHECKOUT_OPEN, or award invalid",
            ("audit", "job:lot.refill"),
        ),
    ),
    active=(
        "OFFERED",
        "ORDER_CREATED",
        "APPROVED",
        "AUTHORIZING",
        "AUTHORIZED",
        "CAPTURING",
        "CAPTURE_PENDING",
        "CAPTURED",
        "REFUNDING",
    ),
)

BID = _machine(
    "bid",
    "DRAFT",
    ("DRAFT", "PROPOSED", "CONFIRMED", "FLAGGED", "REJECTED", "ELIGIBLE", "AWARDED", "LOST"),
    ("REJECTED", "AWARDED", "LOST"),
    (
        Transition(
            "BS-01",
            ("DRAFT",),
            "PROPOSED",
            "merchant.quote",
            "AI proposes fields from a pasted quote (DEP-2)",
            ("audit",),
        ),
        Transition(
            "BS-02",
            ("DRAFT",),
            "CONFIRMED",
            "merchant.confirm",
            "structured form complete and valid",
            ("audit",),
        ),
        Transition(
            "BS-03",
            ("PROPOSED",),
            "CONFIRMED",
            "merchant.confirm",
            "merchant reviewed and confirmed every field",
            ("audit",),
        ),
        Transition(
            "BS-04",
            ("CONFIRMED",),
            "FLAGGED",
            "ai.reconcile",
            "a BLOCKING flag was raised (R7)",
            ("audit", "notify"),
        ),
        Transition(
            "BS-05",
            ("FLAGGED",),
            "CONFIRMED",
            "merchant.confirm",
            "merchant saved a corrected revision; new flags none",
            ("audit",),
        ),
        Transition(
            "BS-06",
            ("CONFIRMED",),
            "REJECTED",
            "job:lot.award",
            "a rule among R1 to R6, R8 or R9 failed; reject_reason set",
            ("audit", "notify"),
        ),
        Transition(
            "BS-07",
            ("CONFIRMED",),
            "ELIGIBLE",
            "job:lot.award",
            "all rules pass",
            ("audit",),
        ),
        Transition(
            "BS-08",
            ("ELIGIBLE",),
            "AWARDED",
            "job:lot.award",
            "lowest ranking key",
            ("audit", "notify"),
        ),
        Transition(
            "BS-09",
            ("ELIGIBLE",),
            "LOST",
            "job:lot.award",
            "not the winner",
            ("audit", "notify"),
        ),
        Transition(
            "BS-10",
            ("FLAGGED",),
            "REJECTED",
            "job:lot.award",
            "still FLAGGED at award (R7)",
            ("audit", "notify"),
        ),
        Transition(
            "BS-11",
            ("PROPOSED", "DRAFT"),
            "REJECTED",
            "job:lot.award",
            "unconfirmed fields at award (R1)",
            ("audit", "notify"),
        ),
        Transition(
            "BS-12",
            ("PROPOSED", "CONFIRMED", "FLAGGED"),
            "DRAFT",
            "merchant.revise",
            "now < bid_close_at; creates a new revision with a receipt",
            ("audit",),
        ),
    ),
)

#: Machine name to its full definition. The YAML blocks are the source of truth.
MACHINES: dict[str, Machine] = {
    "pool": POOL,
    "entry": ENTRY,
    "lot": LOT,
    "buyer_order": BUYER_ORDER,
    "bid": BID,
}

#: Transition id (PS-01, BO-12, ...) to its transition, across every machine.
TRANSITIONS_BY_ID: dict[str, Transition] = {
    transition.id: transition for machine in MACHINES.values() for transition in machine.transitions
}


def assert_transition(
    machine: str,
    from_state: str,
    to_state: str,
    *,
    trigger: str | None = None,
) -> Transition:
    """Return the whitelisted transition or raise ``IllegalTransition`` (I10).

    Some pairs (for example CAPTURING to CAPTURED) are listed twice with
    different triggers; pass ``trigger`` to select one, otherwise the first
    listed transition is returned.
    """
    definition = MACHINES.get(machine)
    if definition is None:
        raise UnknownMachine(machine)
    for transition in definition.transitions:
        if from_state not in transition.from_states or transition.to_state != to_state:
            continue
        if trigger is not None and transition.trigger != trigger:
            continue
        return transition
    raise IllegalTransition(machine, from_state, to_state)


def is_legal(
    machine: str,
    from_state: str,
    to_state: str,
    *,
    trigger: str | None = None,
) -> bool:
    """True when the pair is whitelisted (and the trigger matches, when given)."""
    try:
        assert_transition(machine, from_state, to_state, trigger=trigger)
    except IllegalTransition:
        return False
    return True
