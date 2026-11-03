"""Pure buyer-order guard decisions for the checkout transition engine (T03A01).

No I/O, no SQLAlchemy and no process clock. Every value is passed in, and the
deadline comparison uses the ``datetime`` the caller read from
``Clock.db_wall_now`` *after* its row lock (CR-3 note 1, I15); this module never
reads a clock of its own.

Legality comes from the whitelist in ``domain/states.py`` and nowhere else: this
module never lists a permitted ``(from, to)`` pair. ``allowed_transition_id``
first asks the whitelist, then decides whether the guard *text* of that listed
transition is satisfied by the data. A whitelisted pair whose guard is unmet is
still not allowed to run, so both failures raise ``IllegalTransition`` (I10) and
the caller's transaction fails (CR-3 note 5).

Sources for each rule are cited where the rule is applied:
``docs/contracts/state-machines.md`` (guards, vacancy rule), ``vault-charge.md``
sections 3, 4 and 7 (mode families, precheck, outcomes), ``paypal-adapter.md``
sections 3, 4, 6 and 7 (keys, resource statuses, approval checks, error classes)
and invariants I3, I4, I7, I8, I10, I15 and V8.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from .errors import IllegalTransition, MoneyError
from .states import TRANSITIONS_BY_ID, assert_transition

MACHINE: Final[str] = "buyer_order"

#: ``payment_mode`` values stamped on the lot at award (N8, db-schema.md).
MODE_VAULT: Final[str] = "vault_charge"
MODE_AUTHORIZE: Final[str] = "authorize_capture"
MODE_CAPTURE_ONLY: Final[str] = "capture_only"
STAMPED_MODES: Final[frozenset[str]] = frozenset({MODE_VAULT, MODE_AUTHORIZE, MODE_CAPTURE_ONLY})

#: ``payment_router`` values named by ``paypal-adapter.md`` section 9.
STAMPED_ROUTERS: Final[frozenset[str]] = frozenset(
    {"fake", "single_seller", "payee_email", "platform"}
)

#: Evidence provenance (I4, V8): a validated adapter result or an explicit test
#: fixture. Nothing else may carry a money-bearing fact.
EVIDENCE_ADAPTER: Final[str] = "adapter"
EVIDENCE_FIXTURE: Final[str] = "fixture"
EVIDENCE_SOURCES: Final[frozenset[str]] = frozenset({EVIDENCE_ADAPTER, EVIDENCE_FIXTURE})

OBSERVATION_KINDS: Final[frozenset[str]] = frozenset(
    {"approval", "authorization", "capture", "refund", "charge"}
)

#: ``buyer_orders.void_source`` values (config-and-errors.md section 5).
VOID_SOURCES: Final[frozenset[str]] = frozenset(
    {"lot_failing", "buyer_withdraw", "age_guard", "paypal_expired"}
)

#: ``buyer_orders.reject_reason`` values (config-and-errors.md section 5).
REJECT_REASONS: Final[frozenset[str]] = frozenset(
    {
        "DUPLICATE_PAYER",
        "WRONG_COUNTRY",
        "CURRENCY_MISMATCH",
        "AMOUNT_MISMATCH",
        "PAYEE_MISMATCH",
        "PAYER_MISMATCH",
        "STATUS_NOT_APPROVED",
    }
)

#: Resource statuses that mean "paid" and nothing else (P3, I4).
CAPTURE_COMPLETED: Final[str] = "COMPLETED"
CAPTURE_PENDING: Final[str] = "PENDING"
CAPTURE_FAILURES: Final[frozenset[str]] = frozenset({"DECLINED", "FAILED"})

#: Definitive vault-charge declines (vault-charge.md section 7): 422
#: ``INSTRUMENT_DECLINED``, status ``DENIED`` and the 403 rows. ``TOKEN_REVOKED`` is
#: the adapter's code for a deleted or revoked permission, which the contract files
#: under the same 403 row (VC-03).
VAULT_DECLINE_CODES: Final[frozenset[str]] = frozenset(
    {"INSTRUMENT_DECLINED", "PERMISSION_DENIED", "TOKEN_REVOKED"}
)

#: Transitions that exist only in ``PAYMENT_MODE=vault_charge``: BO-23 names the
#: mode in its own guard and BO-24 to BO-27 share its trigger, which is enqueued
#: only in that mode (vault-charge.md section 3).
VAULT_ONLY: Final[frozenset[str]] = frozenset({"BO-23", "BO-24", "BO-25", "BO-26", "BO-27"})

#: Refunds and capture polling are mode-independent (state-machines.md, vault-charge.md
#: section 7). A capture that is already pending has no ladder to climb, so polling it
#: (BO-09/BO-10) is the same act in both modes; LS-10 requires a COMPLETED refund for
#: every completed capture whatever the mode (BO-13/BO-14).
MODE_INDEPENDENT: Final[frozenset[str]] = frozenset({"BO-09", "BO-10", "BO-13", "BO-14"})

#: Under ``PAYMENT_MODE=vault_charge`` the buyer checkout ladder is not used and
#: there is no buyer payment window (vault-charge.md section 3), and no
#: authorization exists to void (section 1). BO-09 and BO-10 are absent on purpose:
#: they poll a capture that already exists, which is the same act in both modes and
#: the only way a vault PENDING charge ever resolves (``capture.poll``).
AUTHORIZE_LADDER: Final[frozenset[str]] = frozenset(
    {
        "BO-01",
        "BO-02",
        "BO-03",
        "BO-04",
        "BO-05",
        "BO-06",
        "BO-07",
        "BO-08",
        "BO-11",
        "BO-12",
        "BO-15",
        "BO-16",
        "BO-17",
        "BO-18",
        "BO-19",
        "BO-20",
        "BO-21",
        "BO-22",
    }
)

#: Terminal states that create one claimable vacancy (vacancy rule after the
#: buyer_order table). ``REFUNDED`` is absent: it never frees a seat.
VACANCY_STATES: Final[frozenset[str]] = frozenset(
    {"EXPIRED", "REJECTED", "AUTH_FAILED", "CAPTURE_FAILED", "DECLINED"}
)

#: The only void sources that free a seat (vacancy rule).
VACANCY_VOID_SOURCES: Final[frozenset[str]] = frozenset(
    {"buyer_withdraw", "age_guard", "paypal_expired"}
)

#: States that report the outcome of a money movement, so a guard reading them
#: must be fed by validated evidence (I4). ``CAPTURING`` is absent on purpose:
#: entering it is the step *before* the adapter call, so no result exists yet.
MONEY_OUTCOME_STATES: Final[frozenset[str]] = frozenset(
    {
        "AUTHORIZED",
        "AUTH_FAILED",
        "CAPTURE_PENDING",
        "CAPTURED",
        "CAPTURE_FAILED",
        "REFUNDING",
        "REFUNDED",
        "VOIDED",
    }
)

#: PayPal's own ``order.status`` is never a payment signal: in the sandbox it read
#: COMPLETED after a void (V8). No guard below reads ``BuyerOrderFacts.paypal_order_status``;
#: the field exists so a caller can hand it over and a test can prove it is ignored.


@dataclass(frozen=True)
class Observation:
    """One resource status read from a validated adapter result or a test fixture.

    ``status`` is the *authorization*, *capture* or *refund* resource status, never
    the order's own status (paypal-adapter.md section 4, V8). ``payee_matches`` and
    ``checks_passed`` are the outcome of the section 6 approval checks, computed by
    the handler that made the call because only it knows the expected payee and the
    allowed payer countries.
    """

    kind: str
    status: str
    reference: str
    source: str = EVIDENCE_ADAPTER
    amount_cents: int | None = None
    currency: str | None = None
    checks_passed: bool | None = None
    payee_matches: bool | None = None
    error_code: str | None = None
    error_class: str | None = None


@dataclass(frozen=True)
class BuyerOrderFacts:
    """Everything a buyer_order guard needs, as data.

    The caller reads each field after taking the lot and buyer-order row locks;
    ``now`` is ``Clock.db_wall_now`` at that moment (CR-3 note 1).
    """

    from_state: str
    to_state: str
    trigger: str | None = None
    now: datetime | None = None
    offer_expires_at: datetime | None = None
    award_valid_until: datetime | None = None
    lot_status: str | None = None
    payment_mode: str | None = None
    payment_router: str | None = None
    seat_valid: bool = False
    row_lock_taken: bool = False
    total_cents: int | None = None
    cap_cents: int | None = None
    expected_cents: int | None = None
    observation: Observation | None = None
    void_source: str | None = None
    reject_reason: str | None = None
    has_completed_capture: bool = False
    ops_refund: bool = False
    pending_wait_exceeded: bool = False
    saved_permission_status: str | None = None
    seat_locked_until: datetime | None = None
    paypal_order_status: str | None = None


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------


def cents(value: int | None, field: str) -> int | None:
    """Return ``value`` when it is integer cents, or raise ``MoneyError`` (BD-14, I3)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{field} must be integer cents, got {type(value).__name__}")
    return value


