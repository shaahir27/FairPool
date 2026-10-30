"""T01B01: the FastAPI route set equals api.md section 2 exactly."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.routing import APIRoute

from fairpool.api.app import ROUTERS, create_app
from fairpool.api.merchant_api import routes_fulfillment, routes_lots_bids
from fairpool.api.routers import health

ROOT = Path(__file__).resolve().parents[3]
API_DOC = ROOT / "docs/contracts/api.md"
ROW_RE = re.compile(
    r"^\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*(/\S+)\s*\|\s*(A|B|AB)\s*\|\s*(\w+)\s*\|",
    re.MULTILINE,
)
METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}
A_MODULES = {"checkout", "webhooks", "admin_ops", "health", "merchant_fulfillment"}
B_MODULES = {
    "auth",
    "paypal_login",
    "pools",
    "intake",
    "entries",
    "public",
    "merchant",
    "merchant_keys",
    "agent",
    "admin_pools",
    "admin_sim",
}


def contract_rows() -> list[tuple[str, str, str, str]]:
    text = API_DOC.read_text(encoding="utf-8")
    return [(m.group(1), m.group(2), m.group(3), m.group(4)) for m in ROW_RE.finditer(text)]


def collect(modules: list[object]) -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for module in modules:
        short = module.__name__.rsplit(".", 1)[-1]
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods:
                if method in METHODS:
                    found[(method, route.path)] = short
    return found


def test_parent_and_merchant_route_sets_match_the_contract():
    rows = contract_rows()
    assert len(rows) == 92
    parent_expected = {
        (method, path)
        for method, path, _, _ in rows
        if path != "/mcp" and not path.startswith("/merchant-api/v1")
    }
    merchant_expected = {
        (method, path) for method, path, _, _ in rows if path.startswith("/merchant-api/v1")
    }
    assert len(parent_expected) == 80
    assert len(merchant_expected) == 10

    parent_modules = [health, *ROUTERS]
    parent_actual = collect(parent_modules)
    assert set(parent_actual) == parent_expected

    merchant_modules = [routes_lots_bids, routes_fulfillment]
    merchant_actual = {
        (method, "/merchant-api/v1" + path) for method, path in collect(merchant_modules)
    }
    assert merchant_actual == merchant_expected


def test_every_route_lives_in_its_owner_module():
    modules = [health, *ROUTERS]
    actual = collect(modules)
    for method, path, owner, _ in contract_rows():
        if path == "/mcp":
            continue
        if path.startswith("/merchant-api/v1"):
            short = collect([routes_fulfillment, routes_lots_bids]).get(
                (method, path.removeprefix("/merchant-api/v1"))
            )
            allowed = {"routes_fulfillment"} if owner == "A" else {"routes_lots_bids"}
        else:
            short = actual.get((method, path))
            allowed = A_MODULES if owner == "A" else B_MODULES
            if owner == "AB":
                allowed = A_MODULES | B_MODULES
        assert short is not None, f"{method} {path} is missing"
        assert short in allowed, f"{method} {path} lives in {short}, expected {allowed}"


def test_agent_withdraw_route_is_registered_before_the_dynamic_route():
    from fairpool.api.routers import agent

    paths = [route.path for route in agent.router.routes if isinstance(route, APIRoute)]
    assert paths.index("/agent/v1/entries/withdraw") < paths.index("/agent/v1/entries/{entry_id}")


def test_app_openapi_contains_all_parent_operations():
    schema = create_app().openapi()
    operations = [
        (method.upper(), path)
        for path, item in schema["paths"].items()
        for method in item
        if method.upper() in METHODS
    ]
    assert len(operations) == 80
