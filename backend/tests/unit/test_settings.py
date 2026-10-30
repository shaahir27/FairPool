"""T00A03: settings parity with config-and-errors.md and conditional rules."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from fairpool.config import Settings, get_settings

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/config-and-errors.md"
ENV_EXAMPLE = ROOT / ".env.example"

REQUIRED = object()

SECRET_FIELDS = (
    "database_url",
    "secret_key",
    "hmac_key",
    "receipt_signing_key",
    "address_encryption_key",
    "paypal_client_secret",
    "vault_token_key",
    "elasticsearch_api_key",
    "anthropic_api_key",
)

BASE_VALUES: dict[str, Any] = {
    "database_url": "postgresql+asyncpg://fairpool:dummy-db-password@localhost/fairpool",
    "secret_key": "dummy-secret-key",
    "hmac_key": "dummy-hmac-key",
    "receipt_signing_key": "dummy-receipt-signing-key",
    "address_encryption_key": "dummy-address-encryption-key",
    "paypal_client_id": "dummy-sandbox-client-id",
    "paypal_client_secret": "dummy-sandbox-client-secret",
}

# Values that satisfy every conditional rule; tests override what they exercise.
CONDITIONAL_SAFE: dict[str, Any] = {
    "payment_router": "fake",
    "payment_mode": "authorize_capture",
    "ai_enabled": False,
    "search_backend": "postgres",
    "beacon_mode": "demo",
}


def make_settings(**overrides: Any) -> Settings:
    """Build Settings hermetically: no .env file, no ambient environment leak."""
    kwargs: dict[str, Any] = {}
    for name, field in Settings.model_fields.items():
        if field.is_required():
            continue
        kwargs[name] = field.get_default(call_default_factory=True)
    kwargs.update(BASE_VALUES)
    kwargs.update(CONDITIONAL_SAFE)
    kwargs.update(overrides)
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


def vault_key(raw: bytes = b"k" * 32) -> str:
    return base64.b64encode(raw).decode("ascii")


def contract_defaults() -> dict[str, str]:
    text = CONTRACT.read_text(encoding="utf-8")
    section = text.split("## 1. Environment variables", 1)[1].split("## 2.", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows[cells[0].strip("`")] = cells[1]
    return rows


def expected_default(name: str, raw: str) -> Any:
    value = raw.strip().strip("`")
    if value == "none (required)":
        return REQUIRED
    if value.startswith("none (required when"):
        return None
    if value == "empty" or value.startswith("${"):
        return ""
    if value in ("true", "false"):
        return value == "true"
    if value.lstrip("-").isdigit():
        return int(value)
    if name in ("cors_origins", "allowed_payer_countries"):
        return (value,)
    return value


def plain(value: Any) -> Any:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def test_contract_has_sixty_variables() -> None:
    assert len(contract_defaults()) == 60
    assert len(Settings.model_fields) == 60


def test_csv_env_values_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: CI exports CORS_ORIGINS as a plain comma-separated string."""
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    monkeypatch.setenv("ALLOWED_PAYER_COUNTRIES", "us, ca")
    kwargs: dict[str, Any] = {}
    for name, field in Settings.model_fields.items():
        if field.is_required():
            continue
        kwargs[name] = field.get_default(call_default_factory=True)
    kwargs.update(BASE_VALUES)
    kwargs.update(CONDITIONAL_SAFE)
    kwargs.pop("cors_origins", None)
    kwargs.pop("allowed_payer_countries", None)
    settings = Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]
    assert settings.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")
    assert settings.allowed_payer_countries == ("US", "CA")


def test_field_names_match_contract_exactly() -> None:
    contract = {name.lower() for name in contract_defaults()}
    assert set(Settings.model_fields) == contract


def test_defaults_match_contract() -> None:
    for name, raw in contract_defaults().items():
        field = Settings.model_fields[name.lower()]
        expected = expected_default(name.lower(), raw)
        if expected is REQUIRED:
            assert field.is_required(), f"{name} must be required"
            continue
        actual = plain(field.get_default(call_default_factory=True))
        assert actual == expected, f"{name}: default {actual!r} != {expected!r}"


