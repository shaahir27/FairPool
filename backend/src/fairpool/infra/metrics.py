"""Prometheus counters, scrape-time gauges and the ``/metrics`` route (T08A05).

FR-OP-02 asks for structured logs, metrics and alerts covering four facts: rejected
transitions, amount mismatches, unknown provider outcomes and dead letters. The first
three are process-wide counters that the checkout code increments at the point where
the fact is known (``modules/checkout/engine.py``, ``authorize.py``,
``vault_charge.py``); the last is a gauge read from Postgres on every scrape, because
it describes stored rows rather than events this process remembers.

The route is returned as a plain Starlette ``Route`` on purpose: the application's
documented operation set is frozen by ``docs/contracts/api.md`` and
``tests/unit/test_api_contract.py``, so ``/metrics`` must not appear as an operation
in the parent OpenAPI document. ``create_app`` appends it exactly as it appends
``/mcp`` (``backend/src/fairpool/api/app.py``).

Metrics never carry identifiers, amounts or provider references: label values are
bounded enums (machine name, trigger name, funnel stage), so one order cannot create
an unbounded series and no buyer data reaches a metrics scraper (I13, I14).
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

logger: Final[logging.Logger] = logging.getLogger("fairpool.metrics")

CONTENT_TYPE: Final[str] = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(frozen=True)
class MetricSpec:
    """One metric family: its name, Prometheus type, help text and label names."""

    name: str
    kind: str
    help: str
    labels: tuple[str, ...] = ()


COUNTER_SPECS: Final[dict[str, MetricSpec]] = {
    "fairpool_transitions_rejected_total": MetricSpec(
        "fairpool_transitions_rejected_total",
        "counter",
        "State transitions the whitelist or a post-lock guard refused (I10).",
        ("entity", "trigger"),
    ),
    "fairpool_amount_mismatch_total": MetricSpec(
        "fairpool_amount_mismatch_total",
        "counter",
        "Provider amounts or payees that contradicted the stored award (I3, I4).",
        ("stage",),
    ),
    "fairpool_outcome_unknown_total": MetricSpec(
        "fairpool_outcome_unknown_total",
        "counter",
        "Provider outcomes that were neither success nor a definitive failure (I9).",
        ("stage",),
    ),
}

GAUGE_SPECS: Final[dict[str, MetricSpec]] = {
    "fairpool_dead_letters": MetricSpec(
        "fairpool_dead_letters",
        "gauge",
        "Failed jobs plus dead-lettered or rejected webhook events.",
    ),
    "fairpool_funnel_buyer_orders": MetricSpec(
        "fairpool_funnel_buyer_orders",
        "gauge",
        "Buyer orders currently in each funnel stage.",
        ("stage",),
    ),
}


def metric_names() -> frozenset[str]:
    """Every metric family this module can emit; ``test_alert_rules`` uses it."""
    return frozenset(COUNTER_SPECS) | frozenset(GAUGE_SPECS)


LabelKey = tuple[tuple[str, str], ...]
GaugeValue = Sequence[tuple[Mapping[str, str], float]]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels_text(labels: Mapping[str, str], order: tuple[str, ...]) -> str:
    if not order:
        return ""
    rendered = ",".join(f'{name}="{_escape(str(labels[name]))}"' for name in order)
    return "{" + rendered + "}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


class Counters:
    """Thread-safe monotonic counters, rendered in the Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, LabelKey], int] = {}

    def incr(self, name: str, **labels: str) -> None:
        """Increment one labelled series; unknown names or label sets are bugs."""
        spec = COUNTER_SPECS.get(name)
        if spec is None:
            raise ValueError(f"unknown counter: {name}")
        if set(labels) != set(spec.labels):
            raise ValueError(f"{name} expects labels {spec.labels}, got {tuple(sorted(labels))}")
        key = (name, tuple(sorted((key, str(value)) for key, value in labels.items())))
        with self._lock:
            self._values[key] = self._values.get(key, 0) + 1

    def value(self, name: str, **labels: str) -> int:
        key = (name, tuple(sorted((key, str(value)) for key, value in labels.items())))
        with self._lock:
            return self._values.get(key, 0)

    def reset(self) -> None:
        """Drop every series; tests use this so a scrape cannot see another test."""
        with self._lock:
            self._values.clear()

    def render_prometheus(self, gauges: Mapping[str, GaugeValue] | None = None) -> str:
        """Render counters and the gauges collected for this scrape."""
        with self._lock:
            snapshot = dict(self._values)
        lines: list[str] = []
        for name in sorted(COUNTER_SPECS):
            spec = COUNTER_SPECS[name]
            lines.append(f"# HELP {name} {spec.help}")
            lines.append(f"# TYPE {name} {spec.kind}")
            for (series_name, labels), value in sorted(snapshot.items()):
                if series_name != name:
                    continue
                label_map = dict(labels)
                label_text = _labels_text(label_map, spec.labels)
                lines.append(f"{name}{label_text} {value}")
        for name in sorted(GAUGE_SPECS):
            spec = GAUGE_SPECS[name]
            lines.append(f"# HELP {name} {spec.help}")
            lines.append(f"# TYPE {name} {spec.kind}")
            for labels, value in sorted(
                (gauges or {}).get(name, ()), key=lambda item: sorted(item[0].items())
            ):
                label_text = _labels_text(labels, spec.labels)
                lines.append(f"{name}{label_text} {_number(float(value))}")
        return "\n".join(lines) + "\n"


