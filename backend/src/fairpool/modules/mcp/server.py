"""Minimal JSON-RPC 2.0 MCP server for the four FairPool tools (T07B03).

Contract: ``api.md`` section 4.5 and ``testing-strategy.md`` (test_mcp_contract,
PT-16). This is the MCP server side of Streamable HTTP without the official SDK:
the SDK's ``StreamableHTTPSessionManager`` requires its ``run()`` lifespan, and a
mounted Starlette app under this project's pinned FastAPI never has its lifespan
executed, so the SDK path cannot mount cleanly here. The deviation is recorded
in the task report; the wire contract (initialize, tools/list, tools/call) is
the same.

Only four tool names exist and every call is delegated to the real Agent API, so
no payment verb can appear: ``modules.mcp`` exposes no tool that creates an
order, authorizes, captures, voids or refunds (I1, I2, rule 22).
"""

from __future__ import annotations

from typing import Any, Final

from fairpool.modules.mcp.tools import TOOL_NAMES, TOOL_SPECS, TOOL_SPECS_BY_NAME, invoke

PROTOCOL_VERSION: Final[str] = "2025-06-18"
SERVER_INFO: Final[dict[str, str]] = {"name": "fairpool", "version": "0.1.0"}


class MissingToolArguments(Exception):
    """The request named no tool or no arguments object."""


class MCPServer:
    """Dispatch one JSON-RPC message for one authenticated delegation."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def handle(self, bearer: str, message: dict[str, Any]) -> dict[str, Any] | None:
        """Return the JSON-RPC response, or None for a notification."""
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized" or (method == "notifications/cancelled"):
            return None
        try:
            result = await self._dispatch(bearer, method, message.get("params") or {})
        except MissingToolArguments as exc:
            return _error(request_id, -32602, str(exc))
        except Exception as exc:  # pragma: no cover - never leak internals
            return _error(request_id, -32603, f"Internal error: {type(exc).__name__}")
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    async def _dispatch(
        self, bearer: str, method: object, params: dict[str, Any]
    ) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": TOOL_SPECS}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or name not in TOOL_NAMES:
                raise MissingToolArguments(f"Unknown tool {name!r}")
            if not isinstance(arguments, dict):
                raise MissingToolArguments("arguments must be an object")
            # -32602 names the parameter the client forgot, instead of letting the
            # KeyError surface as an internal -32603.
            missing = [
                key
                for key in TOOL_SPECS_BY_NAME[name]["inputSchema"].get("required", [])
                if key not in arguments
            ]
            if missing:
                raise MissingToolArguments(f"Missing required parameter: {missing[0]}")
            return await invoke(self.app, bearer, name, arguments)
        raise MissingToolArguments(f"Unsupported method {method!r}")


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