def test_effective_defaults_and_redirect_derivation() -> None:
    settings = make_settings()
    assert settings.cors_origins == ("http://localhost:5173",)
    assert settings.allowed_payer_countries == ("US",)
    assert settings.log_level == "INFO"
    assert settings.paypal_api_base == "https://api-m.sandbox.paypal.com"
    assert settings.paypal_checkout_base == "https://www.sandbox.paypal.com"
    assert (
        settings.paypal_login_redirect_uri == "http://localhost:8000/api/v1/paypal/login/callback"
    )
    assert settings.paypal_payload_level == 0
    assert settings.platform_fee_enabled is False


def test_redirect_uri_uses_public_base_and_stays_when_explicit() -> None:
    derived = make_settings(public_base_url="https://api.fairpool.test/")
    assert (
        derived.paypal_login_redirect_uri
        == "https://api.fairpool.test/api/v1/paypal/login/callback"
    )
    explicit = make_settings(paypal_login_redirect_uri="https://app.test/login/cb")
    assert explicit.paypal_login_redirect_uri == "https://app.test/login/cb"


def test_secret_fields_are_secretstr_and_masked() -> None:
    settings = make_settings(
        payment_mode="vault_charge",
        vault_token_key=vault_key(),
        elasticsearch_api_key="dummy-elastic-key",
        anthropic_api_key="dummy-anthropic-key",
    )
    for name in SECRET_FIELDS:
        value = getattr(settings, name)
        assert isinstance(value, SecretStr), name
        assert str(value) == "**********", name

    dumped = settings.model_dump_json()
    for name in SECRET_FIELDS:
        secret = settings.__dict__[name]
        raw = secret.get_secret_value() if secret is not None else ""
        if raw:
            assert raw not in dumped
            assert raw not in repr(settings)


