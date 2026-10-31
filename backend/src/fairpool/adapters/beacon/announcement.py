"""Announce a future drand round; verification is a later-phase responsibility."""

import math
from datetime import datetime
from typing import Any

import httpx


class BeaconAnnouncement:
    def __init__(self, *, mode: str, base_url: str, chain_hash: str) -> None:
        self.mode, self.base_url, self.chain_hash = mode, base_url, chain_hash

    async def announce(self, *, close_at: datetime, delay_s: int) -> dict[str, Any]:
        if self.mode == "demo":
            return {"source": "demo"}
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(self.base_url.rstrip("/") + "/" + self.chain_hash + "/info")
            response.raise_for_status()
            info = response.json()
        if (
            info.get("hash") != self.chain_hash
            or type(info.get("period")) is not int
            or info["period"] <= 0
            or type(info.get("genesis_time")) is not int
        ):
            raise ValueError("Invalid drand chain announcement")
        round_number = max(
            1,
            math.ceil((close_at.timestamp() + delay_s - info["genesis_time"]) / info["period"]) + 1,
        )
        return {"source": "drand", "chain_hash": self.chain_hash, "round": round_number}

    async def fetch(self, announced: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Full beacon retrieval and verification are scheduled later")
