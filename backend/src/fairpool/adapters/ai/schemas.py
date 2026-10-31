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
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("ISO date required")
        return value


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