_COUNTERS: Final[Counters] = Counters()


def get_counters() -> Counters:
    """The process-wide counter registry the checkout hooks increment."""
    return _COUNTERS


async def collect_gauges(
    factory: async_sessionmaker[AsyncSession] | None,
) -> dict[str, list[tuple[dict[str, str], float]]]:
    """Read the stored gauges for one scrape; no session means no gauge samples."""
    if factory is None:
        return {}
    gauges: dict[str, list[tuple[dict[str, str], float]]] = {}
    try:
        async with factory() as session:
            order_rows = (
                await session.execute(
                    text(
                        "SELECT status::text AS stage, count(*) AS total "
                        "FROM buyer_orders GROUP BY status ORDER BY status"
                    )
                )
            ).all()
            gauges["fairpool_funnel_buyer_orders"] = [
                ({"stage": str(row.stage)}, float(row.total)) for row in order_rows
            ]
            dead = await session.scalar(
                text(
                    "SELECT (SELECT count(*) FROM jobs WHERE status = 'FAILED') "
                    "+ (SELECT count(*) FROM webhook_events "
                    "WHERE status IN ('DEAD_LETTER','REJECTED'))"
                )
            )
            gauges["fairpool_dead_letters"] = [({}, float(dead or 0))]
    except Exception as exc:
        # A scrape must never take the API down, and a database hiccup here is an
        # observability gap, not a request failure. Log the type only: a driver
        # exception can carry connection details (I14).
        logger.warning("fairpool.metrics.gauge_collection_failed error=%s", type(exc).__name__)
    return gauges


def _session_factory_for(request: Request) -> async_sessionmaker[AsyncSession] | None:
    """Reuse the app's request session factory, or build the one it would build."""
    state = request.app.state
    factory = getattr(state, "session_factory", None)
    if factory is not None:
        return cast(async_sessionmaker[AsyncSession], factory)
    settings = getattr(state, "settings", None)
    if settings is None:
        return None
    from fairpool.db.session import create_engine

    engine = create_engine(settings)
    built = async_sessionmaker(engine, expire_on_commit=False)
    state.engine = engine
    state.session_factory = built
    return built


async def metrics_endpoint(request: Request) -> Response:
    """The scrape handler: counters always, stored gauges when a session exists."""
    settings = getattr(request.app.state, "settings", None)
    token = settings.metrics_token.get_secret_value() if settings is not None else ""
    if token:
        # ``METRICS_TOKEN`` is unset in local and test runs; a hosted scrape carries it.
        # Compared in constant time and never logged (I14).
        header = request.headers.get("authorization", "")
        supplied = header[len("Bearer ") :] if header.lower().startswith("bearer ") else ""
        if not secrets.compare_digest(supplied, token):
            return Response(
                "Unauthorized\n",
                status_code=401,
                media_type="text/plain",
                headers={"WWW-Authenticate": "Bearer"},
            )
    gauges = await collect_gauges(_session_factory_for(request))
    return Response(get_counters().render_prometheus(gauges), media_type=CONTENT_TYPE)


def metrics_route() -> Route:
    """A raw Starlette route for ``create_app``; it adds no documented operation."""
    return Route("/metrics", endpoint=metrics_endpoint, methods=["GET"])


__all__ = [
    "CONTENT_TYPE",
    "COUNTER_SPECS",
    "GAUGE_SPECS",
    "Counters",
    "collect_gauges",
    "get_counters",
    "metric_names",
    "metrics_endpoint",
    "metrics_route",
]
