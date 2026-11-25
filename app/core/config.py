"""Application settings loaded from environment variables / `.env`."""

import json
import secrets
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.stores import STORES, STORES_BY_SLUG

API_V1_PREFIX = "/api/v1"

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type StoreAdapterMode = Literal["mock", "live"]
# dev_outbox: messages are written to files under DEV_OUTBOX_DIR instead of being delivered.
# Never allowed in production. None = dev_outbox in development, disabled elsewhere.
type EmailBackend = Literal["disabled", "dev_outbox", "smtp"]
type SmsBackend = Literal["disabled", "dev_outbox"]

MAX_STORE_TIMEOUT_SECONDS = 30.0
MIN_SECRET_LENGTH = 32
# Placeholder shipped in .env.example; refused in production.
EXAMPLE_SECRET = "change-me-to-a-long-random-string-in-every-environment"  # noqa: S105
# Used when AUTH_SECRET_KEY is unset outside production. Never leaves this process.
_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def _split_list(value: object) -> object:
    """Accept "a,b" or a JSON array for list settings read from the environment."""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            return json.loads(value)
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _reject_bool_seconds(value: object, what: str) -> object:
    """Booleans are ints in Python, so pydantic would read `true` as 1 second. Refuse them."""
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number of seconds, not {str(value).lower()}")
    return value