def _money(value: int | None, field: str) -> str | None:
    """Validate a stored cent amount and report a problem as a guard reason."""
    if value is None:
        return f"missing {field}"
    try:
        cents(value, field)
    except MoneyError:
        return f"{field} is not integer cents"
    return None


def _stamped(facts: BuyerOrderFacts) -> str | None:
    """The lot's stamped router and mode must exist and be known values (N8)."""
    if facts.payment_mode not in STAMPED_MODES:
        return f"lot payment_mode is not stamped: {facts.payment_mode!r}"
    if facts.payment_router not in STAMPED_ROUTERS:
        return f"lot payment_router is not stamped: {facts.payment_router!r}"
    return None


def _mode_family(transition_id: str, facts: BuyerOrderFacts) -> str | None:
    """BO-23 to BO-27 are the vault path; the ladder is not used in that mode."""
    if transition_id in MODE_INDEPENDENT:
        return None
    if facts.payment_mode == MODE_VAULT and transition_id in AUTHORIZE_LADDER:
        return (
            f"{transition_id} belongs to the buyer checkout ladder, which is not "
            f"used under {MODE_VAULT} (vault-charge.md section 3)"
        )
    if facts.payment_mode != MODE_VAULT and transition_id in VAULT_ONLY:
        return f"{transition_id} requires the stamped mode {MODE_VAULT} (BO-23 guard)"
    return None


