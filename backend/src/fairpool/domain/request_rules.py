"""The deterministic manual-request validator (api.md "Intake"/"Entry", CR-3).

Pure module: no I/O and no SQLAlchemy, so the same rules back unit, integration
and close-time re-validation tests. It is the only gate a confirmed request must
pass; AI output never reaches it directly (the AI proposes, this decides).

Every decision is fail-closed: an unsupported firm term, a float-shaped money
value or a region outside the frozen zones is a ``VALIDATION_ERROR``, never a
guess. A stored canonical request that no longer satisfies the rules is an
``INTEGRITY_ERROR`` (an auditability break, not a user mistake).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, NoReturn

from .errors import ApplicationError
from .hashing import request_hash as _request_hash

CANONICAL_VERSION = 1
_MAX_TERMS = 30
_MAX_TERM_LENGTH = 200


@dataclass(frozen=True)
class ValidatedRequest:
    """The canonical bytes, their hash, the buyer cap and the resolved zone."""

    canonical: dict[str, Any]
    request_hash: str
    cap_cents: int
    zone_id: str


def _fail() -> NoReturn:
    raise ApplicationError("VALIDATION_ERROR")


def _template_zones(template: dict[str, Any]) -> dict[str, list[str]]:
    """Return ``{zone_id: regions}`` from the frozen template, or fail closed."""
    raw_zones = template.get("zones")
    if not isinstance(raw_zones, list) or not raw_zones:
        _fail()
    zones: dict[str, list[str]] = {}
    for zone in raw_zones:
        if not isinstance(zone, dict):
            _fail()
        zone_id = zone.get("zone_id")
        regions = zone.get("regions")
        if (
            not isinstance(zone_id, str)
            or not zone_id
            or zone_id in zones
            or not isinstance(regions, list)
            or not regions
            or not all(isinstance(region, str) and region for region in regions)
        ):
            _fail()
        zones[zone_id] = list(regions)
    return zones


def _supported_firm_terms(template: dict[str, Any]) -> set[str]:
    """What the template provides: bundle contents plus optional explicit terms.

    db-schema.md: ``firm`` must be a subset of what the template provides. The
    template shape carries no dedicated firm-terms key, so a term is supported
    only when it names a bundle item or appears in an optional ``firm_terms``
    list; anything else is rejected rather than guessed (fail closed).
    """
    supported: set[str] = set()
    for key in ("bundle_contents", "firm_terms"):
        raw = template.get(key)
        if isinstance(raw, list):
            supported.update(item for item in raw if isinstance(item, str))
    return supported


def _require_term_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        _fail()
    terms: list[str] = []
    for term in value:
        if not isinstance(term, str) or not 1 <= len(term) <= _MAX_TERM_LENGTH:
            _fail()
        if term != term.strip():
            _fail()
        terms.append(term)
    if len({term.lower() for term in terms}) != len(terms):
        _fail()  # case-folded duplicates would hide a double requirement
    return terms


def _latest_delivery(template: dict[str, Any]) -> dt.date:
    fund_by = template.get("fund_by")
    sla = template.get("delivery_sla_days")
    if not isinstance(fund_by, str) or not isinstance(sla, int) or isinstance(sla, bool) or sla < 0:
        _fail()
    try:
        start = dt.date.fromisoformat(fund_by)
    except ValueError:
        _fail()
    return start + dt.timedelta(days=sla)


def _validate_common(
    template: dict[str, Any], region: object, required_by: object, cap: object
) -> tuple[str, str, int]:
    """Check identity, zone, date and money rules shared by both entry points.

    Returns ``(zone_id, required_by_text, cap_cents)``; fails closed otherwise.
    """
    # Product identity is the template's: the payload can only agree with it.
    if template.get("currency") != "USD":
        _fail()
    if template.get("quantity") != 1:
        _fail()
    product_key = template.get("product_key")
    condition = template.get("condition")
    variant = template.get("variant")
    if not isinstance(product_key, str) or not product_key:
        _fail()
    if not isinstance(condition, str) or not condition:
        _fail()
    if variant is not None and not isinstance(variant, str):
        _fail()

    zones = _template_zones(template)
    if not isinstance(region, str) or not region:
        _fail()
    matched = [zone_id for zone_id, regions in zones.items() if region in regions]
    if len(matched) != 1:
        # Ambiguous or unknown region: ask, never guess (FR-IN-05 semantics).
        _fail()
    zone_id = matched[0]

    # Absolute date only: no relative wording, and the pool must be able to deliver.
    if not isinstance(required_by, str):
        _fail()
    try:
        parsed = dt.date.fromisoformat(required_by)
    except ValueError:
        _fail()
    if parsed.isoformat() != required_by or parsed < _latest_delivery(template):
        _fail()

    # Integer cents only (BD-14); a float-shaped cap is a rejection, not a conversion.
    if isinstance(cap, bool) or not isinstance(cap, int):
        _fail()
    if cap <= 0:
        _fail()
    cap_min = template.get("cap_min_cents")
    cap_max = template.get("cap_max_cents")
    if isinstance(cap_min, int) and not isinstance(cap_min, bool) and cap < cap_min:
        _fail()
    if isinstance(cap_max, int) and not isinstance(cap_max, bool) and cap > cap_max:
        _fail()
    return zone_id, required_by, cap


def _canonical(
    template: dict[str, Any],
    pool_id: str,
    zone_id: str,
    region: str,
    required_by: str,
    cap_cents: int,
    firm: list[str],
    preferences: list[str],
) -> dict[str, Any]:
    return {
        "v": CANONICAL_VERSION,
        "pool_id": pool_id,
        "product_key": template.get("product_key"),
        "variant": template.get("variant"),
        "condition": template.get("condition"),
        "quantity": 1,
        "currency": "USD",
        "delivery": {"zone_id": zone_id, "region": region, "country": "US"},
        "required_by": required_by,
        "max_total_cents": cap_cents,
        "firm": firm,
        "preferences": preferences,
    }


def validate_manual_request(template: dict[str, Any], payload: dict[str, Any]) -> ValidatedRequest:
    """Validate a manual-form payload against the frozen pool template.

    The payload carries only buyer-chosen fields (``api.md`` manual intake):
    ``delivery.region``, ``required_by``, ``max_total_cents``, ``firm`` and
    ``preferences``. Product identity, condition, quantity and currency come
    from the template; if the payload repeats them they must agree exactly.
    Raises ``ApplicationError("VALIDATION_ERROR")`` on any deviation.
    """
    if not isinstance(payload, dict):
        _fail()
    allowed = {"delivery", "required_by", "max_total_cents", "firm", "preferences"}
    optional_identity = {"product_key", "variant", "condition", "quantity", "currency"}
    if set(payload) - allowed - optional_identity:
        _fail()
    for key in ("delivery", "required_by", "max_total_cents", "firm", "preferences"):
        if key not in payload:
            _fail()
    # Repeating template identity fields is only legal when they match exactly:
    # a mismatch is an unsupported product request, never a silent change.
    for key in optional_identity & set(payload):
        if payload[key] != template.get(key):
            _fail()

    delivery = payload["delivery"]
    if not isinstance(delivery, dict) or set(delivery) != {"region"}:
        _fail()
    region = delivery["region"]
    zone_id, required_by, cap_cents = _validate_common(
        template, region, payload["required_by"], payload["max_total_cents"]
    )
    firm_terms = _require_term_list(payload["firm"], limit=_MAX_TERMS)
    supported = _supported_firm_terms(template)
    if any(term not in supported for term in firm_terms):
        _fail()
    preferences = _require_term_list(payload["preferences"], limit=_MAX_TERMS)

    pool_id = template.get("pool_id")
    if not isinstance(pool_id, str) or not pool_id:
        _fail()
    canonical = _canonical(
        template,
        pool_id,
        zone_id,
        str(region),
        required_by,
        cap_cents,
        firm_terms,
        preferences,
    )
    return ValidatedRequest(
        canonical=canonical,
        request_hash=_request_hash(canonical),
        cap_cents=cap_cents,
        zone_id=zone_id,
    )


def revalidate_canonical(
    template: dict[str, Any], canonical: dict[str, Any], request_hash: str
) -> None:
    """Re-run every rule over the stored canonical bytes (CR-3).

    A stored record that no longer matches its own hash or the frozen template
    is an integrity break: ``ApplicationError("INTEGRITY_ERROR")``, never a
    silent rejection and never an invented repair.
    """
    try:
        _revalidate(template, canonical, request_hash)
    except ApplicationError as exc:
        if exc.code == "VALIDATION_ERROR":
            raise ApplicationError("INTEGRITY_ERROR") from None
        raise


def _revalidate(template: dict[str, Any], canonical: dict[str, Any], request_hash: str) -> None:
    if not isinstance(canonical, dict):
        _fail()
    expected_keys = {
        "v",
        "pool_id",
        "product_key",
        "variant",
        "condition",
        "quantity",
        "currency",
        "delivery",
        "required_by",
        "max_total_cents",
        "firm",
        "preferences",
    }
    if set(canonical) != expected_keys or canonical.get("v") != CANONICAL_VERSION:
        _fail()
    if canonical.get("quantity") != 1:
        _fail()
    if canonical.get("currency") != "USD":
        _fail()
    pool_id = canonical.get("pool_id")
    if not isinstance(pool_id, str) or pool_id != template.get("pool_id"):
        _fail()
    for key in ("product_key", "condition", "variant"):
        if canonical.get(key) != template.get(key):
            _fail()
    delivery = canonical.get("delivery")
    if not isinstance(delivery, dict) or set(delivery) != {"zone_id", "region", "country"}:
        _fail()
    if delivery.get("country") != "US":
        _fail()
    region = delivery["region"]
    zone_id, required_by, cap_cents = _validate_common(
        template, region, canonical.get("required_by"), canonical.get("max_total_cents")
    )
    if delivery.get("zone_id") != zone_id:
        _fail()
    if not isinstance(canonical.get("firm"), list) or not isinstance(
        canonical.get("preferences"), list
    ):
        _fail()
    stored_firm = _require_term_list(canonical["firm"], limit=_MAX_TERMS)
    supported = _supported_firm_terms(template)
    if any(term not in supported for term in stored_firm):
        _fail()
    stored_preferences = _require_term_list(canonical["preferences"], limit=_MAX_TERMS)
    rebuilt = _canonical(
        template,
        pool_id,
        zone_id,
        str(region),
        required_by,
        cap_cents,
        stored_firm,
        stored_preferences,
    )
    if canonical != rebuilt:
        _fail()
    # The hash column is CHAR(64): a stored digest that no longer equals the
    # SHA-256 of these bytes means the record was rewritten after it froze.
    if request_hash != _request_hash(canonical):
        _fail()
