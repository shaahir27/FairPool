"""Fixed-value beacon fake."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

DEFAULT_ANNOUNCED: dict[str, Any] = {
    "source": "drand",
    "chain_hash": "ab" * 32,
    "round": 1,
}
DEFAULT_RANDOMNESS = "cd" * 32
DEFAULT_SIGNATURE = "ef" * 64


@dataclass(frozen=True)
class AnnounceCall:
    close_at: datetime
    delay_s: int


@dataclass(frozen=True)
class FetchCall:
    announced: dict[str, Any]


class FakeBeacon:
    """Returns fixed announced and fetched values; can simulate unavailability."""

    def __init__(
        self,
        *,
        announced: dict[str, Any] | None = None,
        fetched: dict[str, Any] | None = None,
        available: bool = True,
    ) -> None:
        self.announced = dict(DEFAULT_ANNOUNCED if announced is None else announced)
        default_fetched = {
            **self.announced,
            "randomness": DEFAULT_RANDOMNESS,
            "signature": DEFAULT_SIGNATURE,
        }
        self.fetched = dict(default_fetched if fetched is None else fetched)
        self.available = available
        self.announce_calls: list[AnnounceCall] = []
        self.fetch_calls: list[FetchCall] = []

    async def announce(self, *, close_at: datetime, delay_s: int) -> dict[str, Any]:
        self.announce_calls.append(AnnounceCall(close_at=close_at, delay_s=delay_s))
        return dict(self.announced)

    async def fetch(self, announced: dict[str, Any]) -> dict[str, Any] | None:
        self.fetch_calls.append(FetchCall(announced=dict(announced)))
        if not self.available:
            return None
        return dict(self.fetched)
