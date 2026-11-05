"""Typed application settings and the PayPal Sandbox host guard (T00A03).

Every variable in `docs/contracts/config-and-errors.md` section 1 has exactly
one field here. Secrets are `SecretStr` so they never leak through logs or
serialisation (I14). Nothing is loaded at import: call `get_settings()`.
"""

from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache
from typing import Final, Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only PayPal hosts this project may ever call (FR-PP-06, I1).
SANDBOX_API_HOST: Final[str] = "api-m.sandbox.paypal.com"
SANDBOX_CHECKOUT_HOST: Final[str] = "www.sandbox.paypal.com"


class ForbiddenHost(Exception):
    """Raised when a configured URL points anywhere but the PayPal Sandbox."""


def assert_sandbox_host(url: str, expected: str) -> None:
    """Refuse any URL that is not exactly the expected Sandbox origin.

    Requires https, the exact hostname (no suffix or subdomain tricks), no
    userinfo and no port other than 443 (FR-PP-06, paypal-adapter.md section 1).
    """
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ForbiddenHost(f"Only https://{expected} on port 443 is allowed") from exc

    if (
        parsed.scheme != "https"
        or hostname != expected
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise ForbiddenHost(f"Only https://{expected} on port 443 is allowed")


class Settings(BaseSettings):
    """Environment-driven settings; one field per contract variable."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Comma-separated tuple fields must reach the validators as strings;
        # pydantic-settings would otherwise JSON-decode them first.
        enable_decoding=False,
    )

    # The hosted profile is the safe default: an unset APP_ENV must not silently
    # enable the local-only helpers (force-award, mock toggles). A developer sets
    # APP_ENV=local in .env, which every local entry point already ships.
    app_env: Literal["local", "test", "render"] = "render"
    database_url: SecretStr
    secret_key: SecretStr
    hmac_key: SecretStr
    receipt_signing_key: SecretStr
    address_encryption_key: SecretStr
    public_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:5173"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    paypal_env: Literal["sandbox"] = "sandbox"
    paypal_client_id: str
    paypal_client_secret: SecretStr
    paypal_api_base: str = f"https://{SANDBOX_API_HOST}"
    paypal_checkout_base: str = f"https://{SANDBOX_CHECKOUT_HOST}"
    paypal_webhook_id: str = ""
    paypal_login_enabled: bool = False
    paypal_login_redirect_uri: str = ""
    oauth_state_ttl_s: int = Field(default=600, ge=60, le=3600)

    payment_router: Literal["fake", "single_seller", "payee_email", "platform"] = "single_seller"
    payment_mode: Literal["vault_charge", "authorize_capture", "capture_only"] = "vault_charge"
    bid_pricing_mode: Literal["flat_delivered", "itemised"] = "flat_delivered"
    vault_token_key: SecretStr | None = None
    vault_consent_version: str = "v1"
    vault_charge_concurrency: int = 5
    vault_setup_ttl_s: int = Field(default=900, ge=60, le=3600)
    vault_real_save_enabled: bool = False
    authorize_use_request_id: bool = True
    paypal_payload_level: int = Field(default=0, ge=0, le=3)
    paypal_approval_ui: Literal["sdk_popup", "redirect"] = "sdk_popup"
    paypal_sdk_auth: Literal["client_id", "client_token"] = "client_id"
    shipment_tracking_enabled: bool = True
    paypal_mcp_verification: Literal["paypal_read_subset", "fairpool_tool"] = "paypal_read_subset"
    single_seller_email: str | None = None
    single_seller_merchant_id: str = ""
    allowed_payer_countries: tuple[str, ...] = ("US",)
    platform_fee_enabled: bool = False

    dedupe_mode: Literal["full", "two_keys", "checkout_only"] = "two_keys"
    require_paypal_link: bool = False
    webhooks_enabled: bool = False
    mock_toggles_enabled: bool = False

    search_backend: Literal["elastic", "postgres"] = "postgres"
    elasticsearch_url: str = ""
    elasticsearch_api_key: SecretStr = SecretStr("")
    elastic_inference_id: str = ""
    elastic_index_prefix: str = "fairpool"
    search_timeout_ms: int = Field(default=1500, ge=100, le=10000)
    similarity_check_enabled: bool = True
    mcp_enabled: bool = True
    merchant_api_enabled: bool = True
    zapier_bridge: Literal["off", "managed"] = "off"

    ai_enabled: bool = True
    gemini_api_key: SecretStr = SecretStr("")
    ai_model_parse: str = "gemini-3.5-flash-lite"
    ai_model_sim: str = "gemini-3.5-flash-lite"
    beacon_mode: Literal["drand", "demo"] = "demo"
    drand_base_url: str = ""
    drand_chain_hash: str = ""

    timing_profile: Literal["demo", "prodlike"] = "demo"
    capture_buffer: int = 0
    capture_concurrency: int = 5
    reconciler_interval_s: int = 60
    worker_concurrency: int = 4
    rate_limit_enabled: bool = True
    # How long a webhook's raw body is kept before the reconciler replaces it with
    # "[expired]": the ids and amounts stay, the payer's identity does not (I14).
    webhook_raw_retention_s: int = Field(default=604800, ge=3600)

    @field_validator("cors_origins", "allowed_payer_countries", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept the comma-separated form used in environment files."""
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_with_credentials(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # create_app always sends ``allow_credentials=True`` (the session cookie), and
        # a wildcard origin with credentials lets any site read an authenticated
        # response. The combination is refused at load rather than shipped.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must name origins; '*' is not allowed")
        return value

    @field_validator(
        "database_url",
        "secret_key",
        "hmac_key",
        "receipt_signing_key",
        "address_encryption_key",
        "paypal_client_id",
        "paypal_client_secret",
        mode="after",
    )
    @classmethod
    def _required_values_not_blank(cls, value: SecretStr | str) -> SecretStr | str:
        # "none (required)" means a present but empty .env value is still missing.
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not raw.strip():
            raise ValueError("This setting is required and must not be empty")
        return value

    @field_validator("address_encryption_key")
    @classmethod
    def _fernet_key_shape(cls, value: SecretStr) -> SecretStr:
        # BD-11: the address book seals with Fernet. A wrong-shaped key must fail the
        # deploy, not every signup request that builds the book.
        try:
            Fernet(value.get_secret_value().encode())
        except (InvalidToken, ValueError) as exc:
            raise ValueError("ADDRESS_ENCRYPTION_KEY must be a Fernet key") from exc
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("allowed_payer_countries")
    @classmethod
    def _iso2_countries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        countries: list[str] = []
        for country in value:
            normalised = country.strip().upper()
            if len(normalised) != 2 or not normalised.isalpha():
                raise ValueError("ALLOWED_PAYER_COUNTRIES entries must be two-letter ISO codes")
            countries.append(normalised)
        if not countries:
            raise ValueError("ALLOWED_PAYER_COUNTRIES must not be empty")
        return tuple(countries)

    @model_validator(mode="after")
    def _validate_invariants(self) -> Settings:
        # The sandbox guard is checked at settings load and again by create_app.
        assert_sandbox_host(self.paypal_api_base, SANDBOX_API_HOST)
        assert_sandbox_host(self.paypal_checkout_base, SANDBOX_CHECKOUT_HOST)

        if self.platform_fee_enabled:
            raise ValueError("PLATFORM_FEE_ENABLED must remain false (G9 failed)")
        if self.require_paypal_link and self.dedupe_mode == "checkout_only":
            raise ValueError("REQUIRE_PAYPAL_LINK cannot be true when DEDUPE_MODE=checkout_only")

        vault_key = self.vault_token_key.get_secret_value() if self.vault_token_key else ""
        if self.payment_mode == "vault_charge" and not vault_key:
            raise ValueError("VAULT_TOKEN_KEY is required when PAYMENT_MODE=vault_charge")
        if vault_key:
            self._check_vault_key(vault_key)

        if self.payment_router == "single_seller" and not self.single_seller_email:
            raise ValueError("SINGLE_SELLER_EMAIL is required when PAYMENT_ROUTER=single_seller")
        if self.search_backend == "elastic" and (
            not self.elasticsearch_url or not self.elasticsearch_api_key.get_secret_value()
        ):
            raise ValueError(
                "ELASTICSEARCH_URL and ELASTICSEARCH_API_KEY are required "
                "when SEARCH_BACKEND=elastic"
            )
        if self.beacon_mode == "drand" and (not self.drand_base_url or not self.drand_chain_hash):
            raise ValueError(
                "DRAND_BASE_URL and DRAND_CHAIN_HASH are required when BEACON_MODE=drand"
            )
        if self.ai_enabled and not self.gemini_api_key.get_secret_value():
            raise ValueError("GEMINI_API_KEY is required when AI_ENABLED=true")

        if not self.paypal_login_redirect_uri:
            self.paypal_login_redirect_uri = (
                f"{self.public_base_url.rstrip('/')}/api/v1/paypal/login/callback"
            )
        return self

    @staticmethod
    def _check_vault_key(value: str) -> None:
        """VAULT_TOKEN_KEY is 32 raw bytes encoded as base64 (vault-charge.md)."""
        try:
            decoded = base64.b64decode(value, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("VAULT_TOKEN_KEY must be base64-encoded") from exc
        if len(decoded) != 32:
            raise ValueError("VAULT_TOKEN_KEY must decode to 32 bytes")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once; import time never reads the environment."""
    return Settings(_env_file=None if os.environ.get("APP_ENV") == "test" else ".env")  # type: ignore[call-arg]
