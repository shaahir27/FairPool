"""Seeded, deterministic simulation plan (T08B04; FR-AI-03, FR-SM-01).

Nothing here touches the database, the network or a model. ``random.Random(seed)``
decides every variable field (caps, salts, sample messages) and ``uuid5`` derives
every identifier from the seed plus the run's pool id, so two runs with the same
seed produce the same plan while two pools never share synthetic users, entries or
merchants.

The plan is the measured path: 10,000 entries are ranked and assigned by the pure
``domain.fairness.assign_lots`` with no AI call, job enqueue or provider traffic in
between (I12). Message text variety is produced later, by the handler, for a bounded
sample only, and is stored in ``sim_runs.results`` rather than in any buyer-visible
surface.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID, uuid5

from fairpool.domain import fairness, hashing

#: The most model-generated text samples one run keeps; they are never on the timed path.
SIM_SAMPLES: Final[int] = 20

#: Generic catalog values only: demo data carries no brand names (FR-HK-06).
PRODUCT_KEY: Final[str] = "sim-monitor-27-4k"
PRODUCT_TITLE: Final[str] = "27-inch 4K monitor"

#: Fixed UTC window: a simulation never depends on the application clock (I15).
OPEN_AT: Final[str] = "2030-01-01T00:00:00.000000Z"
CLOSE_AT: Final[str] = "2030-01-02T00:00:00.000000Z"
FUND_BY: Final[str] = "2030-01-03"

ZONES: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("US-EAST", "US East", ("NY", "NJ", "PA")),
    ("US-WEST", "US West", ("CA", "OR", "WA")),
    ("US-CENTRAL", "US Central", ("IL", "OH", "MI")),
    ("US-SOUTH", "US South", ("TX", "FL", "GA")),
)


@dataclass(frozen=True)
class SimBuyer:
    id: UUID
    email: str
    display_name: str


@dataclass(frozen=True)
class SimMerchant:
    id: UUID
    user_id: UUID
    email: str
    display_name: str


@dataclass(frozen=True)
class SimEntry:
    id: UUID
    user_id: UUID
    zone_id: str
    cap_cents: int
    request_hash: str
    salt: str
    commitment: str
    submitted_via: str
    canonical_request: dict[str, Any]


@dataclass(frozen=True)
class SimMessage:
    kind: str
    facts: dict[str, Any]
    text: str


@dataclass(frozen=True)
class SimLot:
    id: UUID
    zone_id: str
    lot_index: int
    lot_order: int
    seats: int
    min_seats: int
    status: str


@dataclass(frozen=True)
class PoolMeta:
    """The frozen pool document shape; cheap to build without the 10,000 entries."""

    title: str
    template: dict[str, Any]
    lot_plan: list[dict[str, Any]]
    timeline: dict[str, Any]


@dataclass(frozen=True)
class SimPlan:
    pool_id: UUID
    seed: int
    meta: PoolMeta
    buyers: tuple[SimBuyer, ...]
    merchants: tuple[SimMerchant, ...]
    entries: tuple[SimEntry, ...]
    messages: tuple[SimMessage, ...]
    zone_plan: tuple[fairness.ZoneLotPlan, ...]
    lots: tuple[SimLot, ...]
    signing_seed: bytes


def _namespace(pool_id: UUID) -> UUID:
    return uuid5(UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8"), f"fairpool/sim/{pool_id}")


def _lot_specs(count: int) -> list[tuple[int, int]]:
    """Two lots holding about 80% of a zone: one seated tranche and one waitlist tail.

    A lot smaller than its minimum is still written (``fairness`` cancels it), so the
    plan never invents a seat count. Tiny zones keep one lot and one waitlisted entry.
    """
    target = max(1, count * 4 // 5)
    if target >= 2:
        first = max(1, target // 2)
        second = target - first
        if second >= 1:
            return [(first, max(1, first // 2)), (second, max(1, second // 2))]
    return [(1, 1)]


def pool_metadata(*, entries: int, seed: int) -> PoolMeta:
    """The pool document for this run; depends on the entry count, not on their data."""
    zone_count = min(len(ZONES), max(1, entries))
    zones = ZONES[:zone_count]
    base, remainder = divmod(entries, zone_count)
    counts = [base + (1 if index < remainder else 0) for index in range(zone_count)]
    grouped: list[dict[str, Any]] = []
    for (zone_id, _, _), count in zip(zones, counts, strict=True):
        grouped.append(
            {
                "zone_id": zone_id,
                "lots": [
                    {"seats": seats, "min_seats": minimum} for seats, minimum in _lot_specs(count)
                ],
            }
        )
    return PoolMeta(
        title=f"Simulated group buy #{seed}",
        template={
            "product_key": PRODUCT_KEY,
            "variant": "black",
            "title": PRODUCT_TITLE,
            "condition": "NEW",
            "quantity": 1,
            "currency": "USD",
            "bundle_contents": ["monitor", "stand", "power cable"],
            "delivery_sla_days": 7,
            "fund_by": FUND_BY,
            "min_return_days": 14,
            "zones": [
                {"zone_id": zone_id, "label": label, "regions": list(regions)}
                for zone_id, label, regions in zones
            ],
        },
        lot_plan=grouped,
        timeline={
            "open_at": OPEN_AT,
            "close_at": CLOSE_AT,
            "beacon_delay_s": 10,
            "bid_window_s": 120,
            "offer_window_s": 180,
            "fund_deadline_s": 600,
            "capture_grace_s": 120,
            "pending_wait_s": 120,
            "max_refill_waves": 1,
            "authorization_age_guard_s": 216000,
        },
    )


def _sample_messages(
    rng: random.Random,
    *,
    entries: int,
    zone_id: str,
    cap_cents: int,
) -> tuple[SimMessage, ...]:
    """Twenty facts-only samples; the handler may turn them into model text afterwards."""
    messages: list[SimMessage] = []
    for index in range(SIM_SAMPLES):
        kind = "buyer_message" if index % 2 == 0 else "merchant_quote"
        facts = {
            "kind": kind,
            "product": PRODUCT_TITLE,
            "zone_id": zone_id,
            "cap_cents": cap_cents,
            "entry_count": entries,
            "sample": index + 1,
        }
        if kind == "buyer_message":
            text = (
                f"SIMULATED buyer message {index + 1}: wants one {PRODUCT_TITLE} "
                f"delivered to {zone_id} at a total of {cap_cents} cents or less."
            )
        else:
            text = (
                f"SIMULATED merchant quote {index + 1}: {PRODUCT_TITLE} for {entries} "
                f"buyers in {zone_id}, unit price {cap_cents} cents, seven-day delivery."
            )
        messages.append(SimMessage(kind=kind, facts=facts, text=text))
        rng.random()  # Keeps the message draw inside the seeded stream.
    return tuple(messages)


def build_plan(*, pool_id: UUID, entries: int, merchants: int, seed: int) -> SimPlan:
    """Build the whole deterministic plan for one pool (no I/O, no model call)."""
    if entries < 1 or merchants < 1:
        raise ValueError("entries and merchants must be positive")
    rng = random.Random(seed)
    namespace = _namespace(pool_id)
    meta = pool_metadata(entries=entries, seed=seed)

    buyers = tuple(
        SimBuyer(
            id=uuid5(namespace, f"buyer/{index}"),
            email=f"sim-buyer-{index}@{pool_id}.invalid",
            display_name=f"Simulated buyer {index + 1}",
        )
        for index in range(entries)
    )
    merchant_rows = tuple(
        SimMerchant(
            id=uuid5(namespace, f"merchant/{index}"),
            user_id=uuid5(namespace, f"merchant-user/{index}"),
            email=f"sim-merchant-{index}@{pool_id}.invalid",
            display_name=f"Simulated seller {index + 1}",
        )
        for index in range(merchants)
    )

    zone_count = len(meta.template["zones"])
    entry_rows: list[SimEntry] = []
    for index, buyer in enumerate(buyers):
        zone_id, _, regions = ZONES[index % zone_count]
        cap_cents = 45_000 + rng.randrange(0, 20_001)
        canonical = {
            "v": 1,
            "pool_id": str(pool_id),
            "product_key": PRODUCT_KEY,
            "variant": "black",
            "condition": "NEW",
            "quantity": 1,
            "currency": "USD",
            "delivery": {
                "zone_id": zone_id,
                "region": regions[index % len(regions)],
                "country": "US",
            },
            "required_by": "2030-02-01",
            "max_total_cents": cap_cents,
            "firm": [],
            "preferences": [],
        }
        request_digest = hashing.request_hash(canonical)
        salt = f"{rng.getrandbits(256):064x}"
        entry_id = uuid5(namespace, f"entry/{index}")
        entry_rows.append(
            SimEntry(
                id=entry_id,
                user_id=buyer.id,
                zone_id=zone_id,
                cap_cents=cap_cents,
                request_hash=request_digest,
                salt=salt,
                commitment=hashing.commitment(str(pool_id), str(entry_id), request_digest, salt),
                submitted_via="agent" if index % 5 == 0 else "human",
                canonical_request=canonical,
            )
        )

    zone_plan = tuple(
        fairness.ZoneLotPlan(
            zone_id=str(zone["zone_id"]),
            lots=tuple(
                fairness.LotSpec(seats=int(lot["seats"]), min_seats=int(lot["min_seats"]))
                for lot in zone["lots"]
            ),
        )
        for zone in meta.lot_plan
    )
    lots = tuple(
        SimLot(
            id=uuid5(namespace, f"lot/{zone_id}/{index}"),
            zone_id=zone_id,
            lot_index=index,
            lot_order=order,
            seats=int(lot["seats"]),
            min_seats=int(lot["min_seats"]),
            status="PLANNED",
        )
        for order, (zone_id, index, lot) in enumerate(
            (
                (str(zone["zone_id"]), index, lot)
                for zone in meta.lot_plan
                for index, lot in enumerate(zone["lots"])
            ),
            start=1,
        )
    )
    first_cap = entry_rows[0].cap_cents if entry_rows else 45_000
    return SimPlan(
        pool_id=pool_id,
        seed=seed,
        meta=meta,
        buyers=buyers,
        merchants=merchant_rows,
        entries=tuple(entry_rows),
        messages=_sample_messages(
            rng,
            entries=entries,
            zone_id=str(meta.template["zones"][0]["zone_id"]),
            cap_cents=first_cap,
        ),
        zone_plan=zone_plan,
        lots=lots,
        # A simulation receipt is signed with a run-derived seed, never the live
        # RECEIPT_SIGNING_KEY; it is internal and never published as a live receipt.
        signing_seed=hashlib.sha256(f"fairpool/sim-signing/v1|{pool_id}".encode()).digest(),
    )


def owner_id(pool_id: UUID) -> UUID:
    """The synthetic admin who owns the pool row (``pools.created_by`` is NOT NULL)."""
    return uuid5(_namespace(pool_id), "owner")


def allocation_id(pool_id: UUID, entry_id: UUID) -> UUID:
    """A stable allocation id: one seat row per entry, never a random rewrite."""
    return uuid5(_namespace(pool_id), f"allocation/{entry_id}")


__all__ = [
    "SIM_SAMPLES",
    "PoolMeta",
    "SimBuyer",
    "SimEntry",
    "SimLot",
    "SimMerchant",
    "SimMessage",
    "SimPlan",
    "allocation_id",
    "build_plan",
    "owner_id",
    "pool_metadata",
]
