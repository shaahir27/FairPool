"""ASGI transport for the FairPool MCP server at ``/mcp`` (T07B03).

Contract: ``api.md`` sections 2 and 4.5. A mounted ASGI app, not a route: the
parent OpenAPI document must not grow an operation for it, and the route-table
test skips ``/mcp`` by contract.

Auth is the Agent API's delegation bearer, resolved by the same
``PostgresDelegationAuth`` and the same database clock as ``require_agent``. A
missing, malformed, expired or revoked token is a JSON error envelope with
``DELEGATION_INVALID`` at 401, never an HTML page or a protocol answer.

POST carries JSON-RPC messages (single or batch). GET would carry
server-initiated messages, which this server has none of: it answers 200 with an
idle SSE stream and closes when the client disconnects. That is the Streamable
HTTP shape the contract asks for without inventing notifications.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fairpool.config import Settings
from fairpool.db.session import create_engine
from fairpool.domain.errors import ApplicationError
from fairpool.modules.identity.delegations import AgentPrincipal, PostgresDelegationAuth
from fairpool.modules.mcp.server import MCPServer
from fairpool.ports import Clock

JSON: Final[bytes] = b"application/json"


def build_mcp_app(parent: Any, settings: Settings, *, clock: Clock) -> MCPApp:
    return MCPApp(parent=parent, settings=settings, clock=clock)


class MCPApp:
    """The mounted ``/mcp`` application."""

    def __init__(self, *, parent: Any, settings: Settings, clock: Clock) -> None:
        self.parent = parent
        self.settings = settings
        self.clock = clock
        self.server = MCPServer(parent)
        self._factory: async_sessionmaker[AsyncSession] | None = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":  # pragma: no cover - no websocket/lifespan use
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        # Served by a Starlette Route at exactly /mcp (see api/app.py); the mount
        # forms are also accepted so a trailing slash is not a 404.
        if path not in {"", "/", "/mcp", "/mcp/"}:
            await _send_json(send, 404, _error_body("NOT_FOUND", "Unknown MCP path."))
            return
        bearer = _bearer(scope)
        if bearer is None:
            await _send_json(send, 401, _error_body("DELEGATION_INVALID", _INVALID_MESSAGE))
            return
        try:
            await self._authenticate(bearer)
        except ApplicationError:
            await _send_json(send, 401, _error_body("DELEGATION_INVALID", _INVALID_MESSAGE))
            return
        if method == "POST":
            await self._post(bearer, receive, send)
        elif method == "GET":
            await self._stream(send, receive)
        else:
            await _send_json(send, 405, _error_body("VALIDATION_ERROR", "Use POST or GET."))

    async def _authenticate(self, bearer: str) -> AgentPrincipal:
        """Resolve the token on its own short session; authentication writes nothing."""
        if self._factory is None:
            engine = create_engine(self.settings)
            self._factory = async_sessionmaker(engine, expire_on_commit=False)
        async with self._factory() as session:
            auth = PostgresDelegationAuth(
                clock=self.clock, hmac_key=self.settings.hmac_key.get_secret_value()
            )
            return await auth.from_token(session, bearer)

    async def _post(self, bearer: str, receive: Any, send: Any) -> None:
        body = await _read_body(receive)
        try:
            message = json.loads(body or b"null")
        except ValueError:
            await _send_json(send, 400, _rpc_error(None, -32700, "Parse error"))
            return
        messages = message if isinstance(message, list) else [message]
        replies: list[dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict):
                replies.append(_rpc_error(None, -32600, "Invalid request"))
                continue
            reply = await self.server.handle(bearer, item)
            if reply is not None:
                replies.append(reply)
        if not replies:
            await _send_json(send, 202, None)
        elif isinstance(message, list):
            await _send_json(send, 200, replies)
        else:
            await _send_json(send, 200, replies[0])

    async def _stream(self, send: Any, receive: Any) -> None:
        """An idle SSE channel: no server-initiated notifications exist yet."""
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/event-stream"),
                    (b"cache-control", b"no-cache"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b": fairpool mcp stream\n\n", "more_body": True}
        )
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return


_INVALID_MESSAGE: Final[str] = "Agent token unknown, expired or revoked."


def _bearer(scope: dict[str, Any]) -> str | None:
    headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
    for key, value in headers:
        if key.lower() == b"authorization":
            text = value.decode("latin-1")
            scheme, _, token = text.partition(" ")
            if scheme.lower() == "bearer" and token:
                return token.strip()
            return None
    return None


async def _read_body(receive: Any) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":  # pragma: no cover - disconnect mid-body
            return b"".join(chunks)
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            return b"".join(chunks)


async def _send_json(send: Any, status: int, payload: Any) -> None:
    body = b"" if payload is None else json.dumps(payload).encode()
    headers = [(b"content-type", JSON), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _error_body(code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": {},
            "request_id": uuid.uuid4().hex,
        }
    }


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
