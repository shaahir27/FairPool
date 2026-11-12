"""CR-17: an MCP client connects through OAuth 2.1, not a pasted token.

Contract: ``api.md`` section 4.6, RFC 6749/7636/7591/9728 as scoped by CR-17.
The access token is an ordinary buyer delegation, so there is one revocation path
and one cap/scope enforcement path. These tests pin the parts that make the flow
safe: PKCE S256, exact redirect matching, single-use codes, the ratification
binding, and a token that is never wider than the mandate the buyer approved.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fairpool.api.app import create_app
from fairpool.api.deps import database_session
from fairpool.modules.identity.delegations import hash_token
from fairpool.modules.identity.mandate import canonical_mandate
from tests.integration.test_join_receipts import login, settings_for

pytestmark = pytest.mark.integration

SETTINGS = settings_for(public_base_url="https://api.test")
HMAC_KEY = SETTINGS.hmac_key.get_secret_value()
FUTURE = "2099-01-01T00:00:00Z"
REDIRECT = "https://client.example.test/callback"
TOKEN_SHAPE = re.compile(r"^fpd_[0-9a-f]{8}_[A-Za-z0-9_-]{43}$")


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(SETTINGS)

    async def session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[database_session] = session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://api.test"
    ) as http:
        yield http


def pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(b"v" * 48).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def ratified(scope: dict[str, Any], cap: int, expires: str) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    digest = hashlib.sha256(
        canonical_mandate(
            category=scope.get("category"),
            conditions=scope.get("conditions") or [],
            expires_at=expires_at,
            max_cap_cents=cap,
            pool_ids=scope.get("pool_ids") or [],
        ).encode()
    ).hexdigest()
    return {**scope, "mandate_version": "1", "ratification_sha256": digest}


async def register(client: httpx.AsyncClient, redirect: str = REDIRECT) -> str:
    response = await client.post(
        "/oauth/register", json={"client_name": "Test assistant", "redirect_uris": [redirect]}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["client_id"])


async def authorize_params(client: httpx.AsyncClient, **overrides: Any) -> dict[str, str]:
    _, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": await register(client),
        "redirect_uri": REDIRECT,
        "state": "state-123",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(overrides)
    return params


async def decision(
    client: httpx.AsyncClient,
    csrf: str,
    params: dict[str, str],
    *,
    cap: int = 60000,
    scope: dict[str, Any] | None = None,
    expires: str = FUTURE,
) -> httpx.Response:
    chosen = scope if scope is not None else {"pool_ids": [], "category": None}
    return await client.post(
        "/oauth/authorize/decision",
        headers={"X-CSRF-Token": csrf},
        json={
            **params,
            "scope": ratified(chosen, cap, expires),
            "max_cap_cents": cap,
            "expires_at": expires,
        },
    )


async def test_metadata_describes_this_origin_and_the_mcp_resource(
    client: httpx.AsyncClient,
) -> None:
    resource = await client.get("/.well-known/oauth-protected-resource")
    assert resource.status_code == 200, resource.text
    body = resource.json()
    assert body["resource"].endswith("/mcp")
    assert body["bearer_methods_supported"] == ["header"]

    server = await client.get("/.well-known/oauth-authorization-server")
    assert server.status_code == 200, server.text
    meta = server.json()
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["token_endpoint_auth_methods_supported"] == ["none"]
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        assert meta[key].startswith("https://api.test"), meta[key]


async def test_registration_refuses_an_unsafe_redirect(client: httpx.AsyncClient) -> None:
    for redirect in (
        "javascript:alert(1)",
        "http://evil.example.test/callback",
        "data:text/html,x",
    ):
        response = await client.post(
            "/oauth/register", json={"client_name": "Bad", "redirect_uris": [redirect]}
        )
        assert response.status_code == 400, (redirect, response.text)
        assert response.json()["error"] == "invalid_redirect_uri"
    loopback = await client.post(
        "/oauth/register",
        json={"client_name": "Native", "redirect_uris": ["http://127.0.0.1:8976/callback"]},
    )
    assert loopback.status_code == 201, loopback.text


async def test_authorize_redirects_to_consent_only_for_a_valid_request(
    client: httpx.AsyncClient,
) -> None:
    params = await authorize_params(client)
    good = await client.get("/oauth/authorize", params=params, follow_redirects=False)
    assert good.status_code == 302, good.text
    location = urlparse(good.headers["location"])
    assert location.path == "/agents/authorize"
    assert parse_qs(location.query)["client_id"] == [params["client_id"]]

    for bad in (
        {"client_id": "fpc_unknown"},
        {"redirect_uri": "https://elsewhere.example.test/cb"},
        {"code_challenge_method": "plain"},
        {"code_challenge": ""},
        {"state": ""},
    ):
        response = await client.get(
            "/oauth/authorize", params={**params, **bad}, follow_redirects=False
        )
        assert response.status_code == 400, (bad, response.text)
        assert "location" not in response.headers


async def test_the_decision_requires_a_session_and_a_matching_ratification(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    params = await authorize_params(client)
    anonymous = await client.post(
        "/oauth/authorize/decision",
        json={
            **params,
            "scope": ratified({"pool_ids": [], "category": None}, 60000, FUTURE),
            "max_cap_cents": 60000,
            "expires_at": FUTURE,
        },
    )
    assert anonymous.status_code == 401

    csrf = await login(client, "oauth-binding@example.test")
    tampered = await client.post(
        "/oauth/authorize/decision",
        headers={"X-CSRF-Token": csrf},
        json={
            **params,
            "scope": ratified({"pool_ids": [], "category": None}, 60000, FUTURE),
            "max_cap_cents": 90000,
            "expires_at": FUTURE,
        },
    )
    assert tampered.status_code == 422, tampered.text
    codes = await db_session.scalar(text("SELECT count(*) FROM agent_oauth_codes"))
    assert codes == 0


async def test_the_code_is_stored_hashed_and_exchanges_once(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "oauth-flow@example.test")
    verifier, challenge = pkce()
    params = await authorize_params(client, code_challenge=challenge)
    approved = await decision(client, csrf, params)
    assert approved.status_code == 200, approved.text
    redirect_to = approved.json()["redirect_to"]
    query = parse_qs(urlparse(redirect_to).query)
    assert redirect_to.startswith(REDIRECT)
    assert query["state"] == ["state-123"]
    code = query["code"][0]

    stored = await db_session.scalar(text("SELECT code_hash FROM agent_oauth_codes"))
    assert stored == hash_token(HMAC_KEY, code)
    assert code not in stored

    exchanged = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": params["client_id"],
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    token = exchanged.json()["access_token"]
    assert TOKEN_SHAPE.match(token), token
    assert exchanged.json()["token_type"] == "Bearer"
    assert exchanged.json()["expires_in"] > 0

    replay = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": params["client_id"],
            "code_verifier": verifier,
        },
    )
    assert replay.status_code == 400

    row = await db_session.execute(
        text(
            "SELECT name, oauth_client_id, max_cap_cents, scope FROM delegations "
            "WHERE token_hash = :hash"
        ),
        {"hash": hash_token(HMAC_KEY, token)},
    )
    minted = row.mappings().one()
    assert minted["name"] == "Test assistant"
    assert minted["oauth_client_id"] == params["client_id"]
    assert minted["max_cap_cents"] == 60000

    usable = await client.get(
        "/agent/v1/pools?limit=1", headers={"Authorization": f"Bearer {token}"}
    )
    assert usable.status_code == 200, usable.text


async def test_a_wrong_verifier_or_redirect_never_exchanges(
    client: httpx.AsyncClient,
) -> None:
    csrf = await login(client, "oauth-pkce@example.test")
    verifier, challenge = pkce()
    params = await authorize_params(client, code_challenge=challenge)
    code = parse_qs(urlparse((await decision(client, csrf, params)).json()["redirect_to"]).query)[
        "code"
    ][0]

    wrong = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": params["client_id"],
            "code_verifier": base64.urlsafe_b64encode(b"w" * 48).decode().rstrip("="),
        },
    )
    assert wrong.status_code == 400

    mismatched = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://client.example.test/other",
            "client_id": params["client_id"],
            "code_verifier": verifier,
        },
    )
    assert mismatched.status_code == 400


async def test_an_expired_code_never_exchanges(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    csrf = await login(client, "oauth-expiry@example.test")
    verifier, challenge = pkce()
    params = await authorize_params(client, code_challenge=challenge)
    code = parse_qs(urlparse((await decision(client, csrf, params)).json()["redirect_to"]).query)[
        "code"
    ][0]
    await db_session.execute(
        text("UPDATE agent_oauth_codes SET created_at = now() - interval '11 minutes'")
    )
    await db_session.flush()

    response = await client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": params["client_id"],
            "code_verifier": verifier,
        },
    )
    assert response.status_code == 400


async def test_revoking_the_token_revokes_the_delegation(
    client: httpx.AsyncClient,
) -> None:
    csrf = await login(client, "oauth-revoke@example.test")
    verifier, challenge = pkce()
    params = await authorize_params(client, code_challenge=challenge)
    code = parse_qs(urlparse((await decision(client, csrf, params)).json()["redirect_to"]).query)[
        "code"
    ][0]
    token = (
        await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": params["client_id"],
                "code_verifier": verifier,
            },
        )
    ).json()["access_token"]

    revoked = await client.post("/oauth/revoke", data={"token": token})
    assert revoked.status_code == 200
    refused = await client.get(
        "/agent/v1/pools?limit=1", headers={"Authorization": f"Bearer {token}"}
    )
    assert refused.status_code == 401


async def test_mcp_refusal_advertises_the_resource_metadata(client: httpx.AsyncClient) -> None:
    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401
    header = response.headers.get("www-authenticate", "")
    assert header.startswith("Bearer"), header
    assert "resource_metadata=" in header
    assert "/.well-known/oauth-protected-resource" in header


async def test_the_minted_token_keeps_the_ratified_cap(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A mandate narrower than the buyer's ceiling stays narrower after exchange."""
    csrf = await login(client, "oauth-cap@example.test")
    verifier, challenge = pkce()
    params = await authorize_params(client, code_challenge=challenge)
    approved = await decision(client, csrf, params, cap=45000)
    assert approved.status_code == 200, approved.text
    code = parse_qs(urlparse(approved.json()["redirect_to"]).query)["code"][0]
    token = (
        await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": params["client_id"],
                "code_verifier": verifier,
            },
        )
    ).json()["access_token"]
    cap = await db_session.scalar(
        text("SELECT max_cap_cents FROM delegations WHERE token_hash = :hash"),
        {"hash": hash_token(HMAC_KEY, token)},
    )
    assert cap == 45000
    assert datetime.now(UTC) < datetime(2099, 1, 1, tzinfo=UTC) + timedelta(days=1)