def _deadline_passed(facts: BuyerOrderFacts) -> str | None:
    """``now >= offer_expires_at`` read from the wall clock after the lock (I15)."""
    if facts.now is None or facts.offer_expires_at is None:
        return "the offer deadline or the wall-clock reading is missing"
    if facts.now < facts.offer_expires_at:
        return "now < offer_expires_at: the offer window has not ended"
    return None


def _deadline_open(facts: BuyerOrderFacts) -> str | None:
    """``now < offer_expires_at`` for admission (BO-01)."""
    if facts.now is None or facts.offer_expires_at is None:
        return "the offer deadline or the wall-clock reading is missing"
    if facts.now >= facts.offer_expires_at:
        return "now >= offer_expires_at: the offer window has ended (OFFER_EXPIRED)"
    return None


def _award_valid(facts: BuyerOrderFacts) -> str | None:
    """The award snapshot must exist and still be valid at the wall clock (BO-01)."""
    if facts.award_valid_until is None:
        return "no award is attached to the lot"
    if facts.now is None:
        return "the wall-clock reading is missing"
    if facts.now >= facts.award_valid_until:
        return "now >= award valid_until: the award snapshot expired"
    return None


def _lot_status(*allowed: str) -> Callable[[BuyerOrderFacts], str | None]:
    """A predicate requiring the lot to be in one of ``allowed`` states."""

    def check(facts: BuyerOrderFacts) -> str | None:
        if facts.lot_status is None:
            return "the lot row is missing"
        if facts.lot_status not in allowed:
            return f"lot status is {facts.lot_status}, expected one of {sorted(allowed)}"
        return None

    return check


