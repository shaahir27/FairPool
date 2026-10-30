"""T01B01: exactly the ten Merchant Agent API operations, with fixed IDs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fairpool.api.merchant_api.app import app as merchant_app

ROOT = Path(__file__).resolve().parents[3]
API_DOC = ROOT / "docs/contracts/api.md"
SPEC = ROOT / "sdk/merchant-openapi.json"
PREFIX = "/merchant-api/v1"
METHODS = {"get", "post", "put", "delete", "patch"}
ROW_RE = re.compile(
    r"^\|\s*([A-Za-z0-9_]+)\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)\s*\|\s*[a-z:]+\s*\|",
    re.MULTILINE,
)


def contract_operations() -> set[tuple[str, str, str]]:
    section = re.search(
        r"^### 4\.3\b.*?(?=^### |\Z)",
        API_DOC.read_text(encoding="utf-8"),
        re.MULTILINE | re.DOTALL,
    )
    assert section is not None
    return {
        (match.group(1), match.group(2), match.group(3))
        for match in ROW_RE.finditer(section.group(0))
    }


def schema_operations(schema: dict) -> set[tuple[str, str, str]]:
    operations: set[tuple[str, str, str]] = set()
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method.lower() not in METHODS:
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                operations.add((operation_id, method.upper(), path))
    return operations


def test_live_sub_app_has_exactly_the_ten_contract_operations():
    expected = contract_operations()
    assert len(expected) == 10
    schema = merchant_app.openapi()
    actual = {
        (operation_id, method, PREFIX + path)
        for operation_id, method, path in schema_operations(schema)
    }
    assert actual == expected
    assert len(actual) <= 20


def test_committed_spec_matches_the_live_sub_app():
    expected = contract_operations()
    document = json.loads(SPEC.read_text(encoding="utf-8"))
    assert schema_operations(document) == expected
    assert document["servers"] == [{"url": "/"}]


def test_sub_app_advertises_bearer_auth():
    schema = merchant_app.openapi()
    first = next(iter(schema["paths"].values()))
    operation = next(item for method, item in first.items() if method.lower() in METHODS)
    assert operation.get("security")
    assert "HTTPBearer" in schema["components"]["securitySchemes"]
