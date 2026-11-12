"""OAuth 2.1 for the buyer MCP surface (CR-17, api.md section 4.6).

An MCP client that meets a 401 with ``WWW-Authenticate`` discovers this server,
registers itself, opens the buyer's browser to consent, and exchanges a PKCE code
for an access token. The access token **is** a buyer delegation, minted from the
mandate the buyer ratified in the browser: there is no second authority model, one
revocation path, and the same cap/scope checks every agent call already runs.

Deliberately narrow, and recorded as such in CR-17: public clients only (no client
secret), authorization-code grant only, S256 only, no refresh token (an expired
delegation means consenting again), and no token introspection endpoint.

The code is stored only as its HMAC and is usable once. Every refusal at the token
endpoint is the same ``invalid_grant`` so a probe cannot tell an unknown code from a
replayed one, mirroring the delegation rule (I11).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Final
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.db.models.identity import AgentOAuthClient, AgentOAuthCode, Delegation
from fairpool.modules.identity.delegations import DelegationService, hash_token
from fairpool.modules.identity.mandate import verify_ratification
from fairpool.ports import AuditLog, Clock

logger: Final[logging.Logger] = logging.getLogger("fairpool.identity.agent_oauth")

CLIENT_PREFIX: Final[str] = "fpc"
CODE_TTL_S: Final[int] = 600
MAX_REDIRECTS: Final[int] = 5
_VERIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_UNSAFE_SCHEMES: Final[frozenset[str]] = frozenset(
    {"javascript", "data", "file", "blob", "vbscript", "about"}
)
_LOOPBACK: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


class OAuthError(Exception):
    """An RFC 6749 error response, not an application envelope."""

    def __init__(self, error: str, description: str = "") -> None:
        super().__init__(error)
        self.error = error
        self.description = description


def safe_redirect(uri: str) -> bool:
    """https anywhere, http only on loopback, a native custom scheme, never a fragment."""
    if not uri or len(uri) > 2000:
        return False
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    scheme = parsed.scheme.lower()
    if scheme in _UNSAFE_SCHEMES or not scheme or parsed.fragment:
        return False
    if scheme == "http":
        return (parsed.hostname or "") in _LOOPBACK
    if scheme == "https":
        return bool(parsed.hostname)
    # A native client's own scheme (for example an editor's callback): no host required.
    return bool(parsed.path or parsed.netloc)


def pkce_matches(verifier: str, challenge: str) -> bool:
    if _VERIFIER.fullmatch(verifier) is None:
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return secrets.compare_digest(computed, challenge)


class AgentOAuthService:
    def __init__(
        self, *, clock: Clock, audit: AuditLog, hmac_key: str, delegations: DelegationService
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.hmac_key = hmac_key
        self.delegations = delegations

    async def register(
        self, session: AsyncSession, *, name: str, redirect_uris: list[str]
    ) -> AgentOAuthClient:
        if not name.strip() or len(name) > 120:
            raise OAuthError("invalid_client_metadata", "A client name is required")
        if not redirect_uris or len(redirect_uris) > MAX_REDIRECTS:
            raise OAuthError("invalid_redirect_uri", "One to five redirect URIs are required")
        if any(not safe_redirect(uri) for uri in redirect_uris):
            raise OAuthError("invalid_redirect_uri", "A redirect URI is not allowed")
        row = AgentOAuthClient(
            client_id=f"{CLIENT_PREFIX}_{secrets.token_hex(16)}",
            name=name.strip(),
            redirect_uris=list(redirect_uris),
        )
        session.add(row)
        await session.flush()
        logger.info("agent oauth client registered client_id=%s", row.client_id)
        return row

    async def client(self, session: AsyncSession, client_id: str) -> AgentOAuthClient:
        row = await session.scalar(
            select(AgentOAuthClient).where(AgentOAuthClient.client_id == client_id)
        )
        if row is None:
            raise OAuthError("invalid_client", "Unknown client")
        return row

    async def check_request(
        self,
        session: AsyncSession,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        state: str,
    ) -> AgentOAuthClient:
        """Validate everything that must hold before a browser is sent anywhere."""
        row = await self.client(session, client_id)
        if redirect_uri not in row.redirect_uris:
            raise OAuthError("invalid_request", "Redirect URI is not registered")
        if code_challenge_method != "S256" or not code_challenge:
            raise OAuthError("invalid_request", "PKCE S256 is required")
        if not state:
            raise OAuthError("invalid_request", "state is required")
        return row

    async def issue_code(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        state: str,
        scope: dict[str, Any],
        max_cap_cents: int,
        expires_at: datetime,
    ) -> str:
        await self.check_request(
            session,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
        # The same binding the delegation mint path enforces: a code cannot carry a
        # mandate the buyer did not ratify (CR-14, FR-AI-06).
        verify_ratification(scope, max_cap_cents=max_cap_cents, expires_at=expires_at)
        code = secrets.token_urlsafe(32)
        session.add(
            AgentOAuthCode(
                code_hash=hash_token(self.hmac_key, code),
                client_id=client_id,
                user_id=user_id,
                redirect_uri=redirect_uri,
                code_challenge=code_challenge,
                scope=scope,
                max_cap_cents=max_cap_cents,
                expires_at=expires_at,
            )
        )
        await session.flush()
        await self.audit.append(
            session,
            actor=str(user_id),
            action="agent_oauth.code_issued",
            subject_type="agent_oauth_client",
            subject_id=client_id,
            payload={"max_cap_cents": max_cap_cents, "redirect_uri": redirect_uri},
        )
        return code

    async def exchange(
        self,
        session: AsyncSession,
        *,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> tuple[Delegation, str]:
        row = await session.scalar(
            select(AgentOAuthCode)
            .where(AgentOAuthCode.code_hash == hash_token(self.hmac_key, code))
            .with_for_update()
        )
        now = await self.clock.db_now(session)
        if (
            row is None
            or row.consumed_at is not None
            or row.created_at + timedelta(seconds=CODE_TTL_S) <= now
            or row.client_id != client_id
            or row.redirect_uri != redirect_uri
            or not pkce_matches(code_verifier, row.code_challenge)
        ):
            raise OAuthError("invalid_grant", "The code is not usable")
        if row.expires_at <= now:
            raise OAuthError("invalid_grant", "The mandate has expired")
        row.consumed_at = now
        await session.flush()
        client = await self.client(session, client_id)
        delegation, token = await self.delegations.create(
            session,
            user_id=row.user_id,
            scope=dict(row.scope),
            max_cap_cents=row.max_cap_cents,
            expires_at=row.expires_at,
            name=client.name,
            oauth_client_id=client_id,
        )
        await self.audit.append(
            session,
            actor=str(row.user_id),
            action="agent_oauth.token_issued",
            subject_type="delegation",
            subject_id=str(delegation.id),
            payload={"client_id": client_id, "max_cap_cents": row.max_cap_cents},
        )
        return delegation, token

    async def revoke_token(self, session: AsyncSession, *, token: str) -> None:
        """RFC 7009: revoking an unknown token is still a success, never a probe answer."""
        row = await session.scalar(
            select(Delegation).where(Delegation.token_hash == hash_token(self.hmac_key, token))
        )
        if row is None or row.revoked_at is not None:
            return
        await self.delegations.revoke(session, user_id=row.user_id, delegation_id=row.id)

    @staticmethod
    def expires_in(delegation: Delegation, now: datetime) -> int:
        return max(0, int((delegation.expires_at - now).total_seconds()))
