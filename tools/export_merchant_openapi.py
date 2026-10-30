#!/usr/bin/env python3
"""Export the Merchant Agent API OpenAPI document (INT-4, INT-9).

The Merchant Agent API is a FastAPI sub-application mounted at
``/merchant-api/v1``. Its routes are declared relative to that mount; the
exported document prefixes them so APIMatic sees the full paths in
docs/contracts/api.md section 4.3.

Usage (from the repository root)::

    python tools/export_merchant_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import re
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "sdk" / "merchant-openapi.json"
API_DOC = REPO_ROOT / "docs" / "contracts" / "api.md"
MODULE = "fairpool.api.merchant_api.app"
PREFIX = "/merchant-api/v1"
EXPECTED_COUNT = 10

SECTION_RE = re.compile(r"^### 4\.3\b.*?(?=^### |\Z)", re.MULTILINE | re.DOTALL)
OPERATION_RE = re.compile(
    r"^\|\s*([A-Za-z0-9_]+)\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)\s*\|\s*[a-z:]+\s*\|",
    re.MULTILINE,
)
HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch"})


class ExportError(RuntimeError):
    """A configuration or contract error that should fail the command."""


def _find_merchant_spec() -> ModuleSpec | None:
    backend_src = REPO_ROOT / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
    try:
        return importlib.util.find_spec(MODULE)
    except ModuleNotFoundError:
        return None


def _load_app() -> object | None:
    spec = _find_merchant_spec()
    if spec is None:
        print("SKIP: merchant API not present (T01B01)")
        return None
    try:
        module = importlib.import_module(spec.name)
    except ImportError as exc:
        raise ExportError(f"could not import {MODULE}: {exc}") from exc
    app = getattr(module, "app", None)
    if app is None or not hasattr(app, "openapi"):
        raise ExportError(f"{MODULE} does not expose a FastAPI 'app'")
    return app


def _contract_operations() -> set[tuple[str, str, str]]:
    text = API_DOC.read_text(encoding="utf-8")
    section = SECTION_RE.search(text)
    if section is None:
        raise ExportError("docs/contracts/api.md section 4.3 was not found")
    rows = OPERATION_RE.findall(section.group(0))
    operations = {(row[0], row[1].upper(), row[2]) for row in rows}
    if len(operations) != EXPECTED_COUNT:
        raise ExportError(
            f"docs/contracts/api.md section 4.3 has {len(operations)} operations; "
            f"expected {EXPECTED_COUNT}"
        )
    return operations


def _generated_operations(schema: dict[str, object]) -> list[tuple[str, str, str]]:
    operations: list[tuple[str, str, str]] = []
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return operations
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if isinstance(operation_id, str) and operation_id:
                operations.append((operation_id, method.upper(), path))
    return operations


def _with_full_paths(schema: dict[str, object]) -> dict[str, object]:
    """Prefix relative sub-app paths for the APIMatic document."""
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return schema
    document = dict(schema)
    document["paths"] = {
        (path if path.startswith(PREFIX) else PREFIX + path): item for path, item in paths.items()
    }
    document["servers"] = [{"url": "/"}]
    return document


def _check(schema: dict[str, object]) -> int:
    try:
        expected = _contract_operations()
    except (OSError, ExportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    generated = _generated_operations(schema)
    actual = {(operation[0], operation[1], operation[2]) for operation in generated}
    ids = [operation[0] for operation in generated]
    duplicates = sorted({operation_id for operation_id in ids if ids.count(operation_id) > 1})
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)

    errors: list[str] = []
    if len(generated) != EXPECTED_COUNT:
        errors.append(f"generated {len(generated)} operations; expected {EXPECTED_COUNT}")
    if duplicates:
        errors.append(f"duplicate operationIds: {', '.join(duplicates)}")
    if missing:
        errors.append(
            "missing operations: " + ", ".join(f"{item[0]} {item[1]} {item[2]}" for item in missing)
        )
    if extra:
        errors.append(
            "unexpected operations: "
            + ", ".join(f"{item[0]} {item[1]} {item[2]}" for item in extra)
        )

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: merchant OpenAPI matches api.md section 4.3 ({EXPECTED_COUNT} operations)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="assert the generated operations against docs/contracts/api.md section 4.3",
    )
    args = parser.parse_args(argv)

    try:
        app = _load_app()
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if app is None:
        return 0

    try:
        schema = app.openapi()
    except Exception as exc:  # report a clean CLI error, not a traceback
        print(f"ERROR: could not build the merchant OpenAPI document: {exc}", file=sys.stderr)
        return 1
    if not isinstance(schema, dict):
        print("ERROR: FastAPI returned a non-object OpenAPI document", file=sys.stderr)
        return 1

    schema = _with_full_paths(schema)
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {SPEC_PATH.relative_to(REPO_ROOT).as_posix()}")

    if args.check:
        return _check(schema)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
