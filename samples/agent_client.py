#!/usr/bin/env python3
"""A tiny stdlib-only Agent API client, for docs and manual checks (T07A05).

It never takes a secret from the file: the delegation token comes from the
``FAIRPOOL_AGENT_TOKEN`` environment variable, and the API base URL from
``FAIRPOOL_API_BASE_URL``. The token is an ``fpd_`` buyer delegation, not a
PayPal credential, and this script cannot pay: payment happens on the
``checkout_url`` the API returns, approved by a human (I1, rule 24).

Usage::

    export FAIRPOOL_API_BASE_URL=http://localhost:8000
    export FAIRPOOL_AGENT_TOKEN=fpd_...            # shown once when created
    python samples/agent_client.py pools --q monitor
    python samples/agent_client.py entries
    python samples/agent_client.py enter --pool <uuid> --region NY --max-usd 600.00 \
        --required-by 2026-12-01 --key demo-1
    python samples/agent_client.py withdraw --entry <uuid>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4


def _call(method: str, path: str, token: str, *, body: dict | None = None) -> dict | list:
    base = os.environ.get("FAIRPOOL_API_BASE_URL", "http://localhost:8000").rstrip("/")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    if body is not None:
        request.add_header("Idempotency-Key", str(body.get("idempotency_key", uuid4().hex)))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        # The API's error envelope is the useful part; the token is never printed.
        return json.loads(exc.read() or b"{}")


def main(argv: list[str] | None = None) -> int:
    token = os.environ.get("FAIRPOOL_AGENT_TOKEN")
    if not token:
        print("FAIRPOOL_AGENT_TOKEN is required (a delegation token, shown once).", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description="FairPool Agent API client")
    sub = parser.add_subparsers(dest="command", required=True)
    pools = sub.add_parser("pools")
    pools.add_argument("--q", default=None)
    pools.add_argument("--limit", type=int, default=20)
    entries = sub.add_parser("entries")
    entries.add_argument("--pool", default=None)
    enter = sub.add_parser("enter")
    enter.add_argument("--pool", required=True)
    enter.add_argument("--region", required=True)
    enter.add_argument("--max-usd", default=None)
    enter.add_argument("--max-cents", type=int, default=None)
    enter.add_argument("--required-by", default=None)
    enter.add_argument("--key", default=None)
    withdraw = sub.add_parser("withdraw")
    withdraw.add_argument("--entry", required=True)
    args = parser.parse_args(argv)

    if args.command == "pools":
        query = urllib.parse.urlencode(
            {k: v for k, v in {"q": args.q, "limit": args.limit}.items() if v is not None}
        )
        result = _call("GET", f"/agent/v1/pools?{query}", token)
    elif args.command == "entries":
        query = urllib.parse.urlencode({} if args.pool is None else {"pool_id": args.pool})
        result = _call("GET", f"/agent/v1/entries?{query}", token)
    elif args.command == "enter":
        request: dict[str, object] = {"delivery": {"region": args.region}}
        if args.max_usd is not None:
            request["max_total_usd"] = args.max_usd
        if args.max_cents is not None:
            request["max_total_cents"] = args.max_cents
        if args.required_by is not None:
            request["required_by"] = args.required_by
        result = _call(
            "POST",
            "/agent/v1/entries",
            token,
            body={
                "pool_id": args.pool,
                "request": request,
                "idempotency_key": args.key or uuid4().hex,
            },
        )
    else:
        result = _call("POST", "/agent/v1/entries/withdraw", token, body={"entry_id": args.entry})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
