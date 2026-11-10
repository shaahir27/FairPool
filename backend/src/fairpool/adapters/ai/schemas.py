"""Closed production schemas and strict JSON decoding for Gemini proposals."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "phase2-v1"
Amount = Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$", max_length=16)]
Positive = Annotated[int, Field(gt=0, le=1000000)]
Condition = Literal["NEW", "REFURBISHED", "OPEN_BOX"]
Text = Annotated[str, Field(max_length=4000)]

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_WORD = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_NTH = r"(?:st|nd|rd|th)?"


def _iso(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def stated_dates(text: str) -> set[str]:
    """Absolute calendar dates the text states, canonicalised to ISO.

    ISO, "Nov 30, 2026" and "30 November 2026" name one day each and are read.
    "11/30/2026" is not: a US reader and a European reader disagree about which
    number is the day, so it grounds nothing and the buyer is asked instead.
    A weekday or a relative phrase is not a date at all (ai-schemas.md 2).
    """
    found: set[str] = set()
    for year, month, day in re.findall(r"\b(\d{4})-(\d{2})-(\d{2})(?![0-9])", text):
        value = _iso(int(year), int(month), int(day))
        if value is not None:
            found.add(value)
    forms = (
        # month name first: "Nov 30, 2026"
        (rf"\b({_MONTH_WORD})\.?\s+(\d{{1,2}}){_NTH},?\s+(\d{{4}})\b", 0, 1, 2),
        # day first: "30 November 2026"
        (rf"\b(\d{{1,2}}){_NTH}\s+(?:of\s+)?({_MONTH_WORD}),?\s+(\d{{4}})\b", 1, 0, 2),
    )
    for pattern, month_at, day_at, year_at in forms:
        for groups in re.findall(pattern, text, re.I):
            month = _MONTHS.get(str(groups[month_at])[:3].lower())
            value = (
                _iso(int(groups[year_at]), month, int(groups[day_at]))
                if month is not None
                else None
            )
            if value is not None:
                found.add(value)
    return found


def _one_stated_date(value: str | None) -> str | None:
    """The single absolute day ``value`` names, or null.

    A written date the server can read is normalised; a weekday or another relative
    phrase is not a value this system may copy, so it becomes null and the pipeline asks
    (section 2.6, FR-IN-02). Returning null rather than raising is deliberate: raising
    used to throw away a whole proposal over one unresolved field.
    """
    if value is None:
        return None
    found = stated_dates(value)
    return next(iter(found)) if len(found) == 1 else None


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Ambiguity(Closed):
    field: Text
    question: Text


class Delivery(Closed):
    region: Text | None


class Money(Closed):
    amount: Amount | None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None


class Intake(Closed):
    pool_id: str | None
    match_confidence: Literal["high", "medium", "low", "none"]
    condition: Condition | None
    quantity: Annotated[int, Field(strict=True, ge=1, le=1)]
    delivery: Delivery
    required_by: str | None
    max_total: Money
    firm_requirements: list[Text] = Field(max_length=30)
    preferences: list[Text] = Field(max_length=30)
    ambiguities: list[Ambiguity] = Field(max_length=30)
    clarifying_question: Text | None

    @field_validator("required_by")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        """The field is one absolute day, canonicalised, or null (ai-schemas.md 2)."""
        return _one_stated_date(value)


class Tier(Closed):
    min_qty: Positive
    item_price: Amount


class Tax(Closed):
    mode: Literal["INCLUDED", "RATE_TABLE"] | None
    rate_bps_by_region: dict[str, Annotated[int, Field(ge=0, le=10000)]]


class Quote(Closed):
    product_text: Text | None
    condition: Condition | None
    bundle_contents: list[Text] = Field(max_length=30)
    capacity: Positive | None
    target_quantity: Positive | None
    moq: Positive | None
    tiers: list[Tier] = Field(max_length=30)
    shipping_by_zone: dict[str, Amount]
    tax: Tax
    delivery_sla_days: Positive | None
    returns_days: Annotated[int, Field(ge=0, le=1000000)] | None
    valid_until: str | None
    total_capacity: Positive | None
    evidence_note: Text | None
    ambiguities: list[Ambiguity] = Field(max_length=30)

    @field_validator("valid_until", mode="before")
    @classmethod
    def date_only_until_end_of_day(cls, value: object) -> object:
        """A model that answers "valid until 2026-12-01" means through that day (UTC).

        The contract asks for a timestamp; Gemini commonly omits the time. Normalising
        here keeps the stored value timezone-aware instead of discarding the whole
        proposal, which a live merchant quote hit on 2026-11-10.
        """
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            return f"{value.strip()}T23:59:59Z"
        return value

    @model_validator(mode="after")
    def relationships(self) -> Quote:
        if self.moq and self.capacity and self.moq > self.capacity:
            raise ValueError("MOQ exceeds capacity")
        if self.target_quantity and self.capacity and self.target_quantity > self.capacity:
            raise ValueError("Target exceeds capacity")
        if self.total_capacity and self.capacity and self.total_capacity < self.capacity:
            raise ValueError("Total capacity below lot capacity")
        quantities = [t.min_qty for t in self.tiers]
        if quantities != sorted(set(quantities)):
            raise ValueError("Tier minimums must strictly increase")
        if self.valid_until is not None:
            parsed = datetime.fromisoformat(self.valid_until.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Timestamp needs timezone")
        return self


class Flag(Closed):
    code: Literal[
        "BUNDLE_MISMATCH",
        "CONDITION_MISMATCH",
        "DELIVERY_CONFLICT",
        "HIDDEN_FEE",
        "QUANTITY_CONFLICT",
        "RETURN_CONFLICT",
        "OTHER",
    ]
    severity: Literal["BLOCKING", "WARNING"]
    field: Annotated[str, Field(min_length=1, max_length=100)]
    snippet: Annotated[str, Field(min_length=1, max_length=200)]


class Reconcile(Closed):
    consistent: bool
    flags: list[Flag] = Field(max_length=30)

    @model_validator(mode="after")
    def consistency(self) -> Reconcile:
        if self.consistent and self.flags:
            raise ValueError("Consistent result cannot assert mismatch flags")
        return self


class Simulation(Closed):
    text: Annotated[str, Field(min_length=1, max_length=4000)]


# ---------------------------------------------------------------- MANDATE (CR-14)
#
# A closed vocabulary, enforced by the type system rather than by hand. Each predicate has
# its own params model, so a parameter set that does not belong to its predicate fails
# validation instead of being carried along. Adding a predicate means adding a member here
# and a rule the server can evaluate from stored rows only (ai-schemas.md section 9).

MandateAction = Literal["PROCEED", "REASK", "HALT"]


class PoolScope(Closed):
    """Which pools the agent may see; always narrower than the token it becomes."""

    pool_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(max_length=5)
    category: Annotated[str, Field(max_length=100)] | None


class PriceAboveParams(Closed):
    amount: Amount


class FundingBelowParams(Closed):
    percent: Annotated[int, Field(strict=True, ge=1, le=100)]
    hours_before_close: Annotated[int, Field(strict=True, ge=0, le=168)]


class NoParams(Closed):
    """``BLOCKING_FLAG_ON_AWARD`` takes no parameters; any key here is rejected."""


class DatedParams(Closed):
    date: str | None

    @field_validator("date")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        return _one_stated_date(value)


class PriceAbove(Closed):
    predicate: Literal["PRICE_ABOVE"]
    action: MandateAction
    params: PriceAboveParams


class FundingBelow(Closed):
    predicate: Literal["FUNDING_BELOW"]
    action: MandateAction
    params: FundingBelowParams


class BlockingFlagOnAward(Closed):
    predicate: Literal["BLOCKING_FLAG_ON_AWARD"]
    action: MandateAction
    params: NoParams


class DeliveryAfter(Closed):
    predicate: Literal["DELIVERY_AFTER"]
    action: MandateAction
    params: DatedParams


class NoAwardBy(Closed):
    predicate: Literal["NO_AWARD_BY"]
    action: MandateAction
    params: DatedParams


MandateCondition = Annotated[
    PriceAbove | FundingBelow | BlockingFlagOnAward | DeliveryAfter | NoAwardBy,
    Field(discriminator="predicate"),
]


class Mandate(Closed):
    """A proposed delegation mandate; the buyer ratifies it and the server mints the token.

    ``reserved`` is deliberately not a field here. ``extra="forbid"`` rejects a model that
    invents one, which is the whole mechanism behind "the model cannot alter the reserved
    acts": there is nowhere to put them, and the server stamps them afterwards.
    """

    pool_scope: PoolScope
    max_total: Money
    expires: str | None
    conditions: list[MandateCondition] = Field(max_length=5)
    ambiguities: list[Ambiguity] = Field(max_length=30)
    clarifying_question: Text | None

    @field_validator("expires")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        return _one_stated_date(value)


def strict_json(value: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON property")
            result[key] = item
        return result

    def nonfinite(value: str) -> None:
        raise ValueError("Non-finite JSON number")

    if len(value) > 32000:
        raise ValueError("Output too large")
    return json.loads(value, object_pairs_hook=pairs, parse_constant=nonfinite)


def cents(value: str) -> int:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError("Invalid monetary string")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))