def _seat(facts: BuyerOrderFacts) -> str | None:
    if not facts.seat_valid:
        return "the allocation no longer holds this seat (SEAT_NOT_VALID)"
    return None


def _cap(facts: BuyerOrderFacts) -> str | None:
    """``total <= cap`` by integer cent compare; never float (vault-charge.md section 4)."""
    problem = _money(facts.total_cents, "total_cents") or _money(facts.cap_cents, "cap_cents")
    if problem:
        return problem
    assert facts.total_cents is not None and facts.cap_cents is not None
    if facts.total_cents > facts.cap_cents:
        return f"total {facts.total_cents} exceeds the buyer cap {facts.cap_cents}"
    return None


def _expected(facts: BuyerOrderFacts) -> str | None:
    return _money(facts.expected_cents, "expected_cents")


def _evidence(facts: BuyerOrderFacts, *kinds: str) -> str | None:
    """A money-bearing guard may only read validated evidence of the named kind."""
    observation = facts.observation
    if observation is None:
        return "no validated adapter result or test fixture backs this money fact (I4)"
    if observation.source not in EVIDENCE_SOURCES:
        return (
            f"evidence source {observation.source!r} is not a validated adapter result or fixture"
        )
    if not observation.reference:
        return "the evidence carries no PayPal resource reference"
    if kinds and observation.kind not in kinds:
        return f"evidence kind {observation.kind!r} is not one of {sorted(kinds)}"
    return None


def _amount_equals_expected(facts: BuyerOrderFacts) -> str | None:
    observation = facts.observation
    assert observation is not None
    problem = _money(observation.amount_cents, "observation.amount_cents")
    if problem:
        return problem
    assert facts.expected_cents is not None and observation.amount_cents is not None
    if observation.amount_cents != facts.expected_cents:
        return (
            f"observed amount {observation.amount_cents} does not equal the expected "
            f"{facts.expected_cents} (I3)"
        )
    return None


def _usd(facts: BuyerOrderFacts) -> str | None:
    observation = facts.observation
    if observation is None or observation.currency != "USD":
        return "currency is not USD (V12, DEP-1)"
    return None


def _void_source(facts: BuyerOrderFacts) -> str | None:
    if facts.void_source not in VOID_SOURCES:
        return f"void_source {facts.void_source!r} is not a contracted reason"
    return None


def _definitive_denial(facts: BuyerOrderFacts) -> str | None:
    """BO-05: DENIED, EXPIRED or VOIDED, or a definitive 4xx that is not ORDER_NOT_APPROVED.

    CR-8 note 1; V4 keeps ``ORDER_NOT_APPROVED`` a wait rather than a denial.
    """
    observation = facts.observation
    assert observation is not None
    if observation.status in {"DENIED", "EXPIRED", "VOIDED"}:
        # An authorization that can never be captured ends the seat; CR-8 note 1.
        return None
    if observation.error_code == "ORDER_NOT_APPROVED":
        return "ORDER_NOT_APPROVED is a wait, not a failure (V4)"
    if observation.error_class in {"TERMINAL", "CONFIG", "BUG"}:
        return None
    return "the denial is not definitive: stay AUTHORIZING and poll (paypal-adapter.md section 4)"


def _policy_failure(facts: BuyerOrderFacts) -> str | None:
    """BO-18 and BO-19: a named policy failure, recorded as a reject reason."""
    if facts.reject_reason not in REJECT_REASONS:
        return f"reject_reason {facts.reject_reason!r} is not a contracted policy failure"
    observation = facts.observation
    if observation is not None and observation.checks_passed is True:
        return "the approval checks passed, so this is not a policy failure"
    return None


