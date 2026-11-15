"""Centralized configuration and runtime environment settings for Argus Control Plane."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArgusEnvironment(StrEnum):
    """Runtime execution environment tiers."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class ArgusSettings(BaseModel):
    """Immutable, validated configuration parameters for Argus Control Plane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    env: ArgusEnvironment = Field(default=ArgusEnvironment.DEVELOPMENT)
    auth_secret: str = Field(
        default="argus-local-dev-hmac-secret-key-2026",
        min_length=16,
        description="HMAC secret key used to sign and verify Bearer tokens.",
    )
    allow_anonymous: bool = Field(
        default=False,
        description="Permit unauthenticated requests (development/testing only).",
    )
    storage_backend: str = Field(
        default="memory",
        description="Persistence backend: 'memory', 'sqlite', or 'postgres'.",
    )
    db_path: str = Field(
        default=".argus_logs/argus.db",
        description="File path for SQLite persistence.",
    )
    cors_origins: tuple[str, ...] = Field(
        default=("*",),
        description="Permitted Cross-Origin Resource Sharing (CORS) origins.",
    )
    default_token_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        le=31536000,
        description="Default Bearer token TTL in seconds (default 24h).",
    )

    @classmethod
    def from_env(cls) -> ArgusSettings:
        """Construct ArgusSettings by inspecting environment variables."""
        raw_env = os.environ.get("ARGUS_ENV", "development").strip().lower()
        try:
            env = ArgusEnvironment(raw_env)
        except ValueError:
            env = ArgusEnvironment.DEVELOPMENT

        auth_secret = os.environ.get("ARGUS_AUTH_SECRET", "argus-local-dev-hmac-secret-key-2026")

        raw_anon = os.environ.get("ARGUS_ALLOW_ANONYMOUS", "").strip().lower()
        if raw_anon in ("1", "true", "yes"):
            allow_anonymous = True
        elif raw_anon in ("0", "false", "no"):
            allow_anonymous = False
        else:
            allow_anonymous = env == ArgusEnvironment.DEVELOPMENT

        storage_backend = os.environ.get("ARGUS_STORAGE_BACKEND", "memory").strip().lower()
        db_path = os.environ.get("ARGUS_DB_PATH", ".argus_logs/argus.db").strip()

        raw_cors = os.environ.get("ARGUS_CORS_ORIGINS", "*").strip()
        cors_origins = tuple(o.strip() for o in raw_cors.split(",") if o.strip())

        raw_ttl = os.environ.get("ARGUS_DEFAULT_TOKEN_TTL", "86400").strip()
        try:
            default_ttl = int(raw_ttl)
        except ValueError:
            default_ttl = 86400

        return cls(
            env=env,
            auth_secret=auth_secret,
            allow_anonymous=allow_anonymous,
            storage_backend=storage_backend,
            db_path=db_path,
            cors_origins=cors_origins or ("*",),
            default_token_ttl_seconds=default_ttl,
        )

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        """Enforce zero-tolerance security standards in production tier."""
        if self.env == ArgusEnvironment.PRODUCTION:
            if self.allow_anonymous:
                raise ValueError("ARGUS_ALLOW_ANONYMOUS cannot be true in production environment.")
            if len(self.auth_secret) < 32:
                raise ValueError(
                    "In production, ARGUS_AUTH_SECRET must be at least 32 characters long."
                )
            if "local-dev" in self.auth_secret or "argus-local" in self.auth_secret:
                raise ValueError(
                    "In production, default development HMAC secret key is strictly forbidden."
                )
        return self
