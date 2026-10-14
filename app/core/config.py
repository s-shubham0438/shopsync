"""Application settings loaded from environment variables / `.env`."""

import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

API_V1_PREFIX = "/api/v1"

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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

    # --- Caching ---
    cache_ttl_seconds: int = Field(default=1800, ge=0)

    # --- Health ---
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

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
    def sqlalchemy_url(self) -> str:
        return str(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