# ---------------------------------------------------------------------------
# one predicate per whitelisted buyer_order transition
# ---------------------------------------------------------------------------


def _bo_01(facts: BuyerOrderFacts) -> str | None:
    # "seat valid; now < offer_expires_at; lot CHECKOUT_OPEN; award valid; total <= cap"
    return (
        _seat(facts)
        or _deadline_open(facts)
        or _lot_status("CHECKOUT_OPEN")(facts)
        or _award_valid(facts)
        or _cap(facts)
    )


def _bo_02(facts: BuyerOrderFacts) -> str | None:
    # "GET order shows APPROVED; amount, currency, payee, country and payer-key
    # checks pass (FR-CK-05)"; paypal-adapter.md section 6.
    reason = (
        _evidence(facts, "approval")
        or _expected(facts)
        or _amount_equals_expected(facts)
        or _usd(facts)
    )
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != "APPROVED":
        return f"order is not APPROVED on GET: {observation.status}"
    if observation.checks_passed is not True:
        return "the payee, country and payer-key checks did not all pass (FR-CK-05)"
    return None


def _bo_03(facts: BuyerOrderFacts) -> str | None:
    # "row lock taken; seat still valid; lot CHECKOUT_OPEN; sets seat_locked_until (I7)"
    if not facts.row_lock_taken:
        return "the buyer-order row lock was not taken (I7)"
    if facts.seat_locked_until is None:
        return "seat_locked_until is not set, so the seat would stay unlockable (I7)"
    return _seat(facts) or _lot_status("CHECKOUT_OPEN")(facts)


def _bo_04(facts: BuyerOrderFacts) -> str | None:
    # "authorization status CREATED; amount equals expected (I3)"
    reason = _evidence(facts, "authorization", "approval") or _expected(facts)
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != "CREATED":
        return f"authorization status is {observation.status}, expected CREATED"
    return _amount_equals_expected(facts)


def _bo_05(facts: BuyerOrderFacts) -> str | None:
    # "definitive denial (status DENIED or definitive 4xx other than ORDER_NOT_APPROVED)"
    reason = _evidence(facts, "authorization", "approval")
    if reason:
        return reason
    return _definitive_denial(facts)


def _bo_06(facts: BuyerOrderFacts) -> str | None:
    # "lot FUNDING or FUNDED"
    return _lot_status("FUNDING", "FUNDED")(facts)


def _bo_07(facts: BuyerOrderFacts) -> str | None:
    # "capture status COMPLETED" (P3: COMPLETED is the only paid status)
    reason = _evidence(facts, "capture", "charge") or _expected(facts)
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != CAPTURE_COMPLETED:
        return f"capture status is {observation.status}, expected COMPLETED (P3, I4)"
    return _amount_equals_expected(facts)


def _bo_08(facts: BuyerOrderFacts) -> str | None:
    # "capture status PENDING (P3)"
    reason = _evidence(facts, "capture", "charge")
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != CAPTURE_PENDING:
        return f"capture status is {observation.status}, expected PENDING"
    return None


def _bo_09(facts: BuyerOrderFacts) -> str | None:
    # "capture status COMPLETED" read by the poller's GET
    return _bo_07(facts)


def _bo_10(facts: BuyerOrderFacts) -> str | None:
    # "capture DECLINED or FAILED, or pending_wait exceeded"
    if facts.pending_wait_exceeded:
        return None
    reason = _evidence(facts, "capture", "charge")
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status not in CAPTURE_FAILURES:
        return f"capture status is {observation.status}; PENDING keeps polling (P3)"
    return None


