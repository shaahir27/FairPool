"""The closed mandate vocabulary a delegation token may carry (CR-14, FR-AI-06).

``ai-schemas.md`` section 9 defines five predicates with typed params and three actions.
The browser renders the buyer's mandate and hashes it, but this module is the authority:
a delegation token is minted only from conditions that pass here, and each predicate names
a rule deterministic code can evaluate against stored rows alone. No provider call and no
model call is allowed to resolve a condition (rule 5).

Amounts stay ``"520.00"`` strings because money is integer cents behind this boundary and
a float would not survive the round trip (I3). A predicate outside the vocabulary, a param
that belongs to another predicate, or a condition with no ``ratification_sha256`` is a
``VALIDATION_ERROR``: refused, never guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Final, NoReturn

from fairpool.domain.errors import ApplicationError

MAX_CONDITIONS: Final[int] = 5
ACTIONS: Final[frozenset[str]] = frozenset({"PROCEED", "REASK", "HALT"})

_AMOUNT: Final[re.Pattern[str]] = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")
_DAY: Final[re.Pattern[str]] = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SHA256: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}")
_CONDITION_KEYS: Final[frozenset[str]] = frozenset({"predicate", "params", "action"})


def _refuse() -> NoReturn:
    raise ApplicationError("VALIDATION_ERROR")


def _exact_keys(params: Mapping[str, Any], expected: frozenset[str]) -> None:
    if set(params) != expected:
        _refuse()


def _is_int(value: Any) -> bool:
    # bool is an int subclass; "true percent" is not a percentage.
    return isinstance(value, int) and not isinstance(value, bool)


def _price_above(params: dict[str, Any]) -> None:
    _exact_keys(params, frozenset({"amount"}))
    amount = params["amount"]
    if not isinstance(amount, str) or _AMOUNT.fullmatch(amount) is None:
        _refuse()


def _funding_below(params: dict[str, Any]) -> None:
    _exact_keys(params, frozenset({"percent", "hours_before_close"}))
    percent = params["percent"]
    hours = params["hours_before_close"]
    if not _is_int(percent) or not 1 <= percent <= 100:
        _refuse()
    if not _is_int(hours) or not 0 <= hours <= 168:
        _refuse()


def _no_params(params: dict[str, Any]) -> None:
    _exact_keys(params, frozenset())


def _dated(params: dict[str, Any]) -> None:
    _exact_keys(params, frozenset({"date"}))
    value = params["date"]
    if not isinstance(value, str) or _DAY.fullmatch(value) is None:
        _refuse()
    try:
        date.fromisoformat(value)
    except ValueError:
        # 2026-02-30 matches the shape but is not a day the server can compare against.
        _refuse()


_PREDICATES: Final[dict[str, Callable[[dict[str, Any]], None]]] = {
    "PRICE_ABOVE": _price_above,
    "FUNDING_BELOW": _funding_below,
    "BLOCKING_FLAG_ON_AWARD": _no_params,
    "DELIVERY_AFTER": _dated,
    "NO_AWARD_BY": _dated,
}

#: The closed vocabulary, exposed for the card's editor and its tests.
PREDICATES: Final[frozenset[str]] = frozenset(_PREDICATES)


def validate_conditions(
    conditions: object, *, ratification_sha256: str | None
) -> list[dict[str, Any]]:
    """Return the conditions re-shaped to the stored form, or refuse the whole set.

    ``ratification_sha256`` is required: a condition without the buyer's hash is an
    unratified rule, and minting a token from it would be exactly the gap CR-14 closes.
    """
    if ratification_sha256 is None:
        _refuse()
    if not isinstance(conditions, list):
        _refuse()
    if len(conditions) > MAX_CONDITIONS:
        _refuse()
    validated: list[dict[str, Any]] = []
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != _CONDITION_KEYS:
            _refuse()
        predicate = condition["predicate"]
        action = condition["action"]
        params = condition["params"]
        check = _PREDICATES.get(predicate) if isinstance(predicate, str) else None
        if check is None or action not in ACTIONS or not isinstance(params, dict):
            _refuse()
        check(params)
        validated.append({"predicate": predicate, "params": params, "action": action})
    return validated


def ratified_mandate(scope: Mapping[str, Any]) -> dict[str, Any]:
    """The three mandate keys of a scope, or ``{}`` when the buyer ratified nothing.

    They survive together or not at all: without a ratification hash the conditions are
    dropped (``db-schema.md``, and the persistence tests that pin that reading), because
    nothing distinguishes them from a caller attaching rules to a token nobody ratified.
    """
    sha = scope.get("ratification_sha256")
    if sha is None:
        return {}
    if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
        _refuse()
    mandate: dict[str, Any] = {"ratification_sha256": sha}
    version = scope.get("mandate_version")
    if version is not None:
        mandate["mandate_version"] = version
    conditions = scope.get("conditions")
    if conditions is not None:
        mandate["conditions"] = validate_conditions(conditions, ratification_sha256=sha)
    return mandate
