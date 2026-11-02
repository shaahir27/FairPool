"""Sandbox-only OAuth grant exchange and userinfo retrieval (S1, CR-6)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Final

import httpx

from fairpool.config import SANDBOX_API_HOST, Settings, assert_sandbox_host
from fairpool.domain.paypal_identity import PayPalIdentityDeclined, PayPalIdentityUnavailable
from fairpool.ports import ProviderProfile, ProviderTokens

logger = logging.getLogger("fairpool.adapters.paypal.identity")

#: The documented identity endpoints, in the order that keeps one identifier.
#: ``openidconnect/userinfo?schema=openid`` carries the standard claims for the
#: scopes the buyer approved; ``oauth2/userinfo?schema=paypalv1.1`` is the shape S1
#: verified and carries the address in its own field names. The second response is
#: merged only when it names the same account (see ``_same_account``), because account
#: dedupe (BD-12) compares those keys raw: one profile can never be keyed twice.
_IDENTITY_ENDPOINTS: Final[tuple[tuple[str, str], ...]] = (
    ("/v1/identity/openidconnect/userinfo", "openid"),
    ("/v1/identity/oauth2/userinfo", "paypalv1.1"),
)

#: The prefix ``schema=paypalv1.1`` puts in front of the same ``user_id`` that
#: ``schema=openid`` reports bare.
_IDENTITY_URL_PREFIX: Final[str] = "https://www.paypal.com/webapps/auth/identity/user/"

#: Claim names by shape, so a name from one endpoint is not read as another's.
_STREET_KEYS: Final[tuple[str, ...]] = ("street_address", "address_line_1", "line1")
_STREET2_KEYS: Final[tuple[str, ...]] = (
    "street_address2",
    "address_line_2",
    "line2",
)
_CITY_KEYS: Final[tuple[str, ...]] = ("locality", "city")
_REGION_KEYS: Final[tuple[str, ...]] = ("region", "state", "regional_subdiv")
_POSTAL_KEYS: Final[tuple[str, ...]] = ("postal_code", "zip")
_COUNTRY_KEYS: Final[tuple[str, ...]] = ("country", "country_code", "country_alpha_2")
_EMAIL_KEYS: Final[tuple[str, ...]] = ("email", "email_address")


def _first_text(source: Any, keys: tuple[str, ...]) -> str:
    """The first non-empty string under any of ``keys``; "" when there is none."""
    if not isinstance(source, dict):
        return ""
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _same_account(first: str, other: str) -> bool:
    """Whether two reported identifiers name one PayPal account.

    The two documented schemas differ in shape only: ``paypalv1.1`` prefixes the same
    ``user_id`` with its identity URL. This compares, it never converts - the stored
    key stays the first response's raw value, so dedupe (BD-12) is untouched.
    """
    if not first or not other:
        return False
    if first == other:
        return True
    for left, right in ((first, other), (other, first)):
        if left.startswith(_IDENTITY_URL_PREFIX) and left[len(_IDENTITY_URL_PREFIX) :] == right:
            return True
    return False


def _first_email(value: Any) -> str:
    """The primary entry of an ``emails`` claim, else its first, else ``""``."""
    if not isinstance(value, list):
        return ""
    fallback = ""
    for item in value:
        candidate = item if isinstance(item, str) else _first_text(item, ("value", "email"))
        candidate = candidate.strip()
        if not candidate:
            continue
        if isinstance(item, dict) and item.get("primary") is True:
            return candidate
        fallback = fallback or candidate
    return fallback


def _profile_address(body: dict[str, Any]) -> dict[str, str] | None:
    """The address claim in either documented spelling, or None when unreadable."""
    source: Any = _claim_address(body.get("address"))
    if not isinstance(source, dict):
        source = None
        items = body.get("addresses")
        for item in items if isinstance(items, list) else ():
            candidate = _claim_address(item)
            if candidate is None:
                continue
            if candidate.get("primary") is True:
                source = candidate
                break
            source = source or candidate
    if not isinstance(source, dict):
        return None
    street = _first_text(source, _STREET_KEYS)
    lines = [line.strip() for line in street.split("\n") if line.strip()]
    address = {
        "line1": (lines[0] if lines else "")[:200],
        "line2": (_first_text(source, _STREET2_KEYS) or (lines[1] if len(lines) > 1 else ""))[:200],
        "city": _first_text(source, _CITY_KEYS)[:120],
        "region": _first_text(source, _REGION_KEYS)[:100],
        "postal_code": _first_text(source, _POSTAL_KEYS)[:32],
        "country_code": _country_code(source, _COUNTRY_KEYS),
    }
    return address if address["line1"] or address["city"] else None


def _country_code(source: Any, keys: tuple[str, ...]) -> str:
    """A two-letter country as stored, "" when the claim cannot be read as one.

    Guessing "US" for a country FairPool has never seen would place a foreign address
    in a US-only pool, so an unreadable claim is reported as absent instead.
    """
    raw = _first_text(source, keys)
    if not raw:
        return ""
    if raw == "United States":
        return "US"
    return raw.upper() if len(raw) == 2 else ""


def _granted_scopes(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(dict.fromkeys(value.split()))
    if isinstance(value, list):
        return tuple(dict.fromkeys(item for item in value if isinstance(item, str)))
    return ()


def _id_token_claims(id_token: str) -> dict[str, Any]:
    """The payload of PayPal's ID token, as claim names and values for the form.

    ``developer.paypal.com/log-in/references`` returns the approved attributes in the
    ID token, not in userinfo, so a Login grant that asks for ``profile email address``
    is unreadable without this. Nothing here authenticates on it: the value arrives on
    a TLS response to a request signed with our own client credentials, the same trust
    the userinfo body gets, and it only ever prefills fields the buyer then edits. The
    account identifier is never taken from it (BD-12).
    """
    try:
        segment = id_token.split(".")[1]
        padded = segment + "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (IndexError, ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _claim_address(value: Any) -> dict[str, Any] | None:
    """The ``address`` claim as an object, or as the JSON string an ID token carries."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