def _bo_11(facts: BuyerOrderFacts) -> str | None:
    # "capture DECLINED or FAILED"
    reason = _evidence(facts, "capture", "charge")
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status not in CAPTURE_FAILURES:
        return f"capture status is {observation.status}, expected DECLINED or FAILED"
    return None


def _bo_12(facts: BuyerOrderFacts) -> str | None:
    # "not yet captured; reason in void_source"
    if facts.has_completed_capture:
        return "a completed capture exists, so the authorization is not voidable (I4)"
    return _void_source(facts)


def _bo_13(facts: BuyerOrderFacts) -> str | None:
    # "lot FAILING or ops refund"
    if facts.ops_refund:
        return _expected(facts)
    if facts.lot_status != "FAILING":
        return f"lot status is {facts.lot_status}, expected FAILING"
    return _expected(facts)


def _bo_14(facts: BuyerOrderFacts) -> str | None:
    # "refund status COMPLETED"
    reason = _evidence(facts, "refund") or _expected(facts)
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != CAPTURE_COMPLETED:
        return f"refund status is {observation.status}, expected COMPLETED"
    return _amount_equals_expected(facts)


def _expiry(facts: BuyerOrderFacts) -> str | None:
    # BO-15 to BO-17: "now >= offer_expires_at; not AUTHORIZING (I7, I15)". The
    # whitelist lists no edge into EXPIRED from AUTHORIZING, CAPTURING or
    # CAPTURE_PENDING, so reaching this predicate already proves the "not AUTHORIZING"
    # half (I7, N4, F5); only the deadline is left to prove.
    return _deadline_passed(facts)


def _bo_18(facts: BuyerOrderFacts) -> str | None:
    # "policy failure: duplicate payer, wrong country, amount or payee mismatch;
    # never authorize" -- the whitelist has no ORDER_CREATED to AUTHORIZED edge, so
    # a rejected order can never be authorized afterwards.
    reason = _evidence(facts, "approval")
    if reason is not None:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status == "APPROVED" and observation.checks_passed is True:
        return "the approved order passed every check, so nothing was rejected"
    return _policy_failure(facts)


def _bo_19(facts: BuyerOrderFacts) -> str | None:
    # "policy failure found before authorizing"
    return _policy_failure(facts)


def _bo_20(facts: BuyerOrderFacts) -> str | None:
    # "authorization amount differs from expected; authorization voided at once (N5)"
    reason = _evidence(facts, "authorization", "capture") or _expected(facts)
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.amount_cents == facts.expected_cents:
        return "the authorization amount equals the expected amount, so BO-20 does not apply (N5)"
    return None


def _bo_21(facts: BuyerOrderFacts) -> str | None:
    # "seat valid"
    return _seat(facts)


def _bo_22(facts: BuyerOrderFacts) -> str | None:
    # "not AUTHORIZING" (I7): BO-22 is listed only from ORDER_CREATED, where no
    # authorization is in flight, so the whitelist proves the guard by construction.
    return None


def vault_precheck_failures(facts: BuyerOrderFacts) -> tuple[str, ...]:
    """The BO-27 vault-charge precheck, as the list of reasons it failed.

    Empty means the precheck passed: the saved permission is ACTIVE, the total is
    at or below the cap by integer compare, the lot is still CHECKOUT_OPEN and the
    award is still valid (BO-27 guard text, vault-charge.md section 4). A missing
    permission row is reported as ``saved permission is missing``, which is the
    "token missing" case of the guard.
    """
    failures: list[str] = []
    if facts.saved_permission_status is None:
        failures.append("saved permission is missing")
    elif facts.saved_permission_status != "ACTIVE":
        failures.append(f"saved permission is {facts.saved_permission_status}, not ACTIVE")
    cap_problem = _cap(facts)
    if cap_problem is not None:
        failures.append(cap_problem)
    if facts.lot_status != "CHECKOUT_OPEN":
        failures.append(f"lot status is {facts.lot_status}, not CHECKOUT_OPEN")
    award_problem = _award_valid(facts)
    if award_problem is not None:
        failures.append(award_problem)
    return tuple(failures)