async def test_consent_preview_reads_registered_name_and_validates_redirect(
    client: httpx.AsyncClient,
) -> None:
    params = await authorize_params(client)
    preview = await client.get(
        "/oauth/authorize", params=params, headers={"Accept": "application/json"}
    )
    assert preview.status_code == 200
    assert preview.json() == {"client_name": "Test assistant", "redirect_uri": REDIRECT}
    refused = await client.get(
        "/oauth/authorize",
        params={**params, "redirect_uri": "https://evil.test"},
        headers={"Accept": "application/json"},
    )
    assert refused.status_code == 400


async def test_deny_returns_access_denied_without_minting_a_code(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    params = await authorize_params(client)
    csrf = await login(client, "oauth-deny@example.test")
    response = await client.post(
        "/oauth/authorize/decision",
        headers={"X-CSRF-Token": csrf},
        json={**params, "approved": False},
    )
    assert response.status_code == 200, response.text
    uri = urlparse(response.json()["redirect_to"])
    assert uri.scheme + "://" + uri.netloc + uri.path == REDIRECT
    assert parse_qs(uri.query) == {"error": ["access_denied"], "state": ["state-123"]}
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM agent_oauth_codes WHERE client_id = :client"),
            {"client": params["client_id"]},
        )
        == 0
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM delegations WHERE oauth_client_id = :client"),
            {"client": params["client_id"]},
        )
        == 0
    )
    refused = await client.post(
        "/oauth/authorize/decision",
        headers={"X-CSRF-Token": csrf},
        json={**params, "approved": False, "redirect_uri": "https://evil.test"},
    )
    assert refused.status_code == 400
