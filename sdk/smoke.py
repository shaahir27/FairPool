"""Smoke test for the generated Merchant Agent SDKs (T10A04).

    .venv/Scripts/python.exe sdk/smoke.py

Offline it imports the generated Python client, builds the contracted bid body with the
generated models, and asserts the serialized JSON is what the server expects (a JSON
boolean for ``confirmed``, not the string "True"). With the three environment variables
below it also submits one real bid through the generated client to a running app; the
API key is read from the environment and never printed.

    FAIRPOOL_SMOKE_BASE_URL=http://127.0.0.1:8000
    FAIRPOOL_SMOKE_API_KEY=fpm_...          # a merchant key with bids:write
    FAIRPOOL_SMOKE_LOT_ID=<uuid>            # a lot in BIDDING
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

SDK_PYTHON = Path(__file__).resolve().parent / "python"
sys.path.insert(0, str(SDK_PYTHON))

from fairpoolmerchantagentapi.api_helper import APIHelper  # noqa: E402
from fairpoolmerchantagentapi.configuration import Configuration, Environment  # noqa: E402
from fairpoolmerchantagentapi.exceptions.api_exception import ApiException  # noqa: E402
from fairpoolmerchantagentapi.fairpoolmerchantagentapi_client import (  # noqa: E402
    FairpoolmerchantagentapiClient,
)
from fairpoolmerchantagentapi.http.auth.oauth_2 import BearerAuthCredentials  # noqa: E402
from fairpoolmerchantagentapi.models.merchant_api_bid_request import (  # noqa: E402
    MerchantApiBidRequest,
)

STRUCTURED = {
    "v": 1,
    "product_key": "monitor-27",
    "condition": "NEW",
    "bundle_contents": ["monitor", "stand", "power cable"],
    "capacity": 12,
    "target_quantity": 12,
    "moq": 3,
    "tiers": [
        {"min_qty": 3, "item_price_cents": 47000},
        {"min_qty": 6, "item_price_cents": 45000},
    ],
    "shipping_cents_by_zone": {},
    "tax": {"mode": "INCLUDED"},
    "delivery": {"sla_days": 7},
    "returns": {"days": 30},
    "valid_until": "2026-12-01T00:00:00Z",
    "total_capacity": 24,
    "evidence": {"note": "units reserved in warehouse A", "url": None},
}

OPERATIONS = (
    "list_lots",
    "get_lot",
    "submit_bid",
    "list_bids",
    "get_bid",
    "get_lot_progress",
    "get_lot_fulfillment",
    "submit_shipments",
    "get_lot_verification",
    "get_verification_manifest",
)


def main() -> int:
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if detail else ''}")

    base_url = os.environ.get("FAIRPOOL_SMOKE_BASE_URL", "").strip()
    if base_url:
        Configuration.environments[Environment.PRODUCTION] = {
            server: base_url for server in Configuration.environments[Environment.PRODUCTION]
        }

    client = FairpoolmerchantagentapiClient(
        bearer_auth_credentials=BearerAuthCredentials("offline-smoke-token"),
        timeout=20,
        max_retries=0,
    )

    check(
        "the generated client exposes the ten Merchant API operations",
        all(hasattr(client.client, name) for name in OPERATIONS),
    )

    body = MerchantApiBidRequest(confirmed=True, structured=STRUCTURED, notes=None)
    payload = json.loads(APIHelper.json_serialize(body))
    check(
        "confirmed serializes as a JSON boolean",
        payload.get("confirmed") is True,
        repr(payload.get("confirmed")),
    )
    check("structured round-trips the contracted shape", payload.get("structured") == STRUCTURED)

    api_key = os.environ.get("FAIRPOOL_SMOKE_API_KEY", "").strip()
    lot_id = os.environ.get("FAIRPOOL_SMOKE_LOT_ID", "").strip()
    if not (base_url and api_key and lot_id):
        print(
            "SKIP  live bid (set FAIRPOOL_SMOKE_BASE_URL, FAIRPOOL_SMOKE_API_KEY and "
            "FAIRPOOL_SMOKE_LOT_ID to send one)"
        )
    else:
        live = FairpoolmerchantagentapiClient(
            bearer_auth_credentials=BearerAuthCredentials(api_key),
            timeout=20,
            max_retries=0,
        )
        try:
            response = live.client.submit_bid(
                uuid.UUID(lot_id), body, idempotency_key=f"sdk-smoke-{uuid.uuid4()}"
            )
            result = response.body
            check(
                "live bid answered 200/201 with a receipt",
                response.status_code in (200, 201)
                and getattr(result, "bid_id", None) is not None
                and len(getattr(getattr(result, "receipt", None), "hash", "") or "") == 64,
                f"status={response.status_code} revision={getattr(result, 'revision', '?')}",
            )
        except ApiException as error:
            # The response body is the server's own error code; no header or key is printed.
            detail = f"status={error.status_code} body={str(error.body)[:200]}"
            check("live bid answered", False, detail)

    verdict = "ALL SMOKE CHECKS PASSED" if failures == 0 else f"{failures} SMOKE CHECK(S) FAILED"
    print(f"\n{verdict}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