def _bo_23(facts: BuyerOrderFacts) -> str | None:
    # BO-23 guard text, part by part: "payment_mode vault_charge; seat valid; lot
    # CHECKOUT_OPEN; award valid; vault token ACTIVE; total <= cap by integer
    # compare; row lock taken". The mode part is already decided: ``_mode_family``,
    # which ``unmet_guard_reason`` runs before any predicate, refuses every VAULT_ONLY
    # id on a lot stamped anything else (N8, vault-charge.md section 3). The
    # permission must also carry a recorded consent, which the caller reads from the
    # same row (rule 27, vault-charge.md section 6).
    failures = vault_precheck_failures(facts)
    if failures:
        return "vault precheck failed: " + "; ".join(failures)
    # BO-23 is the step that opens the charge: like BO-06 it names the call its
    # handler is about to make, so no adapter result backs it yet.
    return _seat(facts) or (
        None if facts.row_lock_taken else "the buyer-order row lock was not taken (I7)"
    )


def _bo_24(facts: BuyerOrderFacts) -> str | None:
    # "capture status COMPLETED; amount equals the award total; payee equals the
    # seller (I3)" -- vault-charge.md section 2 evidence rule.
    reason = _evidence(facts, "capture", "charge") or _expected(facts)
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status != CAPTURE_COMPLETED:
        return f"capture status is {observation.status}: only COMPLETED is paid (I4)"
    equal = _amount_equals_expected(facts)
    if equal:
        return equal
    if observation.payee_matches is not True:
        return "the payee is not the seller named by the stamped router"
    return None


def _bo_25(facts: BuyerOrderFacts) -> str | None:
    # "capture status PENDING (P3)"
    return _bo_08(facts)


def _bo_26(facts: BuyerOrderFacts) -> str | None:
    # "definitive decline: INSTRUMENT_DECLINED, status DENIED or 403
    # PERMISSION_DENIED (token then marked DELETED); unknown outcomes stay
    # CAPTURING" (vault-charge.md section 7).
    reason = _evidence(facts, "charge", "capture")
    if reason:
        return reason
    observation = facts.observation
    assert observation is not None
    if observation.status in {"DENIED", "FAILED"}:
        return None
    if observation.error_code in VAULT_DECLINE_CODES:
        return None
    return (
        "the charge outcome is not definitive, so the order stays CAPTURING "
        "and is reconciled by GET (vault-charge.md section 7)"
    )


def _bo_27(facts: BuyerOrderFacts) -> str | None:
    # "vault precheck failed: token missing or not ACTIVE, total above cap, lot no
    # longer CHECKOUT_OPEN, or award invalid" (BO-27, vault-charge.md section 4). As
    # in BO-23, the stamped mode is decided by ``_mode_family`` before this runs.
    if not vault_precheck_failures(facts):
        return "the vault precheck passed, so the seat is charged (BO-23), not rejected"
    return None


#: transition id to its guard predicate. Built from the whitelist so a transition
#: added to ``state-machines.md`` cannot be silently left unchecked.
_GUARDS: Final[dict[str, Callable[[BuyerOrderFacts], str | None]]] = {
    "BO-01": _bo_01,
    "BO-02": _bo_02,
    "BO-03": _bo_03,
    "BO-04": _bo_04,
    "BO-05": _bo_05,
    "BO-06": _bo_06,
    "BO-07": _bo_07,
    "BO-08": _bo_08,
    "BO-09": _bo_09,
    "BO-10": _bo_10,
    "BO-11": _bo_11,
    "BO-12": _bo_12,
    "BO-13": _bo_13,
    "BO-14": _bo_14,
    "BO-15": _expiry,
    "BO-16": _expiry,
    "BO-17": _expiry,
    "BO-18": _bo_18,
    "BO-19": _bo_19,
    "BO-20": _bo_20,
    "BO-21": _bo_21,
    "BO-22": _bo_22,
    "BO-23": _bo_23,
    "BO-24": _bo_24,
    "BO-25": _bo_25,
    "BO-26": _bo_26,
    "BO-27": _bo_27,
}