class RestPayPalIdentity:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        assert_sandbox_host(settings.paypal_api_base, SANDBOX_API_HOST)
        self.settings = settings
        self.client = client

    async def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            if self.client is not None:
                response = await self.client.request(
                    method,
                    self.settings.paypal_api_base + path,
                    timeout=15,
                    follow_redirects=False,
                    **kwargs,
                )
            else:
                async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                    response = await client.request(
                        method, self.settings.paypal_api_base + path, **kwargs
                    )
            if response.status_code in {400, 401, 403}:
                raise PayPalIdentityDeclined
            if not response.is_success:
                raise PayPalIdentityUnavailable
            body = response.json()
            if not isinstance(body, dict):
                raise PayPalIdentityUnavailable
            return body
        except PayPalIdentityDeclined:
            raise
        except (httpx.HTTPError, ValueError):
            # I14: never attach provider response text, credentials or grant values.
            raise PayPalIdentityUnavailable from None

    async def exchange_code(self, code: str) -> ProviderTokens:
        body = await self._call(
            "POST",
            "/v1/oauth2/token",
            auth=(
                self.settings.paypal_client_id,
                self.settings.paypal_client_secret.get_secret_value(),
            ),
            data={"grant_type": "authorization_code", "code": code},
        )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise PayPalIdentityUnavailable
        expires = body.get("expires_in", 0)
        if isinstance(expires, bool) or not isinstance(expires, int) or expires < 0:
            raise PayPalIdentityUnavailable
        granted = _granted_scopes(body.get("scope"))
        # Scope names only, never a token or a grant value. Whether PayPal echoes
        # ``profile email address`` back is what separates a parse gap in this file
        # from an attribute set the Sandbox app never approved (CR-6).
        logger.info(
            "paypal.identity.token exchanged fields=%s granted_scopes=%s",
            sorted(body),
            list(granted),
        )
        raw_id_token = body.get("id_token")
        return ProviderTokens(
            access_token=token,
            expires_in=expires,
            granted_scopes=granted,
            id_token=raw_id_token if isinstance(raw_id_token, str) else None,
        )

    async def _fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {access_token}"}
        profile: dict[str, Any] | None = None
        profile_id = ""
        last_failure: Exception | None = None
        for path, schema in _IDENTITY_ENDPOINTS:
            try:
                body = await self._call("GET", path, params={"schema": schema}, headers=headers)
            except (PayPalIdentityUnavailable, PayPalIdentityDeclined) as error:
                last_failure = error
                logger.info("paypal.identity.userinfo %s schema=%s failed", path, schema)
                continue
            identifier = _first_text(body, ("user_id", "sub"))
            logger.info(
                "paypal.identity.userinfo %s schema=%s fields=%s identifier_present=%s",
                path,
                schema,
                sorted(body),
                bool(identifier),
            )
            if not identifier:
                continue
            if profile is None:
                profile, profile_id = dict(body), identifier
                continue
            if not _same_account(profile_id, identifier):
                logger.info(
                    "paypal.identity.userinfo %s schema=%s identifier differs; ignored",
                    path,
                    schema,
                )
                continue
            for key, value in body.items():
                if not profile.get(key) and value not in (None, "", [], {}):
                    profile[key] = value
        if profile is None:
            if last_failure is not None:
                raise last_failure
            raise PayPalIdentityUnavailable
        return profile

    async def userinfo(self, access_token: str, id_token: str | None = None) -> ProviderProfile:
        """One identifier plus whatever profile claims the approved scopes carried.

        The raw identifier comes from userinfo only and is used exactly as the
        provider sent it: login derives the same key from the same rule, so one
        PayPal account maps to one FairPool account (BD-12). The profile claims come
        from userinfo first and then from the ID token, because PayPal's Login
        reference returns the approved attributes in the ID token.
        """
        body = await self._fetch_userinfo(access_token)
        identifier = _first_text(body, ("user_id", "sub"))
        if not identifier:
            raise PayPalIdentityUnavailable
        if id_token:
            claims = _id_token_claims(id_token)
            logger.info("paypal.identity.id_token claims=%s", sorted(claims))
            for key, value in claims.items():
                if key in ("user_id", "sub") or not value or body.get(key):
                    continue
                body[key] = value

        details: dict[str, Any] = {}
        display_name = _first_text(body, ("name",)) or " ".join(
            part
            for part in (_first_text(body, ("given_name",)), _first_text(body, ("family_name",)))
            if part
        )
        if 0 < len(display_name) <= 120:
            details["display_name"] = display_name

        email = _first_text(body, _EMAIL_KEYS) or _first_email(body.get("emails"))
        if 0 < len(email) <= 320:
            details["email"] = email

        address = _profile_address(body)
        if address is not None:
            details["address"] = address

        logger.info("paypal.identity.profile fields=%s", sorted(details))
        return ProviderProfile(account_id=identifier, details=details)
