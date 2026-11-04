"""The four FairPool MCP tools, each a thin call into the Agent API (T07B03).

Contract: ``api.md`` section 4.5, ``product-spec.md`` FR-IG-02, rule 22. There is
no payment tool and no PayPal call: an AI client may list pools, enter one, list
its buyer's entries and withdraw one. Payment stays with the human on PayPal,
which is why ``checkout_url`` is a link, not an action.

Every tool is executed in-process through ``httpx.ASGITransport`` against the
real Agent API, forwarding the caller's ``Authorization`` header. The tool layer
therefore adds no authorisation rules of its own: the API's delegation checks,
scope, cap and validator are the only ones that apply.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

#: The exact four tools of api.md section 4.5; nothing else may be listed.
TOOL_SPECS: Final[list[dict[str, Any]]] = [
    {
        "name": "list_pools",
        "description": "List or search pools that are open for entries.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": ["string", "null"], "description": "Optional search text."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 20},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "enter_pool",
        "description": (
            "Enter an open pool for this buyer. A human approves payment on PayPal "
            "afterwards; this tool cannot pay."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "pool_id": {"type": "string", "format": "uuid"},
                "delivery_region": {"type": "string"},
                "max_total_usd": {"type": "string", "pattern": r"^\d+(\.\d{1,2})?$"},
                "max_total_cents": {"type": "integer", "minimum": 0},
                "required_by": {"type": "string"},
                "firm": {"type": "array", "items": {"type": "string"}},
                "preferences": {"type": "array", "items": {"type": "string"}},
                "idempotency_key": {"type": "string", "maxLength": 128},
            },
            "required": ["pool_id", "delivery_region", "idempotency_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_entries",
        "description": "List this buyer's entries, optionally filtered by pool or entry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pool_id": {"type": ["string", "null"], "format": "uuid"},
                "entry_id": {"type": ["string", "null"], "format": "uuid"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "withdraw_entry",
        "description": "Withdraw one of this buyer's entries before the pool closes.",
        "inputSchema": {
            "type": "object",
            "properties": {"entry_id": {"type": "string", "format": "uuid"}},
            "required": ["entry_id"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES: Final[frozenset[str]] = frozenset(spec["name"] for spec in TOOL_SPECS)


def _client(app: Any) -> httpx.AsyncClient:
    """An in-process client for the parent app; no network and no new process."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fairpool.invalid",
        timeout=30.0,
    )


async def invoke(app: Any, bearer: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool and return its MCP result object."""
    headers = {"Authorization": f"Bearer {bearer}"}
    async with _client(app) as client:
        if name == "list_pools":
            params: dict[str, Any] = {}
            if arguments.get("q") is not None:
                params["q"] = arguments["q"]
            if arguments.get("limit") is not None:
                params["limit"] = arguments["limit"]
            response = await client.get("/agent/v1/pools", headers=headers, params=params)
        elif name == "enter_pool":
            # No missing business input is invented here: an omitted ``required_by``
            # reaches the same validator the web form uses, which rejects it (I3).
            request: dict[str, Any] = {
                "delivery": {"region": arguments["delivery_region"]},
                "firm": arguments.get("firm", []),
                "preferences": arguments.get("preferences", []),
            }
            if arguments.get("required_by") is not None:
                request["required_by"] = arguments["required_by"]
            if arguments.get("max_total_usd") is not None:
                request["max_total_usd"] = arguments["max_total_usd"]
            if arguments.get("max_total_cents") is not None:
                request["max_total_cents"] = arguments["max_total_cents"]
            body = {
                "pool_id": arguments["pool_id"],
                "request": request,
                "idempotency_key": arguments["idempotency_key"],
            }
            response = await client.post(
                "/agent/v1/entries",
                headers={**headers, "Idempotency-Key": arguments["idempotency_key"]},
                json=body,
            )
        elif name == "list_entries":
            params = {}
            if arguments.get("pool_id") is not None:
                params["pool_id"] = arguments["pool_id"]
            if arguments.get("entry_id") is not None:
                params["entry_id"] = arguments["entry_id"]
            response = await client.get("/agent/v1/entries", headers=headers, params=params)
        elif name == "withdraw_entry":
            response = await client.post(
                "/agent/v1/entries/withdraw",
                headers=headers,
                json={"entry_id": arguments["entry_id"]},
            )
        else:  # pragma: no cover - the caller checks TOOL_NAMES first
            return {"content": [{"type": "text", "text": f"Unknown tool {name}"}], "isError": True}

    result: dict[str, Any] = {
        "content": [{"type": "text", "text": response.text}],
        "isError": response.status_code >= 400,
    }
    return result
