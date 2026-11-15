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
    # 3-Tier Loop Detector Circuit Breaker Settings
    loop_window_size: int = Field(
        default=15,
        ge=3,
        le=100,
        description="Sliding window size for loop observation history.",
    )
    loop_exact_threshold: int = Field(
        default=3,
        ge=2,
        le=20,
        description="Consecutive identical tool calls before tripping Tier 1.",
    )
    loop_oscillation_threshold: int = Field(
        default=2,
        ge=2,
        le=10,
        description="Cycle repetitions (A->B->A->B) before tripping Tier 2.",
    )
    loop_semantic_threshold: float = Field(
        default=0.65,
        ge=0.1,
        le=1.0,
        description="Cosine similarity threshold for Tier 3 semantic stagnation.",
    )
    loop_simhash_max_hamming: int = Field(
        default=3,
        ge=0,
        le=16,
        description="Maximum 64-bit SimHash Hamming distance for near-duplicate match.",
    )
    loop_max_tracked_sessions: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description="Maximum active sessions retained in loop history LRU cache.",
    )
    # Budget Guard Enforcer Settings
    budget_default_cap_usd: float = Field(
        default=50.0,
        gt=0.0,
        description="Default hard budget cap in USD for new agent sessions.",
    )
    budget_warning_threshold: float = Field(
        default=0.80,
        ge=0.10,
        le=0.99,
        description="Budget utilization ratio triggering proactive warning alerts.",
    )
    budget_enforce_http_402: bool = Field(
        default=False,
        description="Whether check-budget endpoint raises HTTP 402 by default on budget trip.",
    )
    # MCP Governance Proxy Settings
    mcp_enforce_injection_scan: bool = Field(
        default=True,
        description="Whether to scan MCP tool arguments and descriptions for injection threats.",
    )
    mcp_extra_destructive_patterns: tuple[str, ...] = Field(
        default=("truncate", "format", "kill", "wipe", "destroy"),
        description="Additional tool name substrings treated as destructive requiring C2 approval.",
    )
    # Worker Lease & Dead-Man's Switch Settings
    lease_default_ttl_seconds: float = Field(
        default=300.0,
        ge=5.0,
        le=86400.0,
        description="Default worker lease TTL in seconds (default: 5 min).",
    )
    lease_max_ttl_seconds: float = Field(
        default=3600.0,
        ge=30.0,
        le=604800.0,
        description="Maximum permissible worker lease TTL (default: 1 hour).",
    )
    lease_min_ttl_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=300.0,
        description="Minimum permissible worker lease TTL (default: 5 sec).",
    )
    lease_auto_reaper_enabled: bool = Field(
        default=False,
        description="Whether to run background autonomous lease reaper loop.",
    )
    lease_reap_interval_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=3600.0,
        description="Interval between background dead-man lease reaper sweeps in seconds.",
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

        def _get_int(var: str, default: int) -> int:
            val = os.environ.get(var, "").strip()
            if not val:
                return default
            try:
                return int(val)
            except ValueError:
                return default

        def _get_float(var: str, default: float) -> float:
            val = os.environ.get(var, "").strip()
            if not val:
                return default
            try:
                return float(val)
            except ValueError:
                return default

        raw_402 = os.environ.get("ARGUS_BUDGET_ENFORCE_HTTP_402", "").strip().lower()
        budget_402 = raw_402 in ("1", "true", "yes")

        raw_scan = os.environ.get("ARGUS_MCP_ENFORCE_INJECTION_SCAN", "1").strip().lower()
        mcp_scan = raw_scan not in ("0", "false", "no")

        raw_extra = os.environ.get("ARGUS_MCP_EXTRA_DESTRUCTIVE", "").strip()
        extra_destructive = tuple(p.strip() for p in raw_extra.split(",") if p.strip())

        raw_auto_reap = os.environ.get("ARGUS_LEASE_AUTO_REAPER_ENABLED", "").strip().lower()
        lease_auto_reap = raw_auto_reap in ("1", "true", "yes")

        return cls(
            env=env,
            auth_secret=auth_secret,
            allow_anonymous=allow_anonymous,
            storage_backend=storage_backend,
            db_path=db_path,
            cors_origins=cors_origins or ("*",),
            default_token_ttl_seconds=default_ttl,
            loop_window_size=_get_int("ARGUS_LOOP_WINDOW_SIZE", 15),
            loop_exact_threshold=_get_int("ARGUS_LOOP_EXACT_THRESHOLD", 3),
            loop_oscillation_threshold=_get_int("ARGUS_LOOP_OSCILLATION_THRESHOLD", 2),
            loop_semantic_threshold=_get_float("ARGUS_LOOP_SEMANTIC_THRESHOLD", 0.65),
            loop_simhash_max_hamming=_get_int("ARGUS_LOOP_SIMHASH_MAX_HAMMING", 3),
            loop_max_tracked_sessions=_get_int("ARGUS_LOOP_MAX_TRACKED_SESSIONS", 10000),
            budget_default_cap_usd=_get_float("ARGUS_BUDGET_DEFAULT_CAP", 50.0),
            budget_warning_threshold=_get_float("ARGUS_BUDGET_WARNING_THRESHOLD", 0.80),
            budget_enforce_http_402=budget_402,
            mcp_enforce_injection_scan=mcp_scan,
            mcp_extra_destructive_patterns=extra_destructive
            or ("truncate", "format", "kill", "wipe", "destroy"),
            lease_default_ttl_seconds=_get_float("ARGUS_LEASE_DEFAULT_TTL", 300.0),
            lease_max_ttl_seconds=_get_float("ARGUS_LEASE_MAX_TTL", 3600.0),
            lease_min_ttl_seconds=_get_float("ARGUS_LEASE_MIN_TTL", 5.0),
            lease_auto_reaper_enabled=lease_auto_reap,
            lease_reap_interval_seconds=_get_float("ARGUS_LEASE_REAP_INTERVAL", 30.0),
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
