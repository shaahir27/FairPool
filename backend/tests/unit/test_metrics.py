"""T08A05: the Prometheus text format and the raw ``/metrics`` route."""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette

from fairpool.infra.metrics import (
    CONTENT_TYPE,
    Counters,
    get_counters,
    metrics_route,
)


@pytest.fixture(autouse=True)
def clear_counters() -> None:
    get_counters().reset()


def test_a_counter_renders_one_labelled_series() -> None:
    counters = Counters()
    counters.incr("fairpool_transitions_rejected_total", entity="buyer_order", trigger="BO-03")
    counters.incr("fairpool_transitions_rejected_total", entity="buyer_order", trigger="BO-03")
    counters.incr("fairpool_transitions_rejected_total", entity="lot", trigger="LS-12")

    text = counters.render_prometheus()

    assert "# TYPE fairpool_transitions_rejected_total counter" in text
    assert 'fairpool_transitions_rejected_total{entity="buyer_order",trigger="BO-03"} 2' in text
    assert 'fairpool_transitions_rejected_total{entity="lot",trigger="LS-12"} 1' in text


def test_label_values_are_escaped_and_series_are_sorted() -> None:
    counters = Counters()
    counters.incr("fairpool_outcome_unknown_total", stage='a"b\\c')

    text = counters.render_prometheus()

    assert 'fairpool_outcome_unknown_total{stage="a\\"b\\\\c"} 1' in text
    stages = [line for line in text.splitlines() if line.startswith("fairpool_outcome_unknown")]
    assert stages == ['fairpool_outcome_unknown_total{stage="a\\"b\\\\c"} 1']


def test_unknown_metrics_and_label_sets_are_rejected() -> None:
    counters = Counters()
    with pytest.raises(ValueError):
        counters.incr("fairpool_not_a_metric_total", stage="x")
    with pytest.raises(ValueError):
        counters.incr("fairpool_amount_mismatch_total", entity="buyer_order")
    with pytest.raises(ValueError):
        counters.incr("fairpool_amount_mismatch_total", stage="approval", extra="x")


def test_gauges_are_rendered_with_their_labels() -> None:
    counters = Counters()
    text = counters.render_prometheus(
        {
            "fairpool_dead_letters": [({}, 3.0)],
            "fairpool_funnel_buyer_orders": [({"stage": "OFFERED"}, 2.0)],
        }
    )

    assert "# TYPE fairpool_dead_letters gauge" in text
    assert "fairpool_dead_letters 3" in text
    assert 'fairpool_funnel_buyer_orders{stage="OFFERED"} 2' in text


async def test_the_raw_route_serves_the_prometheus_content_type() -> None:
    route = metrics_route()
    assert route.path == "/metrics"
    app = Starlette(routes=[route])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://metrics.test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert CONTENT_TYPE.startswith("text/plain")
    # Without app settings there is no session, so only the counter families appear.
    assert "# TYPE fairpool_transitions_rejected_total counter" in response.text


async def test_the_scrape_is_open_when_metrics_token_is_unset() -> None:
    from tests.unit.test_settings import make_settings

    app = Starlette(routes=[metrics_route()])
    app.state.settings = make_settings()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://metrics.test"
    ) as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert "# TYPE fairpool_dead_letters gauge" in response.text


async def test_a_configured_metrics_token_guards_the_scrape() -> None:
    from tests.unit.test_settings import make_settings

    settings = make_settings(metrics_token="scrape-token")
    app = Starlette(routes=[metrics_route()])
    app.state.settings = settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://metrics.test"
    ) as client:
        anonymous = await client.get("/metrics")
        wrong = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
        right = await client.get("/metrics", headers={"Authorization": "Bearer scrape-token"})

    assert anonymous.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 200
    assert "fairpool_dead_letters" in right.text
