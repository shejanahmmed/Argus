"""Unit tests for ArgusSettings, zero-trust production validation, and Role hierarchy."""

from __future__ import annotations

import argparse

import pytest
from pydantic import ValidationError

from argus.cli.main import handle_issue_token
from argus.core.config import ArgusEnvironment, ArgusSettings
from argus.core.errors import AuthorizationError, TenantIsolationError
from argus.core.tenancy import Role, TenantContext
from argus.security.auth import HmacTokenAuthenticator


def test_settings_development_defaults() -> None:
    settings = ArgusSettings(env=ArgusEnvironment.DEVELOPMENT)
    assert settings.env == ArgusEnvironment.DEVELOPMENT
    assert settings.allow_anonymous is False  # By default false unless specified
    assert len(settings.auth_secret) >= 16


def test_settings_production_security_validation() -> None:
    # 1. Reject anonymous in production
    with pytest.raises(ValidationError, match="ARGUS_ALLOW_ANONYMOUS cannot be true"):
        ArgusSettings(
            env=ArgusEnvironment.PRODUCTION,
            allow_anonymous=True,
            auth_secret="a" * 32,
        )

    # 2. Reject short secrets in production (< 32 chars)
    with pytest.raises(ValidationError, match="at least 32 characters"):
        ArgusSettings(
            env=ArgusEnvironment.PRODUCTION,
            allow_anonymous=False,
            auth_secret="short-secret-key-16-chars",
        )

    # 3. Reject default dev secret in production
    with pytest.raises(ValidationError, match="default development HMAC secret"):
        ArgusSettings(
            env=ArgusEnvironment.PRODUCTION,
            allow_anonymous=False,
            auth_secret="argus-local-dev-hmac-secret-key-2026",
        )

    # 4. Valid production settings succeed
    valid_prod = ArgusSettings(
        env=ArgusEnvironment.PRODUCTION,
        allow_anonymous=False,
        auth_secret="super-strong-production-hmac-secret-2026-xyz-abc",
    )
    assert valid_prod.env == ArgusEnvironment.PRODUCTION


def test_role_hierarchy_and_privileges() -> None:
    admin = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a1", role=Role.ADMIN)
    operator = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a2", role=Role.OPERATOR)
    ingestor = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a3", role=Role.INGESTOR)
    viewer = TenantContext(tenant_id="t1", workspace_id="w1", actor_id="a4", role=Role.VIEWER)

    # Hierarchy verification
    assert admin.has_role(Role.ADMIN)
    assert admin.has_role(Role.OPERATOR)
    assert admin.has_role(Role.VIEWER)

    assert operator.has_role(Role.OPERATOR)
    assert operator.has_role(Role.INGESTOR)
    assert not operator.has_role(Role.ADMIN)

    assert ingestor.has_role(Role.INGESTOR)
    assert not ingestor.has_role(Role.OPERATOR)

    assert viewer.has_role(Role.VIEWER)
    assert not viewer.has_role(Role.INGESTOR)

    # C2 Mutations
    admin.assert_can_mutate_c2()
    operator.assert_can_mutate_c2()
    with pytest.raises(AuthorizationError):
        ingestor.assert_can_mutate_c2()
    with pytest.raises(AuthorizationError):
        viewer.assert_can_mutate_c2()

    # Token Issuance
    admin.assert_can_issue_tokens()
    with pytest.raises(AuthorizationError, match="Admin privilege required"):
        operator.assert_can_issue_tokens()
    with pytest.raises(AuthorizationError):
        viewer.assert_can_issue_tokens()

    # Isolation
    admin.assert_same_tenant("t1", "w1")
    with pytest.raises(TenantIsolationError):
        admin.assert_same_tenant("foreign_t", "w1")


def test_cli_issue_token(capsys: pytest.CaptureFixture[str]) -> None:
    secret = "cli-test-secret-key-32-chars-long-12345"
    args = argparse.Namespace(
        tenant="cyberdyne",
        workspace="skynet",
        actor="t800",
        role=Role.ADMIN.value,
        ttl=3600,
        secret=secret,
    )
    ret = handle_issue_token(args)
    assert ret == 0

    captured = capsys.readouterr().out
    assert "TOKEN: argus_tok." in captured

    # Extract token and verify
    token_line = next(line for line in captured.splitlines() if line.startswith("TOKEN: "))
    token = token_line.replace("TOKEN: ", "").strip()

    authenticator = HmacTokenAuthenticator(secret_key=secret)
    verified_ctx = authenticator.verify_token(token)
    assert verified_ctx.tenant_id == "cyberdyne"
    assert verified_ctx.workspace_id == "skynet"
    assert verified_ctx.actor_id == "t800"
    assert verified_ctx.role == Role.ADMIN
