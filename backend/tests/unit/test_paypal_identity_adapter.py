"""The login adapter only exchanges grants and retrieves the Sandbox identity."""

import base64
import json

import httpx
import pytest

from fairpool.adapters.paypal.identity import RestPayPalIdentity
from fairpool.domain.paypal_identity import PayPalIdentityDeclined, PayPalIdentityUnavailable
from tests.unit.test_settings import make_settings


async def test_login_adapter_returns_the_provider_identifier():
    async def handle(request):
        assert request.url.host == "api-m.sandbox.paypal.com"
        if request.url.path == "/v1/oauth2/token":
            assert b"grant_type=authorization_code" in request.content
            return httpx.Response(200, json={"access_token": "fixture-access", "expires_in": 60})
        assert request.headers["Authorization"] == "Bearer fixture-access"
        return httpx.Response(
            200,
            json={
                "user_id": "fixture-account",
                "name": "Pool Buyer",
                "email": "buyer@example.test",
                "address": {
                    "street_address": "12 Test Lane",
                    "locality": "Test City",
                    "region": "CA",
                    "postal_code": "90210",
                    "country": "US",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        tokens = await adapter.exchange_code("fixture-code")
        profile = await adapter.userinfo(tokens.access_token)
        assert profile.account_id == "fixture-account"
        assert profile.details["email"] == "buyer@example.test"
        assert profile.details["address"]["line1"] == "12 Test Lane"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_login_adapter_hides_provider_error_bodies(status):
    async def handle(request):
        return httpx.Response(status, text="private-provider-response")

    expected = PayPalIdentityDeclined if status in {400, 401, 403} else PayPalIdentityUnavailable
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        with pytest.raises(expected) as failure:
            await adapter.exchange_code("fixture-code")
        assert "private-provider-response" not in str(failure.value)
        assert "fixture-code" not in str(failure.value)


@pytest.mark.parametrize("body", [{}, {"user_id": ""}, {"user_id": 42}, []])
async def test_login_adapter_rejects_missing_or_malformed_identity(body):
    async def handle(request):
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        with pytest.raises(PayPalIdentityUnavailable):
            await adapter.userinfo("fixture-access")


async def test_login_adapter_parses_paypalv1_1_shape_with_emails_list_and_split_street():
    async def handle(request):
        assert request.url.host == "api-m.sandbox.paypal.com"
        assert request.url.path in (
            "/v1/identity/oauth2/userinfo",
            "/v1/identity/openidconnect/userinfo",
        )
        return httpx.Response(
            200,
            json={
                "user_id": "https://www.paypal.com/webapps/auth/identity/user/uid-12345",
                "sub": "uid-12345",
                "given_name": "Ada",
                "family_name": "Lovelace",
                "emails": [
                    {"value": "secondary@example.test", "primary": False},
                    {"value": "ada@example.test", "primary": True},
                ],
                "address": {
                    "street_address": "123 Algorithmic Way\nSuite 400",
                    "locality": "London",
                    "region": "England",
                    "postal_code": "SW1A 1AA",
                    "country": "GB",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        profile = await adapter.userinfo("fixture-access")
        assert profile.account_id == "https://www.paypal.com/webapps/auth/identity/user/uid-12345"
        assert profile.details["display_name"] == "Ada Lovelace"
        assert profile.details["email"] == "ada@example.test"
        assert profile.details["address"]["line1"] == "123 Algorithmic Way"
        assert profile.details["address"]["line2"] == "Suite 400"
        assert profile.details["address"]["city"] == "London"
        assert profile.details["address"]["region"] == "England"
        assert profile.details["address"]["postal_code"] == "SW1A 1AA"
        assert profile.details["address"]["country_code"] == "GB"


async def test_login_adapter_falls_back_when_first_candidate_unavailable():
    calls = []

    async def handle(request):
        calls.append(request.url.path + "?" + request.url.query.decode())
        if len(calls) == 1:
            return httpx.Response(404, json={"error": "not_found"})
        return httpx.Response(
            200,
            json={
                "sub": "sub-987",
                "name": "Grace Hopper",
                "email": "grace@example.test",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        profile = await adapter.userinfo("fixture-access")
        assert len(calls) == 2
        assert profile.account_id == "sub-987"
        assert profile.details["display_name"] == "Grace Hopper"
        assert profile.details["email"] == "grace@example.test"
        assert "address" not in profile.details


async def test_login_adapter_handles_partial_claims_and_addresses_array():
    async def handle(request):
        return httpx.Response(
            200,
            json={
                "user_id": "https://www.paypal.com/webapps/auth/identity/user/raw-identifier-123",
                "given_name": "Katherine",
                "emails": [
                    {"value": "katherine@example.test"},
                ],
                "addresses": [
                    {
                        "line1": "456 Orbit Drive",
                        "city": "Hampton",
                        "state": "VA",
                        "zip": "23666",
                        "country": "United States",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        profile = await adapter.userinfo("fixture-access")
        # Raw identifier preserved exactly
        assert (
            profile.account_id
            == "https://www.paypal.com/webapps/auth/identity/user/raw-identifier-123"
        )
        assert profile.details["display_name"] == "Katherine"
        assert profile.details["email"] == "katherine@example.test"
        assert profile.details["address"]["line1"] == "456 Orbit Drive"
        assert profile.details["address"]["city"] == "Hampton"
        assert profile.details["address"]["region"] == "VA"
        assert profile.details["address"]["postal_code"] == "23666"
        assert profile.details["address"]["country_code"] == "US"


async def test_claims_from_a_second_endpoint_never_rekey_the_account():
    """S1 recorded ``sub`` != ``user_id``: one profile may not be keyed twice (BD-12)."""

    async def handle(request):
        if request.url.path == "/v1/identity/openidconnect/userinfo":
            return httpx.Response(
                200,
                json={
                    "user_id": "UID-SAME",
                    "sub": "SUB-DIFFERENT",
                    "name": "Ada Lovelace",
                },
            )
        return httpx.Response(
            200,
            json={"user_id": "UID-OTHER", "email": "someone-else@example.test"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        profile = await RestPayPalIdentity(make_settings(), client=client).userinfo("t")
    assert profile.account_id == "UID-SAME"
    assert profile.details["display_name"] == "Ada Lovelace"
    assert "email" not in profile.details


async def test_paypalv1_1_email_address_and_country_alpha_2_are_read():
    async def handle(request):
        body: dict[str, object] = {"user_id": "UID-V11"}
        if request.url.path == "/v1/identity/oauth2/userinfo":
            body = {
                "user_id": "UID-V11",
                "name": "Grace Hopper",
                "email_address": "grace@example.test",
                "address": {
                    "address_line_1": "1 Cooper Square",
                    "address_line_2": "Floor 3",
                    "locality": "New York",
                    "regional_subdiv": "NY",
                    "postal_code": "10003",
                    "country_alpha_2": "us",
                },
            }
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        profile = await RestPayPalIdentity(make_settings(), client=client).userinfo("t")
    assert profile.details["email"] == "grace@example.test"
    assert profile.details["address"]["line2"] == "Floor 3"
    assert profile.details["address"]["region"] == "NY"
    assert profile.details["address"]["country_code"] == "US"


async def test_an_unreadable_country_is_absent_rather_than_guessed():
    async def handle(request):
        return httpx.Response(
            200,
            json={
                "user_id": "UID-COUNTRY",
                "name": "Ada",
                "address": {
                    "street_address": "1 Rue Test",
                    "locality": "Paris",
                    "country": "France",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        profile = await RestPayPalIdentity(make_settings(), client=client).userinfo("t")
    assert profile.details["address"]["country_code"] == ""
    assert profile.details["address"]["city"] == "Paris"


async def test_the_token_response_reports_the_scopes_it_granted():
    async def handle(request):
        return httpx.Response(
            200,
            json={
                "access_token": "fixture-access",
                "expires_in": 60,
                "scope": "openid profile email openid",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = await RestPayPalIdentity(make_settings(), client=client).exchange_code("c")
    assert tokens.granted_scopes == ("openid", "profile", "email")


def _jwt(claims: dict[str, object]) -> str:
    def part(value: object) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.signature-not-read"


async def test_the_id_token_carries_the_claims_paypal_put_there():
    """PayPal's Login reference returns the attributes in the ID token, not userinfo."""

    async def handle(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "fixture-access",
                    "expires_in": 60,
                    "scope": "openid profile email address",
                    "id_token": _jwt(
                        {
                            "sub": "SUB-DIFFERENT",
                            "name": "Ada Lovelace",
                            "email": "ada@example.test",
                            "address": json.dumps(
                                {
                                    "street_address": "12 Test Lane",
                                    "locality": "New York",
                                    "region": "NY",
                                    "postal_code": "10001",
                                    "country": "US",
                                }
                            ),
                        }
                    ),
                },
            )
        return httpx.Response(200, json={"user_id": "UID-ONLY", "sub": "SUB-DIFFERENT"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        tokens = await adapter.exchange_code("fixture-code")
        profile = await adapter.userinfo(tokens.access_token, tokens.id_token)
    assert tokens.granted_scopes == ("openid", "profile", "email", "address")
    assert profile.account_id == "UID-ONLY"
    assert profile.details["display_name"] == "Ada Lovelace"
    assert profile.details["email"] == "ada@example.test"
    assert profile.details["address"]["line1"] == "12 Test Lane"
    assert profile.details["address"]["country_code"] == "US"


async def test_an_id_token_never_rekeys_the_account():
    async def handle(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "expires_in": 60,
                    "id_token": _jwt({"sub": "OTHER-SUB", "name": "Ada"}),
                },
            )
        return httpx.Response(200, json={"user_id": "UID-KEEP"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        tokens = await adapter.exchange_code("fixture-code")
        profile = await adapter.userinfo(tokens.access_token, tokens.id_token)
    assert profile.account_id == "UID-KEEP"
    assert profile.details["display_name"] == "Ada"


async def test_the_two_schemas_same_account_in_different_forms_still_yields_claims():
    """openidconnect answers with a bare user_id and paypalv1.1 with its identity URL.

    The stored identifier stays the first raw value (BD-12); the claims the second
    schema carries must still reach the profile (CR-7).
    """

    async def handle(request):
        if request.url.path == "/v1/identity/openidconnect/userinfo":
            return httpx.Response(200, json={"user_id": "UID-7", "sub": "UID-7"})
        return httpx.Response(
            200,
            json={
                "user_id": "https://www.paypal.com/webapps/auth/identity/user/UID-7",
                "name": "Ada Lovelace",
                "email_address": "ada@example.test",
                "address": {
                    "street_address": "12 Test Lane",
                    "locality": "Test City",
                    "region": "CA",
                    "postal_code": "90210",
                    "country": "US",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        profile = await adapter.userinfo("fixture-access")
    assert profile.account_id == "UID-7"
    assert profile.details["display_name"] == "Ada Lovelace"
    assert profile.details["email"] == "ada@example.test"
    assert profile.details["address"]["line1"] == "12 Test Lane"


async def test_a_second_schema_answering_for_another_account_is_still_ignored():
    async def handle(request):
        if request.url.path == "/v1/identity/openidconnect/userinfo":
            return httpx.Response(200, json={"user_id": "UID-7"})
        return httpx.Response(
            200,
            json={
                "user_id": "https://www.paypal.com/webapps/auth/identity/user/UID-9",
                "name": "Someone Else",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = RestPayPalIdentity(make_settings(), client=client)
        profile = await adapter.userinfo("fixture-access")
    assert profile.account_id == "UID-7"
    assert profile.details == {}
