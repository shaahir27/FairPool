"""Announce a future drand round and fetch that round's value (T04A04, CR-11).

``announce`` commits to a round; ``fetch`` only ever returns the value that round
produced. The two together are what makes the draw auditable: FairPool cannot
choose a seed after seeing the entries, and it cannot accept a round that had
already resolved when the entry list was frozen.

Two limits are stated rather than hidden. The round's own publication time is
checked against ``not_before`` using chain parameters read fresh at fetch time,
so a spoofed announcement is caught, but the BLS signature over the round is
**not** verified -- this project permits no signing-verification dependency, so
``randomness`` is taken on trust from the configured endpoint. An outside auditor
holding the real drand public key can verify what FairPool here cannot. A
transport failure or an unresolved round is treated as "not available yet" and
returns ``None``, which keeps the F27 wait path instead of dead-ending the job.
"""

import math
import re
from datetime import datetime
from typing import Any

import httpx

from fairpool.domain.errors import ApplicationError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class BeaconAnnouncement:
    def __init__(
        self,
        *,
        mode: str,
        base_url: str,
        chain_hash: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.mode, self.base_url, self.chain_hash = mode, base_url, chain_hash
        # Injected in tests with httpx.MockTransport; absent in wiring, where each
        # call owns and closes its own client.
        self._client = client

    async def _get(self, suffix: str) -> httpx.Response:
        url = self.base_url.rstrip("/") + "/" + self.chain_hash + "/" + suffix
        if self._client is not None:
            return await self._client.get(url)
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            return await client.get(url)

    async def _info(self) -> dict[str, Any]:
        response = await self._get("info")
        response.raise_for_status()
        info = response.json()
        if (
            not isinstance(info, dict)
            or info.get("hash") != self.chain_hash
            or not isinstance(info.get("period"), int)
            or info["period"] <= 0
            or not isinstance(info.get("genesis_time"), int)
        ):
            raise ApplicationError("INTEGRITY_ERROR")
        return info

    async def announce(self, *, close_at: datetime, delay_s: int) -> dict[str, Any]:
        if self.mode == "demo":
            return {"source": "demo"}
        not_before = int(close_at.timestamp()) + int(delay_s)
        info = await self._info()
        # The first round scheduled at or after close_at + delay_s (fairness §4):
        # round r is scheduled at genesis_time + (r - 1) * period.
        round_number = max(
            1,
            math.ceil((not_before - info["genesis_time"]) / info["period"]) + 1,
        )
        return {
            "source": "drand",
            "chain_hash": self.chain_hash,
            "round": round_number,
            "not_before": not_before,
        }

    async def fetch(self, announced: dict[str, Any]) -> dict[str, Any] | None:
        round_number = announced.get("round")
        if not isinstance(round_number, int) or round_number < 1:
            raise ApplicationError("INTEGRITY_ERROR")
        try:
            info = await self._info()
            response = await self._get(f"pub/{round_number}")
        except httpx.HTTPError:
            # F27: "unavailable" includes "the network refused to answer". Waiting is
            # correct; failing here stranded a closed pool with no draw at all.
            return None
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("round") != round_number:
            raise ApplicationError("INTEGRITY_ERROR")
        randomness = body.get("randomness")
        if not isinstance(randomness, str) or _HEX64.fullmatch(randomness) is None:
            raise ApplicationError("INTEGRITY_ERROR")
        signature = body.get("signature")
        if not isinstance(signature, str) or not signature:
            raise ApplicationError("INTEGRITY_ERROR")
        # Recompute the schedule from parameters read now, never from the
        # announcement, so an announcement built against a spoofed info document
        # cannot pass a round that had already resolved before the close window.
        not_before = announced.get("not_before")
        round_time = info["genesis_time"] + (round_number - 1) * info["period"]
        if isinstance(not_before, int) and round_time < not_before:
            raise ApplicationError("INTEGRITY_ERROR")
        return {"round": round_number, "randomness": randomness, "signature": signature}