_MISSING_GUARDS = {
    transition_id
    for transition_id, transition in TRANSITIONS_BY_ID.items()
    if transition.machine == MACHINE and transition_id not in _GUARDS
}
if _MISSING_GUARDS:  # pragma: no cover - a contract change without a predicate
    raise AssertionError(
        f"buyer_order transitions without a guard predicate: {sorted(_MISSING_GUARDS)}"
    )


def needs_validated_evidence(transition_id: str) -> bool:
    """True when the transition reports a money movement, so evidence is required.

    Derived from the whitelist: a ``ledger:`` effect records a money fact (I4) and a
    money outcome state reports the result of a call (V8: never from
    ``order.status``). A ``paypal:`` field alone is not enough -- BO-06 names the
    call the handler is about to make, so no result exists yet.
    """
    transition = TRANSITIONS_BY_ID[transition_id]
    return transition.to_state in MONEY_OUTCOME_STATES or any(
        effect.startswith("ledger:") for effect in transition.effects
    )


def unmet_guard_reason(transition_id: str, facts: BuyerOrderFacts) -> str | None:
    """Return why the guard of ``transition_id`` is unmet, or ``None`` when satisfied.

    The caller must have taken the row locks and read the wall clock first; this
    function only compares the data it was handed.
    """
    stamped = _stamped(facts)
    if stamped is not None:
        return stamped
    family = _mode_family(transition_id, facts)
    if family is not None:
        return family
    predicate = _GUARDS.get(transition_id)
    if predicate is None:
        return f"{transition_id} is not a buyer_order transition"
    reason = predicate(facts)
    if reason is not None:
        return reason
    if needs_validated_evidence(transition_id) and facts.observation is None:
        return "a money-bearing transition has no validated adapter result (I4, V8)"
    return None


def allowed_transition_id(facts: BuyerOrderFacts) -> str:
    """Return the whitelisted transition id whose guard the facts satisfy.

    Raises ``IllegalTransition`` when the whitelist has no such edge or when the
    listed transition's guard is unmet (I10). ``states.assert_transition`` stays
    the only source of legality; the guard text of the returned transition is what
    is evaluated here.
    """
    transition = assert_transition(MACHINE, facts.from_state, facts.to_state, trigger=facts.trigger)
    reason = unmet_guard_reason(transition.id, facts)
    if reason is not None:
        raise IllegalTransition(MACHINE, facts.from_state, facts.to_state)
    return transition.id


def creates_vacancy(*, to_state: str, void_source: str | None) -> bool:
    """Apply the vacancy rule after the buyer_order table.

    A transition into EXPIRED, REJECTED, AUTH_FAILED, CAPTURE_FAILED or DECLINED
    creates one claimable vacancy; VOIDED only when it was voided for
    ``buyer_withdraw``, ``age_guard`` or ``paypal_expired``. A VOIDED with
    ``void_source = lot_failing`` never does, and REFUNDED is not in the list.
    """
    if to_state == "VOIDED":
        return void_source in VACANCY_VOID_SOURCES
    return to_state in VACANCY_STATES


def ledger_amount_cents(facts: BuyerOrderFacts) -> int | None:
    """The integer-cent amount a ``ledger:`` effect of this transition records.

    The observed adapter amount wins when it exists; otherwise the stored expected
    amount. Never a value from a request body, and never a float (I3, I4).
    """
    observation = facts.observation
    if observation is not None and observation.amount_cents is not None:
        return cents(observation.amount_cents, "observation.amount_cents")
    if facts.expected_cents is not None:
        return cents(facts.expected_cents, "expected_cents")
    return facts.total_cents
