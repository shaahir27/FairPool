"""CR-11 / T04A04: the drand adapter announces a round and fetches only that round.

These tests exercise the real adapter against a mocked transport, which is the
only way to pin the three rules the fake could not: the round is chosen from the
chain's own parameters, an unresolved round is a wait rather than a failure, and
a round that had already resolved before the close window is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from fairpool.adapters.beacon.announcement import BeaconAnnouncement
from fairpool.domain.errors import ApplicationError

CHAIN = "8990e7a9aaed2ffed73dbd7092123d6f2899305ba17c255582341577d6d2a3d3"
BASE = "https://api.drand.sh"
GENESIS = 1_000_000
PERIOD = 30


def make_adapter(
    responses: dict[str, tuple[int, Any] | Exception],
) -> BeaconAnnouncement:
    """A beacon adapter whose HTTP calls answer from ``responses`` by path suffix."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for suffix, answer in responses.items():
            if path.endswith(suffix):
                if isinstance(answer, Exception):
                    raise answer
                status, body = answer
                if body is None:
                    return httpx.Response(status)
                return httpx.Response(status, json=body)
        raise AssertionError(f"unexpected beacon call {path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return BeaconAnnouncement(mode="drand", base_url=BASE, chain_hash=CHAIN, client=client)


def info(period: int = PERIOD, genesis: int = GENESIS) -> dict[str, Any]:
    return {"hash": CHAIN, "period": period, "genesis_time": genesis}


def announced(round_number: int, not_before: int) -> dict[str, Any]:
    return {"source": "drand", "chain_hash": CHAIN, "round": round_number, "not_before": not_before}


async def test_demo_mode_announces_no_round() -> None:
    adapter = BeaconAnnouncement(mode="demo", base_url=BASE, chain_hash=CHAIN)
    close = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert await adapter.announce(close_at=close, delay_s=10) == {"source": "demo"}


async def test_announce_picks_the_first_round_at_or_after_the_window() -> None:
    # not_before = 1_000_300 is exactly the schedule of round 11
    # (genesis + (11-1)*period), so the first round at or after it is 11.
    close = datetime.fromtimestamp(1_000_290, tz=UTC)
    adapter = make_adapter({"/info": (200, info())})
    result = await adapter.announce(close_at=close, delay_s=10)
    assert result["not_before"] == 1_000_300
    assert result["round"] == 11
    assert result["chain_hash"] == CHAIN


async def test_announce_refuses_a_chain_that_does_not_describe_itself() -> None:
    wrong = {"hash": "00" * 32, "period": PERIOD, "genesis_time": GENESIS}
    adapter = make_adapter({"/info": (200, wrong)})
    with pytest.raises(ApplicationError) as failure:
        await adapter.announce(close_at=datetime.fromtimestamp(1_000_290, tz=UTC), delay_s=10)
    assert failure.value.code == "INTEGRITY_ERROR"


async def test_fetch_returns_the_announced_round_value() -> None:
    body = {"round": 11, "randomness": "ab" * 32, "signature": "cd" * 96}
    adapter = make_adapter({"/info": (200, info()), "/pub/11": (200, body)})
    fetched = await adapter.fetch(announced(11, 1_000_300))
    assert fetched == {"round": 11, "randomness": "ab" * 32, "signature": "cd" * 96}


async def test_fetch_waits_when_the_round_is_not_published_yet() -> None:
    adapter = make_adapter({"/info": (200, info()), "/pub/11": (404, None)})
    assert await adapter.fetch(announced(11, 1_000_300)) is None


async def test_fetch_waits_when_the_endpoint_is_unreachable() -> None:
    # F27: an outage is a wait. Raising here used to dead-end the pool.seed job
    # at FAILED after eight attempts and strand a closed pool with no draw.
    adapter = make_adapter({"/info": httpx.ConnectError("beacon down")})
    assert await adapter.fetch(announced(11, 1_000_300)) is None


async def test_fetch_refuses_a_round_that_resolved_before_the_close_window() -> None:
    # genesis 1_000_000 + (11-1)*30 = 1_000_300 scheduled; 1_000_400 is later, so
    # the announced round resolved before the window opened.
    body = {"round": 11, "randomness": "ab" * 32, "signature": "cd" * 96}
    adapter = make_adapter({"/info": (200, info()), "/pub/11": (200, body)})
    with pytest.raises(ApplicationError) as failure:
        await adapter.fetch(announced(11, 1_000_400))
    assert failure.value.code == "INTEGRITY_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        {"round": 12, "randomness": "ab" * 32, "signature": "cd" * 96},
        {"round": 11, "randomness": "not-hex", "signature": "cd" * 96},
        {"round": 11, "randomness": "AB" * 32, "signature": "cd" * 96},
        {"round": 11, "randomness": "ab" * 32, "signature": ""},
        {"randomness": "ab" * 32, "signature": "cd" * 96},
    ],
)
async def test_fetch_refuses_a_body_that_is_not_the_announced_round(body: dict[str, Any]) -> None:
    adapter = make_adapter({"/info": (200, info()), "/pub/11": (200, body)})
    with pytest.raises(ApplicationError) as failure:
        await adapter.fetch(announced(11, 1_000_300))
    assert failure.value.code == "INTEGRITY_ERROR"


async def test_fetch_refuses_an_announcement_without_a_round_number() -> None:
    adapter = make_adapter({"/info": (200, info())})
    with pytest.raises(ApplicationError):
        await adapter.fetch({"source": "drand", "chain_hash": CHAIN})