@pytest.mark.parametrize(
    "field",
    [
        "database_url",
        "secret_key",
        "hmac_key",
        "receipt_signing_key",
        "address_encryption_key",
        "paypal_client_id",
        "paypal_client_secret",
    ],
)
def test_required_values_must_not_be_blank(field: str) -> None:
    with pytest.raises(ValidationError, match="required"):
        make_settings(**{field: ""})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_env", "production"),
        ("log_level", "TRACE"),
        ("paypal_env", "live"),
        ("payment_router", "platform_fee"),
        ("payment_mode", "capture"),
        ("bid_pricing_mode", "itemized"),
        ("dedupe_mode", "none"),
        ("paypal_approval_ui", "popup"),
        ("paypal_sdk_auth", "token"),
        ("paypal_mcp_verification", "mcp"),
        ("search_backend", "pg"),
        ("beacon_mode", "random"),
        ("timing_profile", "fast"),
        ("zapier_bridge", "on"),
    ],
)
def test_each_literal_rejects_an_invalid_value(field: str, value: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        make_settings(**{field: value})
    locations = [error["loc"] for error in excinfo.value.errors()]
    assert any(loc and loc[0] == field for loc in locations), locations


def test_vault_charge_requires_a_32_byte_base64_key() -> None:
    with pytest.raises(ValidationError, match="VAULT_TOKEN_KEY"):
        make_settings(payment_mode="vault_charge")

    with pytest.raises(ValidationError, match="32 bytes"):
        make_settings(payment_mode="vault_charge", vault_token_key=vault_key(b"k" * 16))

    with pytest.raises(ValidationError, match="base64"):
        make_settings(payment_mode="vault_charge", vault_token_key="not base64!!!")

    settings = make_settings(payment_mode="vault_charge", vault_token_key=vault_key())
    assert settings.vault_token_key is not None
    assert len(base64.b64decode(settings.vault_token_key.get_secret_value())) == 32


def test_single_seller_requires_payee_email() -> None:
    with pytest.raises(ValidationError, match="SINGLE_SELLER_EMAIL"):
        make_settings(payment_router="single_seller")
    settings = make_settings(
        payment_router="single_seller",
        single_seller_email="seller@example.test",
    )
    assert settings.single_seller_email == "seller@example.test"


def test_elastic_requires_url_and_api_key() -> None:
    with pytest.raises(ValidationError, match="ELASTICSEARCH_URL"):
        make_settings(search_backend="elastic")
    with pytest.raises(ValidationError, match="ELASTICSEARCH_API_KEY"):
        make_settings(
            search_backend="elastic",
            elasticsearch_url="https://elastic.example.test",
        )
    settings = make_settings(
        search_backend="elastic",
        elasticsearch_url="https://elastic.example.test",
        elasticsearch_api_key="dummy-elastic-key",
    )
    assert settings.search_backend == "elastic"


def test_drand_requires_url_and_chain_hash() -> None:
    with pytest.raises(ValidationError, match="DRAND_BASE_URL"):
        make_settings(beacon_mode="drand")
    with pytest.raises(ValidationError, match="DRAND_CHAIN_HASH"):
        make_settings(beacon_mode="drand", drand_base_url="https://drand.example.test")
    settings = make_settings(
        beacon_mode="drand",
        drand_base_url="https://drand.example.test",
        drand_chain_hash="dummy-chain-hash",
    )
    assert settings.drand_chain_hash == "dummy-chain-hash"


def test_ai_enabled_requires_anthropic_key() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        make_settings(ai_enabled=True)
    assert make_settings(ai_enabled=False).anthropic_api_key.get_secret_value() == ""
    settings = make_settings(ai_enabled=True, anthropic_api_key="dummy-anthropic-key")
    assert settings.anthropic_api_key.get_secret_value() == "dummy-anthropic-key"


def test_require_paypal_link_conflicts_with_checkout_only() -> None:
    with pytest.raises(ValidationError, match="REQUIRE_PAYPAL_LINK"):
        make_settings(require_paypal_link=True, dedupe_mode="checkout_only")
    assert make_settings(require_paypal_link=True, dedupe_mode="two_keys").require_paypal_link


def test_platform_fee_must_stay_false() -> None:
    with pytest.raises(ValidationError, match="PLATFORM_FEE_ENABLED"):
        make_settings(platform_fee_enabled=True)


@pytest.mark.parametrize("level", [-1, 4, 99])
def test_payload_level_is_bounded(level: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(paypal_payload_level=level)


def test_payload_level_three_is_allowed() -> None:
    assert make_settings(paypal_payload_level=3).paypal_payload_level == 3


def test_country_list_is_uppercase_iso2_tuple() -> None:
    settings = make_settings(allowed_payer_countries="us, ca")
    assert settings.allowed_payer_countries == ("US", "CA")
    with pytest.raises(ValidationError, match="two-letter"):
        make_settings(allowed_payer_countries="USA")


def test_cors_origins_parse_as_a_tuple() -> None:
    settings = make_settings(cors_origins="https://a.test, https://b.test")
    assert settings.cors_origins == ("https://a.test", "https://b.test")


def env_example_names() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)\s*=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def test_env_example_lists_every_contract_name_and_compose_names() -> None:
    names = env_example_names()
    contract = set(contract_defaults())
    compose_only = {"POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD"}
    assert contract <= set(names)
    assert set(names) - contract == compose_only


def test_env_example_has_no_secret_values() -> None:
    names = env_example_names()
    for name in SECRET_FIELDS:
        raw = names[name.upper()].split("#", 1)[0].strip()
        assert raw == "", f"{name.upper()} must be empty in .env.example"


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in contract_defaults():
        monkeypatch.delenv(name, raising=False)
    values = {
        **{name.upper(): str(value) for name, value in BASE_VALUES.items()},
        "PAYMENT_ROUTER": "fake",
        "PAYMENT_MODE": "authorize_capture",
        "AI_ENABLED": "false",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        first = get_settings()
        second = get_settings()
        assert first is second
    finally:
        get_settings.cache_clear()