def _check_store_slug(slug: str) -> str:
    if slug not in STORES_BY_SLUG:
        known = ", ".join(sorted(STORES_BY_SLUG))
        raise ValueError(f"unknown store {slug!r} (known stores: {known})")
    return slug


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Validation errors must never echo values: they can be secrets or credential URLs.
        hide_input_in_errors=True,
    )

    # --- Application ---
    app_name: str = "ShopSync API"
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = "INFO"
    log_json: bool = False
    docs_enabled: bool = True

    # --- HTTP / CORS ---
    # NoDecode: parse the raw env string ourselves so both "a,b" and '["a","b"]' work.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- PostgreSQL ---
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://shopsync:shopsync@localhost:5432/shopsync"
    )
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    db_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    db_echo: bool = False

    # --- Redis ---
    redis_url: RedisDsn = RedisDsn("redis://localhost:6379/0")
    # Socket read/write timeout for the shared client (health checks etc.).
    redis_socket_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    # --- Caching (fail-open: Redis problems never break search) ---
    cache_enabled: bool = True
    cache_ttl_seconds: int = Field(default=1800, ge=0)
    # Results where some stores failed are kept briefly so recovered stores show up soon.
    cache_partial_ttl_seconds: int = Field(default=60, ge=0)
    # Per-operation limit for cache reads/writes; slower Redis = treated as a miss.
    cache_op_timeout_seconds: float = Field(default=0.25, gt=0, le=5)
    # After a Redis failure, skip the cache for this long instead of retrying on every request.
    cache_failure_backoff_seconds: float = Field(default=30.0, ge=0, le=3600)
    # Entries larger than this are not cached.
    cache_max_entry_bytes: int = Field(default=1_000_000, ge=1024, le=16_000_000)

    # --- Authentication ---
    # Signs access tokens (HS256). Production requires >= 32 characters and not the example.
    # Unset outside production: a random per-process key is used (sessions end on restart).
    auth_secret_key: SecretStr | None = None
    auth_issuer: str = Field(default="shopsync-api", min_length=1, max_length=100)
    auth_audience: str = Field(default="shopsync-web", min_length=1, max_length=100)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=90)
    # Cookies. Secure is forced in production; "none" SameSite (cross-site deployments) is
    # deliberately unsupported: serve the API same-origin (proxy) or same-site (subdomain).
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict"] = "lax"
    cookie_domain: str | None = None
    # Number of reverse proxies in front of the API whose X-Forwarded-For can be trusted
    # (0 = use the socket peer address; never trust client-supplied headers by default).
    trusted_proxy_count: int = Field(default=0, ge=0, le=5)
    # Auth rate limits (fixed windows; applied to login/register/... from Milestone 5.2).
    auth_rate_limit_window_seconds: int = Field(default=900, ge=10, le=86_400)
    auth_rate_limit_per_ip: int = Field(default=50, ge=1, le=100_000)
    auth_rate_limit_per_account: int = Field(default=10, ge=1, le=10_000)
    auth_signup_limit_per_hour: int = Field(default=10, ge=1, le=10_000)  # per IP
    auth_refresh_limit_per_ip: int = Field(default=60, ge=1, le=100_000)  # per window
    # Sessions (refresh-token families) per user; signing in beyond this ends the oldest.
    auth_max_sessions: int = Field(default=10, ge=1, le=100)
    # Two tabs refreshing at once: the loser presents a just-rotated token. Within this many
    # seconds that is a plain 401 (it retries with the new cookie), not token theft.
    refresh_reuse_grace_seconds: int = Field(default=10, ge=0, le=60)

    # --- Public URLs ---
    # The web app's origin: used in emailed links and as the only post-login redirect target.
    frontend_url: str = "http://localhost:5173"

    # --- Email (verification, password reset) ---
    email_backend: EmailBackend | None = None
    email_from: str = Field(default="ShopSync <no-reply@shopsync.local>", min_length=3)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_security: Literal["starttls", "ssl"] = "starttls"  # plaintext SMTP is not offered
    smtp_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    dev_outbox_dir: str = ".dev-outbox"
    email_verify_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=1440)

    # --- Phone OTP ---
    sms_backend: SmsBackend | None = None
    otp_ttl_seconds: int = Field(default=300, ge=60, le=1800)
    otp_max_attempts: int = Field(default=5, ge=1, le=10)
    otp_resend_cooldown_seconds: int = Field(default=60, ge=0, le=600)
    otp_sends_per_hour: int = Field(default=5, ge=1, le=50)  # per phone number

    # --- Google sign-in (OAuth 2.0 / OpenID Connect) ---
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    # Default: FRONTEND_URL + /api/v1/auth/google/callback (same origin through the proxy).
    google_redirect_uri: str | None = None

    # --- Health ---
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    # --- Store adapters ---
    # Stores searched for every query (slugs from app/core/stores.py).
    enabled_stores: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [s.slug for s in STORES]
    )
    # "mock" = demo data; "live" = official/affiliate APIs (stores without one are skipped).
    store_adapter_mode: StoreAdapterMode = "mock"
    store_adapter_timeout_seconds: float = Field(default=4.0, gt=0, le=MAX_STORE_TIMEOUT_SECONDS)
    # Per-store overrides, e.g. "amazon=6,croma=3" or '{"amazon": 6}'.
    store_adapter_timeouts: Annotated[dict[str, float], NoDecode] = Field(default_factory=dict)
    mock_adapter_latency_ms: int = Field(default=150, ge=0, le=10_000)
    # Development aid: fraction of mock calls that fail. Must be 0 in production.
    mock_adapter_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return json.loads(value)
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _validate_cors_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            if origin == "*":
                raise ValueError(
                    "wildcard origin is not allowed: auth cookies require explicit origins"
                )
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"invalid origin {origin!r}: must start with http(s)://")
        return [origin.rstrip("/") for origin in origins]

    @field_validator("enabled_stores", mode="before")
    @classmethod
    def _parse_enabled_stores(cls, value: object) -> object:
        return _split_list(value)

    @field_validator("enabled_stores")
    @classmethod
    def _validate_enabled_stores(cls, stores: list[str]) -> list[str]:
        normalised = [_check_store_slug(s.strip().lower()) for s in stores]
        if not normalised:
            raise ValueError("at least one store must be enabled")
        duplicates = sorted({s for s in normalised if normalised.count(s) > 1})
        if duplicates:
            raise ValueError(f"duplicate stores: {', '.join(duplicates)}")
        return normalised

    @field_validator("store_adapter_timeout_seconds", mode="before")
    @classmethod
    def _timeout_not_bool(cls, value: object) -> object:
        return _reject_bool_seconds(value, "STORE_ADAPTER_TIMEOUT_SECONDS")

    @field_validator(
        "access_token_ttl_seconds",
        "refresh_token_ttl_days",
        "trusted_proxy_count",
        "auth_rate_limit_window_seconds",
        "auth_rate_limit_per_ip",
        "auth_rate_limit_per_account",
        "auth_signup_limit_per_hour",
        "auth_refresh_limit_per_ip",
        "auth_max_sessions",
        "refresh_reuse_grace_seconds",
        "smtp_port",
        "smtp_timeout_seconds",
        "email_verify_ttl_hours",
        "password_reset_ttl_minutes",
        "otp_ttl_seconds",
        "otp_max_attempts",
        "otp_resend_cooldown_seconds",
        "otp_sends_per_hour",
        "redis_socket_timeout_seconds",
        "cache_ttl_seconds",
        "cache_partial_ttl_seconds",
        "cache_op_timeout_seconds",
        "cache_failure_backoff_seconds",
        "cache_max_entry_bytes",
        mode="before",
    )
    @classmethod
    def _numbers_not_bool(cls, value: object, info: Any) -> object:
        # bool is an int subclass: without this, `true` would silently become 1.
        if isinstance(value, bool):
            raise ValueError(
                f"{info.field_name.upper()} must be a number, not {str(value).lower()}"
            )
        return value

    @field_validator("store_adapter_timeouts", mode="before")
    @classmethod
    def _parse_store_timeouts(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            if value.startswith("{"):
                value = json.loads(value)
            else:
                pairs: dict[str, str] = {}
                for item in value.split(","):
                    slug, sep, seconds = item.partition("=")
                    if not sep:
                        raise ValueError(f"expected store=seconds, got {item.strip()!r}")
                    pairs[slug.strip()] = seconds.strip()
                return pairs
        if isinstance(value, dict):
            for slug, seconds in value.items():
                _reject_bool_seconds(seconds, f"timeout for {slug!r}")
        return value

    @field_validator("store_adapter_timeouts")
    @classmethod
    def _validate_store_timeouts(cls, timeouts: dict[str, float]) -> dict[str, float]:
        checked: dict[str, float] = {}
        for slug, seconds in timeouts.items():
            key = _check_store_slug(slug.strip().lower())
            if not 0 < seconds <= MAX_STORE_TIMEOUT_SECONDS:
                raise ValueError(
                    f"timeout for {key!r} must be > 0 and <= {MAX_STORE_TIMEOUT_SECONDS:g}s"
                )
            checked[key] = seconds
        return checked

    @model_validator(mode="after")
    def _production_safety(self) -> Self:
        if self.is_production and self.mock_adapter_failure_rate > 0:
            raise ValueError("MOCK_ADAPTER_FAILURE_RATE must be 0 in production")
        if self.is_production:
            secret = self.auth_secret_key.get_secret_value() if self.auth_secret_key else ""
            if len(secret) < MIN_SECRET_LENGTH or secret == EXAMPLE_SECRET:
                raise ValueError(
                    f"AUTH_SECRET_KEY must be set to a random value of at least "
                    f"{MIN_SECRET_LENGTH} characters in production"
                )
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
            if any(not o.startswith("https://") for o in self.cors_origins):
                raise ValueError("CORS_ORIGINS must all be https:// in production")
            if not self.frontend_url.startswith("https://"):
                raise ValueError("FRONTEND_URL must be https:// in production")
            if "dev_outbox" in (self.email_backend, self.sms_backend):
                raise ValueError(
                    "EMAIL_BACKEND/SMS_BACKEND=dev_outbox is not allowed in production"
                )
        if self.resolved_email_backend == "smtp" and not self.smtp_host:
            raise ValueError("EMAIL_BACKEND=smtp requires SMTP_HOST")
        if (self.google_client_id is None) != (self.google_client_secret is None):
            raise ValueError("set both GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or neither")
        return self

    @field_validator("frontend_url", "google_redirect_uri")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")) or "@" in value:
            raise ValueError("must be an http(s) URL without credentials")
        return value

    @field_validator("auth_secret_key")
    @classmethod
    def _secret_long_enough(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            # The value itself is never echoed in the error.
            raise ValueError(f"must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _force_asyncpg_driver(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith(("postgresql://", "postgres://")):
            return "postgresql+asyncpg://" + value.split("://", 1)[1]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def resolved_email_backend(self) -> EmailBackend:
        if self.email_backend is not None:
            return self.email_backend
        return "dev_outbox" if self.environment is Environment.DEVELOPMENT else "disabled"

    @property
    def resolved_sms_backend(self) -> SmsBackend:
        if self.sms_backend is not None:
            return self.sms_backend
        return "dev_outbox" if self.environment is Environment.DEVELOPMENT else "disabled"

    @property
    def google_enabled(self) -> bool:
        return self.google_client_id is not None and self.google_client_secret is not None

    @property
    def google_callback_url(self) -> str:
        return (
            self.google_redirect_uri or f"{self.frontend_url}{API_V1_PREFIX}/auth/google/callback"
        )

    @property
    def auth_signing_key(self) -> str:
        """The access-token signing key (ephemeral per process when not configured)."""
        if self.auth_secret_key is not None:
            return self.auth_secret_key.get_secret_value()
        return _EPHEMERAL_SECRET

    @property
    def sqlalchemy_url(self) -> str:
        return str(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
