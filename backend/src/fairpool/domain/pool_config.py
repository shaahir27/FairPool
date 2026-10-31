"""Closed nested configuration for operator-defined pools."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Positive = Annotated[int, Field(gt=0, le=1000000)]
Nonnegative = Annotated[int, Field(ge=0, le=1000000)]
Text = Annotated[str, Field(min_length=1, max_length=200)]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Zone(Closed):
    zone_id: Text
    label: Text
    regions: list[Annotated[str, Field(pattern=r"^[A-Z]{2}$")]] = Field(min_length=1, max_length=60)


class Template(Closed):
    product_key: Text
    variant: Text | None = None
    title: Text
    condition: Literal["NEW", "REFURBISHED", "OPEN_BOX"]
    quantity: Annotated[int, Field(strict=True, ge=1, le=1)]
    currency: Literal["USD"]
    bundle_contents: list[Text] = Field(min_length=1, max_length=30)
    delivery_sla_days: Positive
    fund_by: str
    min_return_days: Nonnegative
    zones: list[Zone] = Field(min_length=1, max_length=60)

    @field_validator("fund_by")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("ISO date required")
        return value


class LotSize(Closed):
    seats: Positive
    min_seats: Positive

    @model_validator(mode="after")
    def sizes(self) -> LotSize:
        if self.min_seats > self.seats:
            raise ValueError("Minimum seats exceeds capacity")
        return self


class ZonePlan(Closed):
    zone_id: Text
    lots: list[LotSize] = Field(min_length=1, max_length=100)


class Timeline(Closed):
    open_at: datetime
    close_at: datetime
    beacon_delay_s: Positive = 10
    bid_window_s: Positive = 120
    offer_window_s: Positive = 180
    fund_deadline_s: Positive = 600
    capture_grace_s: Positive = 120
    pending_wait_s: Positive = 120
    max_refill_waves: Nonnegative = 1
    authorization_age_guard_s: Positive = 216000

    @field_validator("open_at", "close_at", mode="before")
    @classmethod
    def utc_timestamp(cls, value: object) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
            raise ValueError("UTC timestamp required")
        return value

    @model_validator(mode="after")
    def ordering(self) -> Timeline:
        if self.open_at >= self.close_at:
            raise ValueError("Close must follow open")
        if self.authorization_age_guard_s >= 259200:
            raise ValueError("Authorization age guard must stay inside honor period")
        return self


class PoolInput(Closed):
    title: Text
    template: Template
    lot_plan: list[ZonePlan] = Field(min_length=1, max_length=60)
    timeline: Timeline
    require_paypal_link: bool = True
    rule_version: Literal["allocation_v1"] = "allocation_v1"

    @model_validator(mode="after")
    def relationships(self) -> PoolInput:
        if date.fromisoformat(self.template.fund_by) < self.timeline.close_at.date():
            raise ValueError("Funding date cannot precede pool close")
        zones = [z.zone_id for z in self.template.zones]
        regions = [r for z in self.template.zones for r in z.regions]
        plans = [p.zone_id for p in self.lot_plan]
        if len(set(zones)) != len(zones) or len(set(regions)) != len(regions):
            raise ValueError("Zones and regions must be unique")
        if len(set(plans)) != len(plans) or set(plans) != set(zones):
            raise ValueError("Each zone needs exactly one lot plan")
        return self


TIMING_PROFILES = {
    "demo": {},
    "prodlike": {
        "beacon_delay_s": 30,
        "bid_window_s": 3600,
        "offer_window_s": 900,
        "fund_deadline_s": 172800,
        "capture_grace_s": 3600,
        "pending_wait_s": 86400,
        "max_refill_waves": 3,
        "authorization_age_guard_s": 216000,
    },
}
